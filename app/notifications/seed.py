"""Déclare en base les permissions du module Notifications (BE-171).

Appelé par la commande d'initialisation des permissions (`app/cli.py`), comme les autres
modules. `get_or_create_permission` est idempotent : relancer ne crée aucun doublon.
"""

from app.core.database import AsyncSessionLocal
from app.notifications.permissions import NOTIFICATIONS_READ
from app.rbac.service import get_or_create_permission


async def seed_known_permissions() -> None:
    """Crée la permission `notifications.read` si elle n'existe pas encore."""
    async with AsyncSessionLocal() as db:
        await get_or_create_permission(db, NOTIFICATIONS_READ, "notifications", "Lire les livraisons des notifications (BE-171).")
        await db.commit()
