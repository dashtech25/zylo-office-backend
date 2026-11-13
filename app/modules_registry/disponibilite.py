"""Disponibilité tenant-module : activation et désactivation d'une installation (BE-048).

Une installation technique (BE-047) est `installed`. Ce service la rend utilisable par
l'organisation (`active`) ou la retire de l'usage (`inactive`), en passant par la machine à états
`transitions.py` (BE-041) qui journalise chaque transition et contrôle la version d'état.

Activation (`executer_activation`), dans l'ordre :

1. installation absente ou `removed` -> 409 `MODULE_ACTIVATION_GUARD_FAILED` (garde `installed`) ;
2. `stateVersion` fourni différent de la version courante -> 409 `MODULE_STATE_VERSION_CONFLICT` ;
3. gardes, dans cet ordre, avant toute écriture (une garde en échec ne change pas l'état) :
   - `installed` : l'état doit être `installed`, `inactive` ou `inactive_error` ; tout autre état
     (`failed`, `provisioning`, `removed`, etc.) -> 409 `MODULE_ACTIVATION_GUARD_FAILED` ;
   - `entitlement` : l'organisation doit avoir un entitlement effectif pour ce module (BE-045). Il n'y
     a aucun accès implicite : une organisation sans ligne d'entitlement est refusée. -> 409
     `ENTITLEMENT_REQUIRED` ;
   - `dependencies` : chaque module listé dans `prerequisites` de la version doit être `active` dans
     l'organisation -> 409 `MODULE_ACTIVATION_GUARD_FAILED` (garde `dependencies`) ;
   - `confirmation` : `confirm` doit valoir `true` -> 409 `MODULE_ACTIVATION_GUARD_FAILED`
     (garde `confirmation`).
4. transition `installed|inactive|inactive_error -> activation_pending`, puis exécution de
   l'activation par le fournisseur (`FournisseurActivation`) :
   - succès : transition `activation_pending -> active`, `lastErrorCode` vide ;
   - exception : transition `activation_pending -> inactive_error`, `lastErrorCode` =
     `MODULE_ACTIVATION_FAILED`. L'exception n'est pas propagée (la transaction doit rester valide pour
     journaliser l'état) et seul son type est journalisé.

Un état `active` n'est donc jamais posé par défaut : il n'est atteint qu'après le succès du fournisseur.

Désactivation (`executer_desactivation`) :

1. mêmes contrôles de version et de confirmation que l'activation ;
2. dépendants : tout module de l'organisation, à l'état `active`, dont la version liste le module
   désactivé dans ses `prerequisites` -> 409 `MODULE_HAS_ACTIVE_DEPENDANTS`, avec la liste des
   dépendants dans `details` (`moduleId`, `moduleCode`) ;
3. transition `active -> inactive`. Un module qui n'est pas `active` est refusé par la machine à états
   (409 `MODULE_TRANSITION_NOT_ALLOWED`).

Suspension (BE-049, `executer_suspension`) : `active -> suspended`, avec une origine parmi `client`,
`commercial`, `security` et un motif obligatoire (validés par le schéma : 422 sinon). Le droit exigé
dépend de l'origine, contrôlé par `verifier_droit_suspension` avant le service : `client` demande
`organization.module.suspend` dans l'organisation ; `commercial` et `security` demandent le droit
plateforme `platform.module.suspend` (allowlist d'environnement). Le motif, l'origine et l'acteur sont
recopiés sur l'installation (`suspensionOrigin`, `suspensionReason`, `suspendedBy`) et journalisés.
La matrice nomme un état `suspending` ; il n'existe pas dans la machine à états (BE-041) : la
suspension passe directement à `suspended`.

Tant que le module est `suspended`, l'activation et la désactivation sont refusées en 409
`MODULE_SUSPENDED` (CA-3), avant tout autre contrôle. La lecture reste possible (route GET).

Reprise (BE-049, `executer_reactivation`) : `suspended -> active`, dans l'ordre :

1. installation absente -> 404 ; `stateVersion` obsolète -> 409 `MODULE_STATE_VERSION_CONFLICT` (CA-5) ;
2. release : la version de manifeste du module doit être supportée
   (`VERSIONS_MANIFESTE_SUPPORTEES`), sinon 409 `MODULE_RELEASE_INCOMPATIBLE` ;
3. entitlement : doit être effectif (BE-045), sinon 409 `ENTITLEMENT_REQUIRED` (CA-4) ;
4. transition `suspended -> active`, motif = `resolutionReference`, colonnes de suspension vidées.

Le droit de reprise est celui de l'origine de la suspension (vérifié par la route). Une reprise hors
d'un état `suspended` est refusée par la machine à états (409 `MODULE_TRANSITION_NOT_ALLOWED`).

Isolation : toutes les lectures sont filtrées par `organizationId` ; une installation d'une autre
organisation est introuvable (la route renvoie 404 avant d'arriver ici, via les permissions).

Les fonctions ne font que `flush` : la transaction est validée par l'appelant (la route), comme dans
`installation.py` et `transitions.py`.
"""

