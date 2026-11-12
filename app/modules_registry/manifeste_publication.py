"""Publication du manifeste d'un module, par code de module (BE-195, registre).

Un manifeste décrit une version livrable d'un module : identifiant, code, release, versions des
contrats API et événements, dépendances (codes d'autres modules), schéma de configuration,
permissions demandées, routes, migrations et compatibilité.

Règles de validation, dans l'ordre (chaque rejet est une `AppError` 422) :
- `MANIFEST_INCOMPLETE` : un champ requis est absent ou n'a pas le bon type (`CHAMPS_MANIFESTE`) ;
- `MANIFEST_CODE_MISMATCH` : le `code` du manifeste n'est pas celui de l'URL ;
- `MANIFEST_DEPENDENCY_UNKNOWN` : une dépendance n'existe pas au catalogue (table `module`) ;
- `MANIFEST_PERMISSION_UNKNOWN` : une permission n'existe pas au registre des permissions
  (table `permission`).

Conséquences d'une publication réussie :
- une `module_version` est créée en `draft`, avec le manifeste validé dans `manifest` ;
- aucun grant, aucun rôle et aucune permission accordés : une permission déclarée n'est jamais
  accordée par la seule déclaration (CA-4) ;
- la publication vers `published` reste à BE-042 (digest et provenance requis).

Chaque rejet de manifeste (422) écrit une entrée d'audit `refused` (CA-6). Cette entrée est
committée avant la levée de l'erreur : sans cela, le rollback de `get_db` l'effacerait avec la
transaction. Le contrôle de droit (`platform.catalog.manage`) reste à la charge du routeur, qui
l'exécute avant toute lecture du manifeste : un refus de droit n'écrit donc pas cette entrée.
"""

import uuid
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.modules_registry.models import Module, ModuleVersion
from app.rbac.models import Permission

# Champs requis du manifeste et type attendu de chacun. Un champ absent ou de mauvais type
# rend le manifeste incomplet (CA-1). Les chaînes doivent être non vides.
CHAMPS_MANIFESTE: dict[str, type] = {
    "id": str,
    "code": str,
    "release": str,
    "contractVersions": dict,
    "dependencies": list,
    "configSchema": dict,
    "permissions": list,
    "routes": list,
    "migrations": list,
    "compatibility": dict,
}

# Action d'audit écrite à chaque rejet de manifeste (CA-6).
ACTION_REJET_MANIFESTE = "modules.manifest.rejected"


def _champs_incomplets(manifeste: dict[str, Any]) -> dict[str, list[str]]:
    """Renvoie, par champ, le motif de rejet des champs requis absents ou mal typés.

    Un champ chaîne vide ou composé d'espaces compte comme absent : un identifiant vide ne
    permettrait pas d'identifier la version publiée.
    """
    erreurs: dict[str, list[str]] = {}
    for nom, type_attendu in CHAMPS_MANIFESTE.items():
        valeur = manifeste.get(nom)
        if not isinstance(valeur, type_attendu) or (type_attendu is str and not valeur.strip()):
            erreurs[nom] = ["champ requis absent ou de type incorrect"]
    return erreurs


async def _verifier_dependances(db: AsyncSession, dependances: list[Any]) -> None:
    """Lève `MANIFEST_DEPENDENCY_UNKNOWN` si une dépendance n'est pas un code du catalogue (CA-2)."""
    codes = [c for c in dependances if isinstance(c, str)]
    connus = set((await db.execute(select(Module.code).where(Module.code.in_(codes)))).scalars()) if codes else set()
    inconnus = sorted({str(c) for c in dependances if not isinstance(c, str) or c not in connus})
    if inconnus:
        raise AppError(
            code="MANIFEST_DEPENDENCY_UNKNOWN",
            message=f"Dépendance absente du catalogue : {', '.join(inconnus)}.",
            status_code=422,
        )


async def _verifier_permissions(db: AsyncSession, permissions: list[Any]) -> None:
    """Lève `MANIFEST_PERMISSION_UNKNOWN` si une permission n'est pas au registre (CA-3)."""
    codes = [c for c in permissions if isinstance(c, str)]
    connus = set((await db.execute(select(Permission.code).where(Permission.code.in_(codes)))).scalars()) if codes else set()
    inconnues = sorted({str(c) for c in permissions if not isinstance(c, str) or c not in connus})
    if inconnues:
        raise AppError(
            code="MANIFEST_PERMISSION_UNKNOWN",
            message=f"Permission inconnue du registre : {', '.join(inconnues)}.",
            status_code=422,
        )


async def _rejeter(db: AsyncSession, acteur_id: uuid.UUID, module_code: str, erreur: AppError) -> NoReturn:
    """Journalise le rejet (CA-6), le committe, puis relève l'erreur de validation."""
    await record_audit_event(
        db,
        organization_id=None,
        actor_user_id=acteur_id,
        action=ACTION_REJET_MANIFESTE,
        entity_type="module_manifest",
        entity_id=None,
        summary=f"Manifeste du module « {module_code} » rejeté : {erreur.code}.",
        changes={"moduleCode": module_code, "motif": erreur.code},
        result="refused",
        sans_organisation=True,
    )
    await db.commit()
    raise erreur


async def publier_manifeste(
    db: AsyncSession, module_code: str, manifeste: dict[str, Any], acteur_id: uuid.UUID
) -> ModuleVersion:
    """Valide le manifeste de `module_code` et crée la version correspondante en `draft`.

    Lève 404 `MODULE_NOT_FOUND` si le module n'est pas au catalogue (pas d'audit : rien à rejeter
    sur un manifeste, la cible n'existe pas). Lève 409 `MODULE_VERSION_EXISTS` si la release est
    déjà enregistrée pour ce module. Les rejets de validation (422) sont audités, voir `_rejeter`.
    Ne crée aucun grant (CA-4). Ne committe pas : le routeur valide la transaction.
    """
    module = (await db.execute(select(Module).where(Module.code == module_code))).scalar_one_or_none()
    if module is None:
        raise AppError(code="MODULE_NOT_FOUND", message="Module introuvable au catalogue.", status_code=404)

    try:
        incomplets = _champs_incomplets(manifeste)
        if incomplets:
            raise AppError(
                code="MANIFEST_INCOMPLETE",
                message="Manifeste incomplet : champ(s) requis absent(s) ou mal typé(s).",
                status_code=422,
                field_errors=incomplets,
            )
        if manifeste["code"] != module_code:
            raise AppError(
                code="MANIFEST_CODE_MISMATCH",
                message="Le code du manifeste ne correspond pas au module de l'URL.",
                status_code=422,
            )
        await _verifier_dependances(db, manifeste["dependencies"])
        await _verifier_permissions(db, manifeste["permissions"])
    except AppError as erreur:
        await _rejeter(db, acteur_id, module_code, erreur)

    release = manifeste["release"]
    existante = (
        await db.execute(
            select(ModuleVersion.id).where(ModuleVersion.moduleId == module.id, ModuleVersion.version == release)
        )
    ).scalar_one_or_none()
    if existante is not None:
        raise AppError(
            code="MODULE_VERSION_EXISTS",
            message=f"Version « {release} » déjà enregistrée pour ce module.",
            status_code=409,
        )

    ligne = ModuleVersion(
        moduleId=module.id,
        version=release,
        compatibility=manifeste["compatibility"],
        prerequisites=manifeste["dependencies"],
        manifest=manifeste,
        publicationState="draft",
    )
    db.add(ligne)
    await db.flush()
    return ligne
