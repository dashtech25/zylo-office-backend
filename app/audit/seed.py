from app.audit.permissions import AUDIT_LOG_VIEW
from app.core.database import AsyncSessionLocal
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, AUDIT_LOG_VIEW, "audit", "Consulter le journal d'audit.")
        await db.commit()
