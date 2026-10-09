"""Règles pures des rôles de module (T-018).

Intention : un seul endroit décrit ce qu'un rôle de module a le droit de
contenir. Les services (rbac/service.py, rbac/module_assignment.py,
rbac/module_backfill.py) appellent ces fonctions ; elles ne décident jamais
seules d'une autorisation d'accès (c'est `user_has_permission` qui le fait).

Ce module ne dépend que des modèles et des constantes partagées : il peut être
importé depuis rbac/service.py sans créer de cycle.
"""

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.rbac.models import Permission
from app.shared.permissions import SHARED_PERMISSION_CODES

# Format du catalogue : domaine.entite.action, trois segments. Le vocabulaire
# recommandé des actions est read, create, update, delete, validate, export,
# manage. Il n'est pas imposé ici : des codes historiques (ex. `acknowledge`)
# restent valides. Seule la forme est vérifiée.
PERMISSION_CODE_PATTERN = re.compile(r"^[a-z][A-Za-z0-9]*\.[a-z][A-Za-z0-9]*\.[a-z][A-Za-z0-9]*$")


def is_valid_permission_code(code: str) -> bool:
    return PERMISSION_CODE_PATTERN.fullmatch(code) is not None


def permission_belongs_to_module(permission_code: str, permission_module_code: str, module_code: str) -> bool:
    """Une permission est utilisable dans un rôle (ou un contrôle) du module si
    elle est déclarée par ce module, ou si elle fait partie du socle partagé.
    Toute autre permission est refusée : c'est l'éviter qui garantit qu'un rôle
    CRM ne donne jamais un droit Stock."""
    return permission_module_code == module_code or permission_code in SHARED_PERMISSION_CODES


async def assert_permissions_match_module(db: AsyncSession, module_code: str | None, permission_codes: list[str]) -> None:
    """Refuse qu'un rôle de module contienne une permission d'un autre module.
    Un rôle transverse (module_code None) n'est pas restreint par cette règle.
    Les codes inconnus ne sont pas traités ici : leur 404 est levé par
    l'appelant, qui connaît le contexte de la requête."""
    if module_code is None or not permission_codes:
        return
    rows = (
        await db.execute(select(Permission.code, Permission.moduleCode).where(Permission.code.in_(permission_codes)))
    ).all()
    for code, permission_module_code in rows:
        if not permission_belongs_to_module(code, permission_module_code, module_code):
            raise AppError(
                code="permission_module_mismatch",
                message=(
                    f"La permission {code} n'appartient pas au module {module_code} : "
                    "un rôle de module ne peut contenir que les permissions de son module ou du socle partagé."
                ),
                status_code=422,
            )
