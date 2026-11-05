"""Mise à jour d'une installation de version rN vers rN+1 (BE-051).

Ce service fait passer l'installation technique d'une organisation (BE-047) de sa version installée
à une version cible publiée du même module. Séquence nominale :

    installed (version source) -> upgrading (version source, cible en cours) -> installed (version cible)

Ordre des vérifications préalables. Elles sont faites avant toute écriture d'installation, donc un
refus ne laisse ni transition ni changement de version (seule une évaluation de compatibilité,
journal append-only, peut être ajoutée) :

1. aucune installation non `removed` pour `(organisation, module)` -> `MODULE_INSTALLATION_NOT_FOUND`
   (404) ; un acteur d'une autre organisation tombe ici, comme pour les autres routes (CA-5) ;
2. `stateVersion` fourni différent de la version d'état courante -> `MODULE_STATE_VERSION_CONFLICT`
   (409) ;
3. version cible absente du module -> `MODULE_VERSION_NOT_FOUND` (404) ;
4. version cible non `published` -> `MODULE_VERSION_NOT_PUBLISHED` (422) ;
5. cible identique à la version installée -> `MODULE_UPGRADE_NOT_ALLOWED` (409) ;
6. compatibilité de la cible (BE-044) différente de `compatible` -> `MODULE_UPGRADE_NOT_ALLOWED`
   (409). Une évaluation `unknown` est refusée aussi, comme à l'installation (fail closed) ;
7. plan BE-044 `source -> cible` absent -> `MODULE_UPGRADE_NOT_ALLOWED` (409) ; le plan le plus
   récent est retenu ;
8. plan `forwardOnly` sans `confirmation_forward_only` explicite -> `MODULE_UPGRADE_FORWARD_ONLY`
   (409). Un plan dont le retour arrière est prouvé ne demande pas cette confirmation.

Exécution : la transition `installed -> upgrading` est journalisée, puis la migration est confiée au
fournisseur (protocole `FournisseurMigration`). Deux issues :

- succès : `moduleVersionId` prend la cible, `upgradeState = completed`, `upgradeTargetVersionId`
  est remis à nul, transition `upgrading -> installed` ;
- échec (toute exception du fournisseur) : la version source reste active (`moduleVersionId`
  inchangé), `upgradeState = failed`, `lastErrorCode = MODULE_UPGRADE_FAILED`, la cible est gardée
  dans `upgradeTargetVersionId` pour l'exploitation, transition `upgrading -> installed`. Aucun retour
  arrière automatique n'est tenté : seul un plan prouvé peut en décrire un (CA-3). L'exception n'est
  pas propagée, pour que la ligne `failed` soit journalisée et renvoyée à l'appelant.

Les autres états (`active`, `inactive`, `suspended`) ne peuvent pas être mis à jour par ce service :
la matrice `tenant_module` ne contient pas de transition `active -> upgrading` ; le refus vient alors
de `transitionner` (`MODULE_TRANSITION_NOT_ALLOWED`, 409). Le passage par l'état d'activation est
prévu avec la réconciliation (BE-052).

Les fonctions ne font que `flush` : la transaction est validée par l'appelant (la route, via
`run_idempotent`), comme dans `installation.py`.
"""

import logging
import uuid
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry import catalogue_publication, compatibilite_service
from app.modules_registry.installation import _installation_active, _transitionner_installation
from app.modules_registry.models import ModuleInstallation, ModuleUpgradePlan

logger = logging.getLogger("app.modules_registry.mise_a_jour")

ORIGINE_MISE_A_JOUR = "client"
CODE_MIGRATION_ECHEC = "MODULE_UPGRADE_FAILED"
ETAT_MISE_A_JOUR_EN_COURS = "running"
ETAT_MISE_A_JOUR_ECHOUEE = "failed"
ETAT_MISE_A_JOUR_TERMINEE = "completed"


class FournisseurMigration(Protocol):
    """Contrat d'exécution de la migration d'une version à l'autre.

    `migrer` lève une exception si la migration échoue ; l'appelant la traduit en `failed`. Le
    fournisseur reçoit l'installation et les deux versions, jamais de secret."""

    async def migrer(self, installation_id: uuid.UUID, source_id: uuid.UUID, cible_id: uuid.UUID) -> None: ...


class FournisseurMigrationSimule:
    """Fournisseur par défaut : réussit sans effet externe (aucun adaptateur réel n'existe encore)."""

    async def migrer(self, installation_id: uuid.UUID, source_id: uuid.UUID, cible_id: uuid.UUID) -> None:
        return None


