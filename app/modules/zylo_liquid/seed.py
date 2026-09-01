from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.permissions import (
    ALERT_MANAGE,
    ALERT_READ,
    DELIVERY_READ,
    LEAK_EVENT_READ,
    FUEL_PRODUCT_MANAGE,
    FUEL_PRODUCT_READ,
    STATION_MANAGE,
    STATION_READ,
    TANK_MANAGE,
    TANK_READ,
    HOLYKELL_ACCOUNT_READ,
    TANK_CALIBRATION_MANAGE,
    TANK_CALIBRATION_READ,
    TANK_SENSOR_MAPPING_MANAGE,
    TANK_SENSOR_MAPPING_READ,
)
from app.rbac.service import get_or_create_permission

# Toute nouvelle permission zylo_liquid doit être ajoutée ici pour être
# accordable — sans quoi `require_permission()` ne trouvera jamais la ligne
# `Permission` correspondante et refusera systématiquement l'accès, y compris
# au owner (Point 3 §14, convention <module>.<ressource>.<action>).
KNOWN_PERMISSIONS = [
    (FUEL_PRODUCT_READ, "Consulter le référentiel des produits carburant."),
    (FUEL_PRODUCT_MANAGE, "Créer/modifier le référentiel des produits carburant."),
    (STATION_READ, "Consulter les stations de l'organisation."),
    (STATION_MANAGE, "Créer/modifier/activer/désactiver les stations de l'organisation."),
    (TANK_READ, "Consulter les cuves des stations de l'organisation."),
    (TANK_MANAGE, "Créer/modifier les cuves des stations de l'organisation."),
    (TANK_SENSOR_MAPPING_READ, "Consulter les associations capteur-cuve."),
    (TANK_SENSOR_MAPPING_MANAGE, "Créer/clore les associations capteur-cuve."),
    (TANK_CALIBRATION_READ, "Consulter la table de calibration d'une cuve."),
    (TANK_CALIBRATION_MANAGE, "Charger (remplacer) la table de calibration d'une cuve."),
    (HOLYKELL_ACCOUNT_READ, "Consulter l'état de synchronisation d'un compte Holykell."),
    (DELIVERY_READ, "Consulter les livraisons détectées."),
    (LEAK_EVENT_READ, "Consulter les événements de fuite détectés."),
    (ALERT_READ, "Consulter les alertes."),
    (ALERT_MANAGE, "Résoudre une alerte."),
]


async def seed_known_permissions() -> None:
    async with AsyncSessionLocal() as db:
        for code, description in KNOWN_PERMISSIONS:
            await get_or_create_permission(db, code, "zylo_liquid", description)
        await db.commit()
