from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.permissions import FUEL_PRODUCT_MANAGE, FUEL_PRODUCT_READ
from app.rbac.service import get_or_create_permission

# Toute nouvelle permission zylo_liquid doit être ajoutée ici pour être
# accordable — sans quoi `require_permission()` ne trouvera jamais la ligne
# `Permission` correspondante et refusera systématiquement l'accès, y compris
# au owner (Point 3 §14, convention <module>.<ressource>.<action>).
KNOWN_PERMISSIONS = [
    (FUEL_PRODUCT_READ, "Consulter le référentiel des produits carburant."),
    (FUEL_PRODUCT_MANAGE, "Créer/modifier le référentiel des produits carburant."),
]


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        for code, description in KNOWN_PERMISSIONS:
            await get_or_create_permission(db, code, "zylo_liquid", description)
        await db.commit()
