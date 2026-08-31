from app.core.database import AsyncSessionLocal
from app.modules_registry.service import get_or_create_module


async def seed_known_modules() -> None:
    """Enregistre les modules connus au démarrage — zylo_liquid en priorité
    (refonte.md §5). Un module listé ici n'est pas activé automatiquement pour
    autant : l'activation reste une décision par organisation (Phase 7)."""
    async with AsyncSessionLocal() as db:
        await get_or_create_module(db, "zylo_liquid", "Zylo Liquid", "Gestion de station-service (cuves, sondes, HK301).")
        await db.commit()
