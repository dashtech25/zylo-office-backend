"""Service pour les migrations (BE-198)."""

import uuid
import os
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.identity.models import Organization
from app.migrations_module import cadre


async def verifie_tenant_actif(db: AsyncSession, tenant_id: str) -> bool:
    """Vérifie que le tenant n'est pas suspended ou closed.

    Levée ValueError (422) si le tenant n'est pas actif.
    """
    org = await db.get(Organization, uuid.UUID(tenant_id))
    if not org:
        raise ValueError(f"Tenant non trouvé : {tenant_id}")

    if org.status not in ("active",):
        raise ValueError(f"Tenant inactif : {org.status}")

    return True


async def verifie_droit_maintenance(user_id: str) -> bool:
    """Vérifie que l'utilisateur a le droit platform.maintenance.run.

    Levée ValueError (403) si absent.
    """
    allowlist = os.environ.get("PLATFORM_MAINTENANCE_RUN_USER_IDS", "")
    user_ids = [uid.strip() for uid in allowlist.split(",") if uid.strip()]

    if user_id not in user_ids:
        raise ValueError(f"Droit platform.maintenance.run absent")

    return True


async def dry_run_migration(migration_id: uuid.UUID, tenant_id: str, user_id: str) -> dict:
    """Lance un dry-run d'une migration (étapes sans persistence)."""
    await verifie_droit_maintenance(user_id)

    async with AsyncSessionLocal() as db:
        await verifie_tenant_actif(db, tenant_id)

    return await cadre.dry_run(migration_id, tenant_id)


async def run_migration(migration_id: uuid.UUID, tenant_id: str, user_id: str) -> dict:
    """Lance une migration avec persistence."""
    await verifie_droit_maintenance(user_id)

    async with AsyncSessionLocal() as db:
        await verifie_tenant_actif(db, tenant_id)

    return await cadre.run(migration_id, tenant_id)


async def resume_migration(migration_id: uuid.UUID, tenant_id: str, user_id: str) -> dict:
    """Reprend une migration."""
    await verifie_droit_maintenance(user_id)

    async with AsyncSessionLocal() as db:
        await verifie_tenant_actif(db, tenant_id)

    return await cadre.resume(migration_id, tenant_id)


async def rollback_migration(migration_id: uuid.UUID, tenant_id: str, user_id: str) -> dict:
    """Annule une migration."""
    await verifie_droit_maintenance(user_id)

    async with AsyncSessionLocal() as db:
        await verifie_tenant_actif(db, tenant_id)

    return await cadre.rollback(migration_id, tenant_id)
