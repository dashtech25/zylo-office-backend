"""Installation technique d'un module pour une organisation (BE-047).

Ce service crée l'installation d'une version publiée de module pour un tenant, puis la fait avancer
dans la matrice d'états `tenant_module` (BE-041). Séquence nominale :

    not_installed -> preflight -> provisioning -> installed

Ordre des vérifications préalables (avant toute écriture, donc sans ligne ni transition en cas de
refus) :

1. version absente ou rattachée à un autre module -> `MODULE_VERSION_NOT_FOUND` (404) ;
2. version non `published` -> `MODULE_VERSION_NOT_PUBLISHED` (422) ;
3. compatibilité (BE-044) différente de `compatible` :
   - motif `PREREQUISITE_MISSING` -> `MODULE_PREREQUISITE_MISSING` (409) ;
   - sinon -> `MODULE_VERSION_INCOMPATIBLE` (409). Une évaluation `unknown` est refusée aussi :
     l'installation échoue fermée plutôt que d'installer une version dont on ignore la compatibilité ;
4. prérequis (liste `prerequisites` de la version) : chacun doit être installé dans l'organisation
   (état dans `ETATS_INSTALLES`), sinon `MODULE_PREREQUISITE_MISSING` (409) ;
5. une installation non `removed` existe déjà pour `(organisation, module)` ->
   `MODULE_ALREADY_INSTALLED` (409). Garanti aussi par l'index unique partiel de la base ;
6. `stateVersion` fourni différent de 0 (aucune installation en cours) -> `MODULE_STATE_VERSION_CONFLICT`
   (409).

Les autorisations (`organization.module.install`) et la validation de l'en-tête `Idempotency-Key` sont
faites par la route, avant d'appeler ce service. La route encadre l'appel par `core/idempotency`
(`run_idempotent`) : un rejeu de la même clé renvoie la réponse initiale, avec le même `operationId`,
sans nouvelle écriture.

Provisionnement : l'exécution technique est déléguée à un fournisseur (protocole
`FournisseurProvisionnement`). Le fournisseur par défaut, `FournisseurSimule`, réussit sans effet
externe ; les tests injectent un fournisseur enregistreur ou en échec. Une exception levée par le
fournisseur place l'installation en `failed` avec `lastErrorCode = MODULE_PROVISIONING_FAILED`. Cet
échec n'est PAS propagé : la transaction doit rester valide pour journaliser l'état `failed`. Aucun
chemin de ce service ne mène à `active` : cette transition relève de BE-048 et `failed` ne l'autorise
pas (BE-041).

Les fonctions ne font que `flush` : la transaction est validée par l'appelant (la route, via
`run_idempotent`), comme dans `transitions.py`.
"""

import logging
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry import catalogue_publication, compatibilite_service
from app.modules_registry.models import Module, ModuleInstallation
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION, transitionner

logger = logging.getLogger("app.modules_registry.installation")

ORIGINE_INSTALLATION = "client"
CODE_PROVISIONNEMENT_ECHEC = "MODULE_PROVISIONING_FAILED"
# États d'une installation qui comptent comme « installé » pour un prérequis (installation réussie,
# quelle que soit son activation). `failed`, `provisioning` et `removed` ne comptent pas.
ETATS_INSTALLES: tuple[str, ...] = ("installed", "inactive", "active", "suspended")
MOTIF_PREREQUIS_ABSENT = "PREREQUISITE_MISSING"