import logging
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.manifeste import VERSIONS_MANIFESTE_SUPPORTEES
from app.modules_registry.models import Module, ModuleInstallation, ModuleVersion
from app.modules_registry.permissions import (
    ORGANIZATION_MODULE_SUSPEND,
    PLATFORM_MODULE_SUSPEND,
)
from app.modules_registry.platform_rights import a_droit_plateforme, exiger_droit_plateforme
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION, transitionner
from app.rbac.service import user_has_permission

logger = logging.getLogger("app.modules_registry.disponibilite")

ORIGINE_DISPONIBILITE = "client"
CODE_ACTIVATION_ECHEC = "MODULE_ACTIVATION_FAILED"
# États depuis lesquels une activation est tentée. `failed`, `provisioning`, `removed`, etc. ne le sont pas.
ETATS_ACTIVABLES: tuple[str, ...] = ("installed", "inactive", "inactive_error")
# Un module ouvre ses prérequis seulement s'il est `active` (pas seulement installé).
ETAT_ACTIF = "active"
# Suspension et reprise (BE-049). `suspending` de la matrice n'existe pas dans la machine à états.
ETAT_SUSPENDU = "suspended"
ORIGINE_CLIENT = "client"
ORIGINES_SUSPENSION: tuple[str, ...] = ("client", "commercial", "security")
CODE_MODULE_SUSPENDU = "MODULE_SUSPENDED"
CODE_RELEASE_INCOMPATIBLE = "MODULE_RELEASE_INCOMPATIBLE"
# Garde nommées, présentes dans `details` du 409 MODULE_ACTIVATION_GUARD_FAILED.
GARDE_INSTALLED = "installed"
GARDE_DEPENDANCES = "dependencies"
GARDE_CONFIRMATION = "confirmation"


