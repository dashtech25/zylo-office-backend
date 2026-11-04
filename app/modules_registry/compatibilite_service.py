"""Persistance des évaluations de compatibilité et des plans de mise à jour (BE-044).

Ce service lit le catalogue (versions et leur module), appelle les fonctions pures de
`compatibilite.py`, puis écrit une ligne d'évaluation ou de plan. Il ne fait que `flush` : la
route valide la transaction, comme dans `catalogue_publication.py`.

Les contrôles de droit (`platform.module.publish`) sont faits par la route avant l'appel : aucune
ligne n'est donc créée pour un acteur sans droit (CA-4).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry import catalogue_publication
from app.modules_registry.compatibilite import (
    EntreeCatalogue,
    construire_plan_mise_a_jour,
    evaluer_compatibilite,
)
from app.modules_registry.models import Module, ModuleCompatibilityEvaluation, ModuleUpgradePlan, ModuleVersion


async def _charger_catalogue(db: AsyncSession) -> list[EntreeCatalogue]:
    """Lit toutes les versions du catalogue avec le code de leur module.

    Une version est « publiée » si son `publicationState` vaut `published` : seule une version
    publiée peut servir de dépendance (voir `compatibilite.py`)."""
    lignes = (
        await db.execute(select(ModuleVersion, Module.code).join(Module, Module.id == ModuleVersion.moduleId))
    ).all()
    return [
        EntreeCatalogue(
            code=code,
            version=version.version,
            publiee=version.publicationState == "published",
            compatibility=version.compatibility,
            prerequisites=version.prerequisites,
        )
        for version, code in lignes
    ]


async def evaluer_version(db: AsyncSession, module_id: uuid.UUID, version_id: uuid.UUID) -> ModuleCompatibilityEvaluation:
    """Évalue la compatibilité de la version `version_id` et journalise le résultat.

    Lève `MODULE_VERSION_NOT_FOUND` (404) si la version n'appartient pas au module."""
    version = await catalogue_publication.lire_version(db, module_id, version_id)
    module = await catalogue_publication.lire_module(db, module_id)
    catalogue = await _charger_catalogue(db)
    cible = EntreeCatalogue(
        code=module.code,
        version=version.version,
        publiee=version.publicationState == "published",
        compatibility=version.compatibility,
        prerequisites=version.prerequisites,
    )
    resultat = evaluer_compatibilite(cible, catalogue)
    ligne = ModuleCompatibilityEvaluation(
        moduleVersionId=version.id, result=resultat.result, reasons=resultat.reasons
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def planifier_mise_a_jour(
    db: AsyncSession, module_id: uuid.UUID, *, from_version: str, to_version: str
) -> ModuleUpgradePlan:
    """Calcule et journalise le plan `from_version` -> `to_version` du module, sans l'exécuter.

    Lève `MODULE_VERSION_NOT_FOUND` (404) si l'une des deux versions n'existe pas pour ce module."""
    module = await catalogue_publication.lire_module(db, module_id)
    source = await _version_par_numero(db, module_id, from_version)
    await _version_par_numero(db, module_id, to_version)
    plan = construire_plan_mise_a_jour(
        from_version, to_version, source_compatibility=source.compatibility
    )
    ligne = ModuleUpgradePlan(
        moduleId=module.id,
        fromVersion=from_version,
        toVersion=to_version,
        steps=plan["steps"],
        rollbackPossible=plan["rollbackPossible"],
        forwardOnly=plan["forwardOnly"],
    )
    db.add(ligne)
    await db.flush()
    return ligne


async def _version_par_numero(db: AsyncSession, module_id: uuid.UUID, numero: str) -> ModuleVersion:
    """Renvoie la version `numero` du module, ou lève `MODULE_VERSION_NOT_FOUND` (404)."""
    version = (
        await db.execute(
            select(ModuleVersion).where(ModuleVersion.moduleId == module_id, ModuleVersion.version == numero)
        )
    ).scalar_one_or_none()
    if version is None:
        raise AppError(code="MODULE_VERSION_NOT_FOUND", message=f"Version introuvable : {numero}.", status_code=404)
    return version
