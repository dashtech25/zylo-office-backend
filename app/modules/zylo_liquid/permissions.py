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
