"""Désinstallation d'un module pour une organisation, sans purge des données (BE-050).

Ce service retire l'installation d'un module pour un tenant en passant par la machine à états
`transitions.py` (BE-041), qui journalise chaque transition et contrôle la version d'état :

    installed | inactive -> removing -> removed

Ordre des vérifications (avant toute écriture : une garde en échec ne change ni l'état ni le journal) :

1. aucune installation non `removed` pour `(organisation, module)` -> 404
   `MODULE_INSTALLATION_NOT_FOUND` ;
2. `stateVersion` fourni différent de la version courante -> 409 `MODULE_STATE_VERSION_CONFLICT` ;
3. `confirm` différent de `true` -> 409 `MODULE_UNINSTALL_GUARD_FAILED`, avec `details` = garde
   `confirmation` ;
4. état `active` -> 409 `MODULE_MUST_BE_INACTIVE` : il faut désactiver le module d'abord (BE-048) ;
5. toute autre transition hors `installed|inactive` (par exemple `failed`, `provisioning`) est refusée
   par la machine à états : 409 `MODULE_TRANSITION_NOT_ALLOWED`.

Pas de purge : la désinstallation ne supprime aucune ligne de données du module (QE-MOD-11). Seule la
ligne `module_installations` change d'état. Une fois `removed`, l'index unique partiel ne compte plus
la ligne : une nouvelle installation du même module devient possible, et les anciennes données
restent accessibles à l'organisation sans rien réinstaller.

Idempotence : la route encadre l'appel par `core/idempotency` (`run_idempotent`). Un rejeu avec la même
`Idempotency-Key` renvoie la réponse initiale sans second passage en `removing`. Chaque transition
reçoit une clé dérivée de la commande, suffixée par l'état cible.

Les fonctions ne font que `flush` : la transaction est validée par l'appelant (la route), comme dans
`disponibilite.py` et `installation.py`.
"""

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.models import ModuleInstallation
from app.modules_registry.transitions import TYPE_SUJET_INSTALLATION, transitionner

logger = logging.getLogger("app.modules_registry.desinstallation")

ORIGINE_DESINSTALLATION = "client"


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
) -> None:
    """Journalise une transition de désinstallation et recopie état et version sur la ligne."""
    ligne = await transitionner(
        db,
        type_sujet=TYPE_SUJET_INSTALLATION,
        id_sujet=installation.id,
        vers_etat=vers_etat,
        version_attendue=installation.stateVersion,
        acteur_id=acteur_id,
        origine=ORIGINE_DESINSTALLATION,
        cle_idempotence=f"{cle}:{vers_etat}",
        organisation_id=organisation_id,
        operation_id=installation.operationId,
        module_id=module_id,
    )
    installation.state = ligne.toState
    installation.stateVersion = ligne.stateVersionAfter


async def desinstaller_module(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    state_version: int,
    confirm: bool,
    cle_idempotence: str,
) -> ModuleInstallation:
    """Retire l'installation du module pour l'organisation : `installed|inactive -> removing -> removed`.

    `cle_idempotence` est la clé de la commande (en-tête `Idempotency-Key`), dérivée pour chaque
    transition journalisée. Renvoie la ligne d'installation dans l'état `removed`. Lève `AppError` pour
    les refus préalables (voir la docstring du module), sans aucune écriture dans ces cas.
    """
    installation = await _installation_courante(db, organization_id, module_id)
    if installation is None:
        raise AppError(code="MODULE_INSTALLATION_NOT_FOUND", message="Installation introuvable.", status_code=404)
    if state_version != installation.stateVersion:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue {state_version}, courante {installation.stateVersion}.",
            status_code=409,
        )
    if not confirm:
        raise AppError(
            code="MODULE_UNINSTALL_GUARD_FAILED",
            message="Désinstallation non confirmée : confirm doit valoir true.",
            status_code=409,
            details=[{"guard": "confirmation"}],
        )
    if installation.state == "active":
        raise AppError(
            code="MODULE_MUST_BE_INACTIVE",
            message="Un module actif ne se désinstalle pas : le désactiver d'abord.",
            status_code=409,
        )

    transition = {
        "acteur_id": acteur_id,
        "organisation_id": organization_id,
        "module_id": module_id,
        "cle": cle_idempotence,
    }
    installation.lastErrorCode = None
    await _transitionner(db, installation, vers_etat="removing", **transition)
    await _transitionner(db, installation, vers_etat="removed", **transition)
    return installation
