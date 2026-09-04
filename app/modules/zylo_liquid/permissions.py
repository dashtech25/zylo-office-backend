"""Permissions déclarées par le module zylo_liquid — un fichier dédié par
domaine, jamais une déclaration centralisée (convention actée en Phase 5-6,
reprise de app/identity/permissions.py)."""

FUEL_PRODUCT_READ = "zyloLiquid.fuelProduct.read"
FUEL_PRODUCT_MANAGE = "zyloLiquid.fuelProduct.manage"

STATION_READ = "zyloLiquid.station.read"
STATION_MANAGE = "zyloLiquid.station.manage"

TANK_READ = "zyloLiquid.tank.read"
TANK_MANAGE = "zyloLiquid.tank.manage"

TANK_SENSOR_MAPPING_READ = "zyloLiquid.tankSensorMapping.read"
TANK_SENSOR_MAPPING_MANAGE = "zyloLiquid.tankSensorMapping.manage"

TANK_CALIBRATION_READ = "zyloLiquid.tankCalibration.read"
TANK_CALIBRATION_MANAGE = "zyloLiquid.tankCalibration.manage"

HOLYKELL_ACCOUNT_READ = "zyloLiquid.holykellAccount.read"

DELIVERY_READ = "zyloLiquid.delivery.read"

LEAK_EVENT_READ = "zyloLiquid.leakEvent.read"

ALERT_READ = "zyloLiquid.alert.read"
ALERT_MANAGE = "zyloLiquid.alert.manage"

PRICE_HISTORY_READ = "zyloLiquid.priceHistory.read"
# La correction (PATCH) exige la même permission que la création (POST) —
# qui peut corriger un prix historique déjà écoulé n'est pas tranché
# (niveau_1_base_de_donnees_et_monetisation.md §27, Point 2 §7.4) ; en
# attendant, option la plus restrictive par défaut, jamais une permission
# distincte plus permissive par supposition.
PRICE_HISTORY_CREATE = "zyloLiquid.priceHistory.create"