class FournisseurActivation(Protocol):
    """Contrat d'exécution technique d'une activation (passage de `activation_pending`).

    `activer` lève une exception si l'activation échoue ; l'appelant la traduit en `inactive_error`."""

    async def activer(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None: ...


class FournisseurActivationSimule:
    """Fournisseur par défaut : réussit sans effet externe (aucun adaptateur réel n'existe encore)."""

    async def activer(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None:
        return None


def _garde_en_echec(garde: str, message: str) -> AppError:
    """409 MODULE_ACTIVATION_GUARD_FAILED portant le nom de la garde en échec."""
    return AppError(
        code="MODULE_ACTIVATION_GUARD_FAILED",
        message=message,
        status_code=409,
        details=[{"guard": garde}],
    )


async def _installation_courante(
    db: AsyncSession, organization_id: uuid.UUID, module_id: uuid.UUID
) -> ModuleInstallation | None:
    """Renvoie l'installation non `removed` du couple (organisation, module), ou None."""
    return (
        await db.execute(
            select(ModuleInstallation).where(
                ModuleInstallation.organizationId == organization_id,
                ModuleInstallation.moduleId == module_id,
                ModuleInstallation.state != "removed",
            )
        )
    ).scalar_one_or_none()


async def _transitionner(
    db: AsyncSession,
    installation: ModuleInstallation,
    *,
    vers_etat: str,
    acteur_id: uuid.UUID,
    organisation_id: uuid.UUID,
    module_id: uuid.UUID,
    cle: str,
    origine: str = ORIGINE_DISPONIBILITE,
    motif: str | None = None,
) -> None:
    """Journalise une transition de disponibilité et recopie état et version sur l'installation.

    La clé d'idempotence est dérivée de la commande (`cle`), suffixée par l'état cible. `origine` vaut
    `client` pour l'activation et la désactivation, l'origine de la suspension pour la suspension
    (BE-049) ; `motif` est journalisé tel quel (motif de suspension, référence de résolution)."""
    ligne = await transitionner(
        db,
        type_sujet=TYPE_SUJET_INSTALLATION,
        id_sujet=installation.id,
        vers_etat=vers_etat,
        version_attendue=installation.stateVersion,
        acteur_id=acteur_id,
        origine=origine,
        cle_idempotence=f"{cle}:{vers_etat}",
        organisation_id=organisation_id,
        operation_id=installation.operationId,
        module_id=module_id,
        motif=motif,
    )
    installation.state = ligne.toState
    installation.stateVersion = ligne.stateVersionAfter


async def _entitlement_effectif(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> bool:
    """Vrai seulement si l'entitlement effectif du module est `active` (projection BE-045).

    Une organisation sans ligne d'entitlement (`not_configured`) n'a pas d'accès : BE-048 ne reprend
    pas l'accès implicite de l'ancien garde d'entitlement."""
    from app.modules_registry.service import get_module_entitlement_access

    access_state, _allowed = await get_module_entitlement_access(db, organization_id, module_code)
    return access_state == "active"


async def _etat_des_prerequis(db: AsyncSession, organization_id: uuid.UUID, version: ModuleVersion) -> list[str]:
    """Renvoie les codes des prérequis de `version` qui ne sont pas `active` dans l'organisation."""
    manquants: list[str] = []
    for prerequis in version.prerequisites or []:
        code = prerequis.get("code") if isinstance(prerequis, dict) else None
        if not isinstance(code, str):
            manquants.append(repr(prerequis))
            continue
        actif = (
            await db.execute(
                select(ModuleInstallation.id)
                .join(Module, Module.id == ModuleInstallation.moduleId)
                .where(
                    ModuleInstallation.organizationId == organization_id,
                    Module.code == code,
                    ModuleInstallation.state == ETAT_ACTIF,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if actif is None:
            manquants.append(code)
    return manquants


def _verifier_version(installation: ModuleInstallation, state_version: int) -> None:
    """Version d'état attendue : 409 MODULE_STATE_VERSION_CONFLICT si elle n'est pas la courante."""
    if state_version != installation.stateVersion:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue {state_version}, courante {installation.stateVersion}.",
            status_code=409,
        )


def _refuser_si_suspendu(installation: ModuleInstallation) -> None:
    """Garde BE-049 (CA-3) : une mutation sensible est refusée pendant `suspended`."""
    if installation.state == ETAT_SUSPENDU:
        raise AppError(
            code=CODE_MODULE_SUSPENDU,
            message="Module suspendu : cette mutation est refusée jusqu'à la reprise.",
            status_code=409,
        )


async def _verifier_version_et_confirmation(
    installation: ModuleInstallation, state_version: int, confirm: bool
) -> None:
    """Contrôles communs : version d'état attendue, puis confirmation explicite."""
    _verifier_version(installation, state_version)
    if confirm is not True:
        raise _garde_en_echec(GARDE_CONFIRMATION, "Confirmation explicite requise (confirm: true).")


async def executer_activation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    state_version: int,
    confirm: bool,
    fournisseur: FournisseurActivation | None = None,
) -> ModuleInstallation:
    """Active le module pour l'organisation, selon les gardes décrites dans la docstring du module.

    Renvoie l'installation dans son état final : `active`, ou `inactive_error` avec
    `lastErrorCode = MODULE_ACTIVATION_FAILED` si le fournisseur a échoué (réponse non fautive).
    Lève `AppError` pour les refus préalables ; aucune écriture n'a lieu dans ces cas.
    """
    installation = await _installation_courante(db, organization_id, module_id)
    if installation is None:
        raise _garde_en_echec(GARDE_INSTALLED, "Aucune installation de ce module pour l'organisation.")
    _refuser_si_suspendu(installation)
    await _verifier_version_et_confirmation(installation, state_version, confirm)
    if installation.state not in ETATS_ACTIVABLES:
        raise _garde_en_echec(
            GARDE_INSTALLED, f"Installation dans l'état {installation.state} : activation impossible."
        )

    module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()
    if not await _entitlement_effectif(db, organization_id, module.code):
        raise AppError(
            code="ENTITLEMENT_REQUIRED",
            message="Aucun entitlement effectif pour ce module : activation refusée.",
            status_code=409,
        )
    version = (
        await db.execute(select(ModuleVersion).where(ModuleVersion.id == installation.moduleVersionId))
    ).scalar_one()
    manquants = await _etat_des_prerequis(db, organization_id, version)
    if manquants:
        raise _garde_en_echec(GARDE_DEPENDANCES, f"Prérequis non actifs : {', '.join(manquants)}.")

    cle = f"activation:{installation.operationId}:{installation.stateVersion}"
    transition = {
        "acteur_id": acteur_id,
        "organisation_id": organization_id,
        "module_id": module_id,
        "cle": cle,
    }
    await _transitionner(db, installation, vers_etat="activation_pending", **transition)

    executeur = fournisseur if fournisseur is not None else FournisseurActivationSimule()
    try:
        await executeur.activer(installation.id, version.id)
    except Exception as exc:
        # Seul le type de l'exception est journalisé : son message peut contenir des secrets.
        logger.warning("Activation en échec pour l'installation %s : %s", installation.id, type(exc).__name__)
        installation.lastErrorCode = CODE_ACTIVATION_ECHEC
        await _transitionner(db, installation, vers_etat="inactive_error", **transition)
        return installation

    installation.lastErrorCode = None
    await _transitionner(db, installation, vers_etat="active", **transition)
    return installation


async def _dependants_actifs(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> list[dict]:
    """Modules `active` de l'organisation qui listent `module_code` dans leurs prérequis."""
    lignes = (
        await db.execute(
            select(ModuleInstallation, ModuleVersion, Module)
            .join(ModuleVersion, ModuleVersion.id == ModuleInstallation.moduleVersionId)
            .join(Module, Module.id == ModuleInstallation.moduleId)
            .where(
                ModuleInstallation.organizationId == organization_id,
                ModuleInstallation.state == ETAT_ACTIF,
            )
        )
    ).all()
    dependants: list[dict] = []
    for _installation, version, module in lignes:
        for prerequis in version.prerequisites or []:
            if isinstance(prerequis, dict) and prerequis.get("code") == module_code:
                dependants.append({"moduleId": str(module.id), "moduleCode": module.code})
                break
    return dependants


async def executer_desactivation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    state_version: int,
    confirm: bool,
) -> ModuleInstallation:
    """Désactive le module (`active -> inactive`) s'il n'a aucun dépendant `active`.

    Lève 409 `MODULE_HAS_ACTIVE_DEPENDANTS` avec la liste des dépendants dans `details`, ou
    409 `MODULE_TRANSITION_NOT_ALLOWED` (par la machine à états) si le module n'est pas `active`.
    """
    installation = await _installation_courante(db, organization_id, module_id)
    if installation is None:
        raise AppError(code="MODULE_INSTALLATION_NOT_FOUND", message="Installation introuvable.", status_code=404)
    _refuser_si_suspendu(installation)
    await _verifier_version_et_confirmation(installation, state_version, confirm)

    module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()
    dependants = await _dependants_actifs(db, organization_id, module.code)
    if dependants:
        raise AppError(
            code="MODULE_HAS_ACTIVE_DEPENDANTS",
            message="Des modules actifs dépendent de ce module : désactivation refusée.",
            status_code=409,
            details=dependants,
        )

    cle = f"desactivation:{installation.operationId}:{installation.stateVersion}"
    installation.lastErrorCode = None
    await _transitionner(
        db, installation, vers_etat="inactive", acteur_id=acteur_id,
        organisation_id=organization_id, module_id=module_id, cle=cle,
    )
    return installation


async def verifier_droit_suspension(
    db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID, origine: str
) -> None:
    """Contrôle le droit de poser ou de reprendre une suspension d'origine `origine` (BE-049).

    `client` exige `organization.module.suspend` dans l'organisation ; `commercial` et `security`
    exigent le droit plateforme `platform.module.suspend`. Refus : 403 (`permission_denied` pour le
    droit d'organisation, `PERMISSION_DENIED` pour le droit plateforme). Appelé par la route, avant
    le service, pour qu'un acteur non autorisé ne puisse pas déduire l'état par le code de réponse.
    """
    if origine == ORIGINE_CLIENT:
        if not await user_has_permission(db, user_id, organization_id, ORGANIZATION_MODULE_SUSPEND):
            raise AppError(
                code="permission_denied",
                message=f"Permission manquante : {ORGANIZATION_MODULE_SUSPEND}.",
                status_code=403,
            )
        return
    exiger_droit_plateforme(user_id, PLATFORM_MODULE_SUSPEND)


async def executer_suspension(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    origine: str,
    motif: str,
    state_version: int,
) -> ModuleInstallation:
    """Suspend le module (`active -> suspended`) avec son origine, son motif et son acteur.

    Ordre : installation absente -> 404 ; version d'état obsolète -> 409
    `MODULE_STATE_VERSION_CONFLICT` ; origine hors `ORIGINES_SUSPENSION` -> 422 (défense en
    profondeur, le schéma la valide déjà) ; module non `active` -> 409 `MODULE_TRANSITION_NOT_ALLOWED`
    (par la machine à états). Aucune écriture en cas de refus.
    """
    installation = await _installation_courante(db, organization_id, module_id)
    if installation is None:
        raise AppError(code="MODULE_INSTALLATION_NOT_FOUND", message="Installation introuvable.", status_code=404)
    _verifier_version(installation, state_version)
    if origine not in ORIGINES_SUSPENSION:
        raise AppError(
            code="VALIDATION_ERROR", message="Origine de suspension inconnue.", status_code=422,
        )

    cle = f"suspension:{installation.operationId}:{installation.stateVersion}"
    await _transitionner(
        db, installation, vers_etat=ETAT_SUSPENDU, acteur_id=acteur_id,
        organisation_id=organization_id, module_id=module_id, cle=cle, origine=origine, motif=motif,
    )
    installation.suspensionOrigin = origine
    installation.suspensionReason = motif
    installation.suspendedBy = acteur_id
    return installation


async def executer_reactivation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    state_version: int,
    resolution_reference: str,
) -> ModuleInstallation:
    """Reprend un module `suspended` (`suspended -> active`) si release et entitlement le permettent.

    Gardes dans l'ordre (voir la docstring du module) : version d'état (CA-5), release (409
    `MODULE_RELEASE_INCOMPATIBLE`), entitlement effectif (CA-4, 409 `ENTITLEMENT_REQUIRED`). Les gardes
    de release et d'entitlement ne s'appliquent qu'à un module `suspended` ; hors suspension, la
    machine à états refuse la transition. En cas de refus, l'état reste `suspended`.
    `resolution_reference` est journalisée comme motif de la transition ; les colonnes de suspension
    sont vidées.
    """
    installation = await _installation_courante(db, organization_id, module_id)
    if installation is None:
        raise AppError(code="MODULE_INSTALLATION_NOT_FOUND", message="Installation introuvable.", status_code=404)
    _verifier_version(installation, state_version)

    if installation.state == ETAT_SUSPENDU:
        module = (await db.execute(select(Module).where(Module.id == module_id))).scalar_one()
        if module.manifestVersion not in VERSIONS_MANIFESTE_SUPPORTEES:
            raise AppError(
                code=CODE_RELEASE_INCOMPATIBLE,
                message="Release du module non supportée : reprise refusée.",
                status_code=409,
            )
        if not await _entitlement_effectif(db, organization_id, module.code):
            raise AppError(
                code="ENTITLEMENT_REQUIRED",
                message="Aucun entitlement effectif pour ce module : reprise refusée.",
                status_code=409,
            )

    cle = f"reprise:{installation.operationId}:{installation.stateVersion}"
    await _transitionner(
        db, installation, vers_etat=ETAT_ACTIF, acteur_id=acteur_id,
        organisation_id=organization_id, module_id=module_id, cle=cle, motif=resolution_reference,
    )
    installation.suspensionOrigin = None
    installation.suspensionReason = None
    installation.suspendedBy = None
    return installation


EXPLICATIONS_ETAT: dict[str, str] = {
    "installed": "Installé, non activé : l'activation est possible après vérification des gardes.",
    "inactive": "Installé et désactivé : l'activation est possible après vérification des gardes.",
    "active": "Activé et disponible pour l'organisation.",
    "activation_pending": "Activation en cours.",
    "inactive_error": "Dernière activation en échec : le module reste inactif ; une nouvelle tentative est possible.",
    "failed": "Installation en échec : aucune activation possible.",
}


def expliquer_etat(etat: str) -> str:
    """Explication lisible de l'état de disponibilité (renvoyée par la lecture, BE-048)."""
    return EXPLICATIONS_ETAT.get(etat, f"État {etat} : aucune activation possible en l'état.")
