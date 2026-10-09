"""Backfill EXPLICITE et rejouable des rôles de module (T-018, condition 4).

Intention : rattacher les rôles PAR DÉFAUT déjà existants (créés avant
`Role.moduleCode`) à leur module, sans jamais changer leurs permissions et sans
bascule silencieuse. Règles :
- seuls les rôles dont le code figure dans la liste explicite fournie par
  l'appelant sont rattachés ; le reste est listé dans le rapport, jamais modifié ;
- un rôle dont une permission appartient à un AUTRE module (hors socle) n'est
  pas rattaché : il est listé en conflit, pour arbitrage par le client ;
- un rôle déjà rattaché (moduleCode non NULL) est ignoré : relancer ne change
  rien (idempotent) ;
- le rôle `owner` est transverse et n'est jamais touché ;
- ce module n'est appelé ni au démarrage ni par une migration : seul le script
  scripts/backfill_module_roles.py le fait, à la demande.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rbac.models import Permission, Role, RolePermission
from app.rbac.module_policy import permission_belongs_to_module


async def _permission_module_codes(db: AsyncSession, role_id: uuid.UUID) -> list[tuple[str, str]]:
    rows = await db.execute(
        select(Permission.code, Permission.moduleCode)
        .join(RolePermission, RolePermission.permissionId == Permission.id)
        .where(RolePermission.roleId == role_id)
    )
    return [(code, module_code) for code, module_code in rows.all()]


async def backfill_module_roles(
    db: AsyncSession, default_roles_by_module: dict[str, list[str]], *, dry_run: bool = False
) -> dict:
    """`default_roles_by_module` : {module_code: [codes de rôles par défaut]}.
    Retourne un rapport JSON-sérialisable. `dry_run=True` ne modifie rien."""
    module_of_code: dict[str, str] = {}
    for module_code, codes in default_roles_by_module.items():
        for code in codes:
            module_of_code[code] = module_code

    report: dict[str, list[dict]] = {"rattached": [], "conflicts": [], "customRoles": []}
    roles = (
        await db.execute(select(Role).where(Role.moduleCode.is_(None), Role.code != "owner").order_by(Role.organizationId, Role.code))
    ).scalars().all()

    for role in roles:
        base = {"organizationId": str(role.organizationId), "roleId": str(role.id), "code": role.code}
        module_code = module_of_code.get(role.code)
        if module_code is None:
            report["customRoles"].append({**base, "name": role.name})
            continue

        foreign = sorted(
            code
            for code, permission_module_code in await _permission_module_codes(db, role.id)
            if not permission_belongs_to_module(code, permission_module_code, module_code)
        )
        if foreign:
            report["conflicts"].append({**base, "moduleCode": module_code, "foreignPermissionCodes": foreign})
            continue

        role.moduleCode = module_code
        report["rattached"].append({**base, "moduleCode": module_code})

    if dry_run:
        await db.rollback()
    else:
        await db.commit()
    return report