class FournisseurProvisionnement(Protocol):
    """Contrat d'exécution technique d'une installation.

    `provisionner` lève une exception si l'exécution échoue ; l'appelant la traduit en `failed`."""

    async def provisionner(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None: ...


class FournisseurSimule:
    """Fournisseur par défaut : réussit sans effet externe (aucun adaptateur réel n'existe encore)."""

    async def provisionner(self, installation_id: uuid.UUID, module_version_id: uuid.UUID) -> None:
        return None


async def _installation_active(
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


async def _verifier_prerequis(db: AsyncSession, organization_id: uuid.UUID, prerequisites: list | None) -> None:
    """Lève `MODULE_PREREQUISITE_MISSING` (409) si un prérequis n'est pas installé dans l'organisation.

    Un prérequis mal formé (sans `code` textuel) est refusé de la même manière : la compatibilité
    (BE-044) l'a déjà signalé, et l'installation ne doit jamais l'ignorer."""
    for prerequis in prerequisites or []:
        code = prerequis.get("code") if isinstance(prerequis, dict) else None
        if not isinstance(code, str):
            raise AppError(
                code="MODULE_PREREQUISITE_MISSING",
                message="Prérequis mal formé dans la version.",
                status_code=409,
            )
        installe = (
            await db.execute(
                select(ModuleInstallation.id)
                .join(Module, Module.id == ModuleInstallation.moduleId)
                .where(
                    ModuleInstallation.organizationId == organization_id,
                    Module.code == code,
                    ModuleInstallation.state.in_(ETATS_INSTALLES),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if installe is None:
            raise AppError(
                code="MODULE_PREREQUISITE_MISSING",
                message=f"Prérequis non installé dans l'organisation : {code}.",
                status_code=409,
            )


async def _verifier_compatibilite(db: AsyncSession, module_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Lève 409 si la version n'est pas `compatible` (BE-044). Le motif de prérequis a son code propre."""
    evaluation = await compatibilite_service.evaluer_version(db, module_id, version_id)
    if evaluation.result == "compatible":
        return
    if any(isinstance(motif, dict) and motif.get("motif") == MOTIF_PREREQUIS_ABSENT for motif in evaluation.reasons):
        raise AppError(
            code="MODULE_PREREQUISITE_MISSING",
            message="Prérequis absent du catalogue publié.",
            status_code=409,
        )
    raise AppError(
        code="MODULE_VERSION_INCOMPATIBLE",
        message=f"Version non compatible : {evaluation.result}.",
        status_code=409,
    )


async def _transitionner_installation(
    db: AsyncSession,
    installation: ModuleInstallation,
    *,
    vers_etat: str,
    acteur_id: uuid.UUID,
    cle: str,
    organisation_id: uuid.UUID,
    module_id: uuid.UUID,
) -> None:
    """Journalise une transition de l'installation et recopie état et version sur la ligne.

    La clé d'idempotence de chaque transition est dérivée de la clé de la commande, suffixée par
    l'état cible, pour rester unique par sujet."""
    ligne = await transitionner(
        db,
        type_sujet=TYPE_SUJET_INSTALLATION,
        id_sujet=installation.id,
        vers_etat=vers_etat,
        version_attendue=installation.stateVersion,
        acteur_id=acteur_id,
        origine=ORIGINE_INSTALLATION,
        cle_idempotence=f"{cle}:{vers_etat}",
        organisation_id=organisation_id,
        operation_id=installation.operationId,
        module_id=module_id,
    )
    installation.state = ligne.toState
    installation.stateVersion = ligne.stateVersionAfter


async def executer_installation(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    module_version_id: uuid.UUID,
    state_version: int,
    cle_idempotence: str,
    fournisseur: FournisseurProvisionnement | None = None,
) -> ModuleInstallation:
    """Crée l'installation de `module_version_id` pour `organization_id` et la mène à `installed`.

    Paramètres :
    - `state_version` : version d'état attendue par l'appelant ; 0 pour une organisation sans
      installation en cours (autre valeur -> `MODULE_STATE_VERSION_CONFLICT`) ;
    - `cle_idempotence` : clé de la commande, dérivée pour chaque transition journalisée ;
    - `fournisseur` : exécution technique ; `FournisseurSimule` par défaut.

    Renvoie la ligne d'installation dans son état final : `installed`, ou `failed` avec
    `lastErrorCode` si le fournisseur a échoué. Lève `AppError` pour les refus préalables (voir la
    docstring du module), sans aucune écriture dans ces cas.
    """
    version = await catalogue_publication.lire_version(db, module_id, module_version_id)
    if version.publicationState != "published":
        raise AppError(
            code="MODULE_VERSION_NOT_PUBLISHED",
            message="Seule une version publiée peut être installée.",
            status_code=422,
        )
    await _verifier_compatibilite(db, module_id, version.id)
    await _verifier_prerequis(db, organization_id, version.prerequisites)

    if await _installation_active(db, organization_id, module_id) is not None:
        raise AppError(
            code="MODULE_ALREADY_INSTALLED",
            message="Ce module est déjà installé pour l'organisation.",
            status_code=409,
        )
    if state_version != 0:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue 0 pour une nouvelle installation, reçue {state_version}.",
            status_code=409,
        )

    installation = ModuleInstallation(
        organizationId=organization_id,
        moduleId=module_id,
        moduleVersionId=version.id,
        state="not_installed",
        stateVersion=0,
        operationId=uuid.uuid4(),
    )
    db.add(installation)
    await db.flush()

    transition = {"acteur_id": acteur_id, "cle": cle_idempotence, "organisation_id": organization_id, "module_id": module_id}
    await _transitionner_installation(db, installation, vers_etat="preflight", **transition)
    await _transitionner_installation(db, installation, vers_etat="provisioning", **transition)

    executeur = fournisseur if fournisseur is not None else FournisseurSimule()
    try:
        await executeur.provisionner(installation.id, version.id)
    except Exception as exc:
        # Seul le type de l'exception est journalisé : son message peut contenir des secrets.
        logger.warning("Provisionnement en échec pour l'installation %s : %s", installation.id, type(exc).__name__)
        installation.lastErrorCode = CODE_PROVISIONNEMENT_ECHEC
        await _transitionner_installation(db, installation, vers_etat="failed", **transition)
        return installation

    await _transitionner_installation(db, installation, vers_etat="installed", **transition)
    return installation


async def lire_installation_par_operation(
    db: AsyncSession, organization_id: uuid.UUID, module_id: uuid.UUID, operation_id: uuid.UUID
) -> ModuleInstallation:
    """Renvoie l'installation de l'opération `operation_id` pour ce couple, sinon 404.

    Le filtre sur l'organisation et le module fait qu'une opération d'un autre tenant est introuvable
    (CA-5) : même réponse qu'une opération inexistante."""
    installation = (
        await db.execute(
            select(ModuleInstallation).where(
                ModuleInstallation.operationId == operation_id,
                ModuleInstallation.organizationId == organization_id,
                ModuleInstallation.moduleId == module_id,
            )
        )
    ).scalar_one_or_none()
    if installation is None:
        raise AppError(code="MODULE_INSTALLATION_NOT_FOUND", message="Opération introuvable.", status_code=404)
    return installation
