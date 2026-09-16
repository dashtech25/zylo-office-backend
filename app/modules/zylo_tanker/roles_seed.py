"""Rôles par défaut du module zylo_tanker — même patron que
`app/modules/zylo_liquid/roles_seed.py` (voir sa docstring), volontairement
réduit à un seul rôle pour l'instant : le tracking de position est la seule
fonctionnalité métier réelle de ce module à ce stade (Gestion des cuves,
qui apportera des rôles plus fins, est l'étape suivante, hors périmètre de
ce chantier)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.location.permissions import GPS_DEVICE_READ, TRACKING_LOCATION_READ
from app.modules.zylo_tanker.permissions import VESSEL_READ
from app.rbac.models import Role, RolePermission
from app.rbac.service import get_or_create_permission

DEFAULT_ROLES: list[tuple[str, str, list[str]]] = [
    (
        "zylo_tanker_operator",
        "Opérateur Zylo Tanker",
        [VESSEL_READ, GPS_DEVICE_READ, TRACKING_LOCATION_READ],
    ),
]


async def seed_default_roles(db: AsyncSession, organization_id: uuid.UUID) -> None:
    """Appelé une fois à l'activation du module `zylo_tanker` pour une
    organisation (`modules_registry/service.py::activate_module`) — mêmes
    conventions que `zylo_liquid.roles_seed.seed_default_roles` : idempotent,
    jamais appliqué au rôle `owner` (déjà créé à part, toutes permissions)."""
    for code, name, permission_codes in DEFAULT_ROLES:
        existing = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == code))
        if existing.scalar_one_or_none() is not None:
            continue

        role = Role(organizationId=organization_id, code=code, name=name)
        db.add(role)
        await db.flush()

        for perm_code in permission_codes:
            permission = await get_or_create_permission(db, perm_code, "zylo_tanker", perm_code)
            db.add(RolePermission(roleId=role.id, permissionId=permission.id))
