"""Déclaration en base des permissions de jobs (BE-213).

Sans ces lignes, `require_permission` refuse, y compris au propriétaire (CLAUDE.md, IAM).
Appelé par app/cli.py au démarrage des seeds. Idempotent.
"""

from app.core.database import AsyncSessionLocal
from app.jobs.permissions import PERMISSION_EXPORT_CLIENTS, PERMISSION_IMPORT_CLIENTS
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, PERMISSION_EXPORT_CLIENTS, "jobs", "Demander un job d'export de données du tenant (BE-213)."
        )
        await get_or_create_permission(
            db, PERMISSION_IMPORT_CLIENTS, "jobs", "Demander un job d'import de données dans le tenant (BE-213)."
        )
        await db.commit()
