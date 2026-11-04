"""Permissions déclarées par version de module (BE-055).

Un module déclare les permissions qu'il définit dans une `module_version`. Ce service :
- enregistre ces déclarations (`declarer_permissions`), avec format et unicité contrôlés ;
- indique la version installée d'un module (`version_installee`) : la dernière version `published` ;
- liste les permissions de cette version (`lister_permissions_installees`) pour la route
  `GET /organizations/{orgId}/modules/{moduleId}/permissions` ;
- refuse les codes non déclarés par la version installée (`exiger_permissions_declarees`, CA-2).

Décisions (définition BE-055, recommandations appliquées) :
- QE-BE055-01 : « version installée » = dernière version publiée. BE-043 (`module_installations`)
  n'existe pas encore ; quand il existera, c'est sa version `installed` qui fera foi.
- QE-BE055-02 : le format du code est `<module-slug>.<ressource>.<action>` (QE-MOD-16). Les codes
  déjà utilisés par les modules (ex. `zyloLiquid.station.read`) respectent ce format.
- CA-2 est fourni ici comme garde de service. Son branchement sur les routes de grant et de rôle
  n'est pas fait : il casserait les grants existants de modules non encore déclarés (voir compte rendu).

Les fonctions ne committent pas : l'appelant gère la transaction, comme dans le reste du module.
"""

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.models import PORTEES_PERMISSION_MODULE, Module, ModulePermission, ModuleVersion

# `<module-slug>.<ressource>.<action>` : trois segments alphanumériques, séparés par des points.
FORMAT_CODE_PERMISSION = re.compile(r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*\.[A-Za-z][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DeclarationPermission:
    """Une permission déclarée par une version : code, libellé et portée."""

    code: str
    description: str | None
    scope: str


def _verifier_declaration(declaration: DeclarationPermission) -> None:
    """Lève 422 `PERMISSION_CODE_INVALID` si le code ou la portée ne respecte pas le format attendu."""
    if not FORMAT_CODE_PERMISSION.match(declaration.code):
        raise AppError(
            code="PERMISSION_CODE_INVALID",
            message=f"Code de permission mal formé : « {declaration.code} » (attendu domaine.entite.action).",
            status_code=422,
        )
    if declaration.scope not in PORTEES_PERMISSION_MODULE:
        raise AppError(
            code="PERMISSION_SCOPE_INVALID",
            message=f"Portée de permission inconnue : « {declaration.scope} ».",
            status_code=422,
        )


async def declarer_permissions(
    db: AsyncSession, module_version_id: uuid.UUID, declarations: Sequence[DeclarationPermission]
) -> list[ModulePermission]:
    """Ajoute les permissions déclarées par une version.

    Lève 422 si un code est mal formé ou si la portée est inconnue. Lève 409
    `PERMISSION_CODE_DUPLICATE` si un code est déjà déclaré par cette même version, qu'il vienne de
    la base ou de la liste fournie. Une autre version peut déclarer le même code sans conflit.
    """
    existants = set(
        (
            await db.execute(select(ModulePermission.code).where(ModulePermission.moduleVersionId == module_version_id))
        ).scalars()
    )
    lignes: list[ModulePermission] = []
    for declaration in declarations:
        _verifier_declaration(declaration)
        if declaration.code in existants:
            raise AppError(
                code="PERMISSION_CODE_DUPLICATE",
                message=f"Permission déjà déclarée par cette version : « {declaration.code} ».",
                status_code=409,
            )
        existants.add(declaration.code)
        ligne = ModulePermission(
            moduleVersionId=module_version_id,
            code=declaration.code,
            description=declaration.description,
            scope=declaration.scope,
        )
        db.add(ligne)
        lignes.append(ligne)
    await db.flush()
    return lignes


async def version_installee(db: AsyncSession, module_id: uuid.UUID) -> ModuleVersion | None:
    """Dernière version publiée du module (QE-BE055-01), ou None si aucune n'est publiée."""
    return (
        await db.execute(
            select(ModuleVersion)
            .where(ModuleVersion.moduleId == module_id, ModuleVersion.publicationState == "published")
            .order_by(ModuleVersion.publishedAt.desc(), ModuleVersion.version.desc())
            .limit(1)
        )
    ).scalars().first()


async def lister_permissions_installees(db: AsyncSession, module_id: uuid.UUID) -> list[ModulePermission]:
    """Permissions déclarées par la version installée, triées par code.

    Lève 404 `MODULE_NOT_FOUND` si le module n'existe pas au catalogue, et 404
    `MODULE_VERSION_NOT_FOUND` si aucune version n'est publiée : rien n'est alors installé.
    """
    if (await db.execute(select(Module.id).where(Module.id == module_id))).scalar_one_or_none() is None:
        raise AppError(code="MODULE_NOT_FOUND", message="Module introuvable au catalogue.", status_code=404)
    version = await version_installee(db, module_id)
    if version is None:
        raise AppError(
            code="MODULE_VERSION_NOT_FOUND", message="Aucune version installée pour ce module.", status_code=404
        )
    return list(
        (
            await db.execute(
                select(ModulePermission)
                .where(ModulePermission.moduleVersionId == version.id)
                .order_by(ModulePermission.code)
            )
        ).scalars()
    )


async def exiger_permissions_declarees(db: AsyncSession, module_code: str, codes: Sequence[str]) -> None:
    """Garde CA-2 : lève 422 `PERMISSION_NOT_DECLARED` si un code n'est pas déclaré par la version
    installée du module `module_code`. Sans version installée, tout code est refusé."""
    module_id = (await db.execute(select(Module.id).where(Module.code == module_code))).scalar_one_or_none()
    declares: set[str] = set()
    if module_id is not None:
        version = await version_installee(db, module_id)
        if version is not None:
            declares = set(
                (
                    await db.execute(
                        select(ModulePermission.code).where(ModulePermission.moduleVersionId == version.id)
                    )
                ).scalars()
            )
    for code in codes:
        if code not in declares:
            raise AppError(
                code="PERMISSION_NOT_DECLARED",
                message=f"Permission non déclarée par la version installée du module : « {code} ».",
                status_code=422,
            )
