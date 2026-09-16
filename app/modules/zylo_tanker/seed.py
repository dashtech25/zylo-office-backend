from app.core.database import AsyncSessionLocal
from app.modules.zylo_tanker.permissions import VESSEL_MANAGE, VESSEL_READ
from app.rbac.service import get_or_create_permission

# Toute nouvelle permission zylo_tanker doit être ajoutée ici pour être
# accordable — même convention que zylo_liquid/seed.py (voir sa docstring) :
# sans ce registre, `require_permission()` ne trouve jamais la ligne
# `Permission` correspondante et refuse systématiquement l'accès, y compris
# au owner.
KNOWN_PERMISSIONS = [
    (VESSEL_READ, "Consulter le référentiel des navires."),
    (VESSEL_MANAGE, "Créer/modifier le référentiel des navires."),
]


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        for code, description in KNOWN_PERMISSIONS:
            await get_or_create_permission(db, code, "zylo_tanker", description)
        await db.commit()
