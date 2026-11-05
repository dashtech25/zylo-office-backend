"""Déclaration en base des permissions de la sortie de tenant (BE-246).

Sans ces lignes, `require_permission` refuse, y compris au propriétaire (CLAUDE.md, IAM).
Appelé par app/cli.py au démarrage des seeds.
"""

from app.core.database import AsyncSessionLocal
from app.rbac.service import get_or_create_permission
from app.sortie_tenant.permissions import SORTIE_TENANT_DECIDER, SORTIE_TENANT_LIRE


async def seed_known_permissions() -> None:
    """Crée les deux permissions de sortie si elles manquent (idempotent)."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(
            db, SORTIE_TENANT_DECIDER, "donnees", "Demander la sortie d'un tenant et poser un hold (BE-246)."
        )
        await get_or_create_permission(
            db, SORTIE_TENANT_LIRE, "donnees", "Lire l'attestation de sortie d'un tenant (BE-246)."
        )
        await db.commit()