async def _plan_le_plus_recent(
    db: AsyncSession, module_id: uuid.UUID, de_version: str, vers_version: str
) -> ModuleUpgradePlan | None:
    """Renvoie le plan BE-044 le plus récent `de_version -> vers_version` du module, ou None."""
    return (
        await db.execute(
            select(ModuleUpgradePlan)
            .where(
                ModuleUpgradePlan.moduleId == module_id,
                ModuleUpgradePlan.fromVersion == de_version,
                ModuleUpgradePlan.toVersion == vers_version,
            )
            .order_by(ModuleUpgradePlan.createdAt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def executer_mise_a_jour(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    module_id: uuid.UUID,
    target_module_version_id: uuid.UUID,
    state_version: int,
    cle_idempotence: str,
    confirmation_forward_only: bool = False,
    fournisseur_migration: FournisseurMigration | None = None,
) -> ModuleInstallation:
    """Met à jour l'installation de `organization_id` vers `target_module_version_id`.

    Paramètres :
    - `state_version` : version d'état que l'appelant a lue sur l'installation ; elle doit être
      égale à la version courante (sinon `MODULE_STATE_VERSION_CONFLICT`) ;
    - `cle_idempotence` : clé de la commande, dérivée pour chaque transition journalisée ;
    - `confirmation_forward_only` : confirmation explicite requise pour un plan sans retour arrière ;
    - `fournisseur_migration` : exécution de la migration ; `FournisseurMigrationSimule` par défaut.

    Renvoie la ligne d'installation dans son état final : `installed`, avec la version cible si la
    migration a réussi, ou avec la version source et `upgradeState = failed` sinon. Lève `AppError`
    pour les refus préalables (voir la docstring du module), sans changer la version installée.
    """
    installation = await _installation_active(db, organization_id, module_id)
    if installation is None:
        raise AppError(
            code="MODULE_INSTALLATION_NOT_FOUND",
            message="Aucune installation de ce module pour l'organisation.",
            status_code=404,
        )
    if state_version != installation.stateVersion:
        raise AppError(
            code="MODULE_STATE_VERSION_CONFLICT",
            message=f"Version d'état attendue {state_version}, courante {installation.stateVersion}.",
            status_code=409,
        )

    cible = await catalogue_publication.lire_version(db, module_id, target_module_version_id)
    if cible.publicationState != "published":
        raise AppError(
            code="MODULE_VERSION_NOT_PUBLISHED",
            message="Seule une version publiée peut être installée par mise à jour.",
            status_code=422,
        )
    if cible.id == installation.moduleVersionId:
        raise AppError(
            code="MODULE_UPGRADE_NOT_ALLOWED",
            message="La version cible est déjà la version installée.",
            status_code=409,
        )

    evaluation = await compatibilite_service.evaluer_version(db, module_id, cible.id)
    if evaluation.result != "compatible":
        raise AppError(
            code="MODULE_UPGRADE_NOT_ALLOWED",
            message=f"Mise à jour refusée : version cible {evaluation.result}.",
            status_code=409,
        )

    source = await catalogue_publication.lire_version(db, module_id, installation.moduleVersionId)
    plan = await _plan_le_plus_recent(db, module_id, source.version, cible.version)
    if plan is None:
        raise AppError(
            code="MODULE_UPGRADE_NOT_ALLOWED",
            message="Aucun plan de mise à jour calculé pour ce couple de versions.",
            status_code=409,
        )
    if plan.forwardOnly and not confirmation_forward_only:
        raise AppError(
            code="MODULE_UPGRADE_FORWARD_ONLY",
            message="Plan sans retour arrière : confirmation explicite requise.",
            status_code=409,
        )

    transition = {
        "acteur_id": acteur_id,
        "cle": cle_idempotence,
        "organisation_id": organization_id,
        "module_id": module_id,
    }
    installation.upgradeTargetVersionId = cible.id
    installation.upgradeState = ETAT_MISE_A_JOUR_EN_COURS
    installation.lastErrorCode = None
    await _transitionner_installation(db, installation, vers_etat="upgrading", **transition)

    executeur = fournisseur_migration if fournisseur_migration is not None else FournisseurMigrationSimule()
    try:
        await executeur.migrer(installation.id, source.id, cible.id)
    except Exception as exc:
        # Seul le type de l'exception est journalisé : son message peut contenir des secrets.
        logger.warning("Migration en échec pour l'installation %s : %s", installation.id, type(exc).__name__)
        installation.upgradeState = ETAT_MISE_A_JOUR_ECHOUEE
        installation.lastErrorCode = CODE_MIGRATION_ECHEC
        await _transitionner_installation(db, installation, vers_etat="installed", **transition)
        return installation

    installation.moduleVersionId = cible.id
    installation.upgradeState = ETAT_MISE_A_JOUR_TERMINEE
    installation.upgradeTargetVersionId = None
    await _transitionner_installation(db, installation, vers_etat="installed", **transition)
    return installation
