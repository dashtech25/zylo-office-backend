"""Filet de caractérisation de la découpe zylo_liquid (T-034, lot 1).

Intention : figer la surface publique des fonctions de stations, de cuves et des helpers
partagés, telle qu'elle est exposée par la façade `app.modules.zylo_liquid.service`. Un
déplacement de code vers `stations/`, `tanks/` ou `common.py` ne doit ni renommer une
fonction, ni changer sa signature, ni la rendre synchrone ou asynchrone. Le comportement
est couvert par les tests HTTP existants (`test_zylo_liquid_stations.py`,
`test_zylo_liquid_station_admin_center.py`, `test_zylo_liquid_fuel_products.py`, ...).

Ce fichier ne couvre pas la logique métier : il ne remplace pas ces tests.
"""
import inspect

import pytest

from app.modules.zylo_liquid import service

# Signatures relevées avant le déplacement (lot 1 de T-034).
SIGNATURES_LOT_1 = [
    ("create_fuel_product", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateFuelProductRequest) -> app.modules.zylo_liquid.models.FuelProduct'),
    ("get_fuel_product", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, fuel_product_id: uuid.UUID) -> app.modules.zylo_liquid.models.FuelProduct'),
    ("create_station_fuel_product", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateStationFuelProductRequest) -> app.modules.zylo_liquid.models.StationFuelProduct'),
    ("list_station_fuel_products", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, pagination: app.shared.pagination.PaginationParams, station_id: uuid.UUID | None, fuel_product_id: uuid.UUID | None) -> app.shared.schemas.Page'),
    ("update_station_fuel_product", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, association_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdateStationFuelProductRequest) -> app.modules.zylo_liquid.models.StationFuelProduct'),
    ("create_station_service", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateStationServiceRequest) -> app.modules.zylo_liquid.schemas.StationServiceResponse'),
    ("update_station_service", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, service_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdateStationServiceRequest) -> app.modules.zylo_liquid.schemas.StationServiceResponse'),
    ("list_station_services", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> list[app.modules.zylo_liquid.schemas.StationServiceResponse]'),
    ("get_pricing_policy", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, fuel_product_id: uuid.UUID) -> app.modules.zylo_liquid.schemas.PricingPolicyResponse | None'),
    ("update_pricing_policy", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, fuel_product_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdatePricingPolicyRequest) -> app.modules.zylo_liquid.schemas.PricingPolicyResponse'),
    ("_assert_city_exists", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, city_id: uuid.UUID) -> None'),
    ("_assert_currency_exists", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, currency_id: uuid.UUID) -> None'),
    ("create_station", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateStationRequest) -> app.modules.zylo_liquid.models.Station'),
    ("get_station", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID) -> app.modules.zylo_liquid.models.Station'),
    ("update_station", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdateStationRequest) -> app.modules.zylo_liquid.models.Station'),
    ("deactivate_station", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> app.modules.zylo_liquid.models.Station'),
    ("reactivate_station", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station_id: uuid.UUID) -> app.modules.zylo_liquid.models.Station'),
    ("list_stations", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: app.shared.pagination.PaginationParams, city_id: uuid.UUID | None, status: str | None) -> app.shared.schemas.Page'),
    ("create_tank", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateTankRequest) -> app.modules.zylo_liquid.models.Tank'),
    ("_assert_tank_station_in_organization", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, tank: app.modules.zylo_liquid.models.Tank) -> None'),
    ("get_tank", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> app.modules.zylo_liquid.models.Tank'),
    ("update_tank", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, tank_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdateTankRequest) -> app.modules.zylo_liquid.models.Tank'),
    ("list_tanks", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: app.shared.pagination.PaginationParams, station_id: uuid.UUID | None, fuel_product_id: uuid.UUID | None, active: bool | None) -> app.shared.schemas.Page'),
    ("create_pump", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreatePumpRequest) -> app.modules.zylo_liquid.models.Pump'),
    ("_assert_pump_station_in_organization", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, pump: app.modules.zylo_liquid.models.Pump) -> None'),
    ("get_pump", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, pump_id: uuid.UUID) -> app.modules.zylo_liquid.models.Pump'),
    ("update_pump", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pump_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.UpdatePumpRequest) -> app.modules.zylo_liquid.models.Pump'),
    ("list_pumps", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, pagination: app.shared.pagination.PaginationParams, station_id: uuid.UUID | None, active: bool | None) -> app.shared.schemas.Page'),
    ("create_tank_sensor_mapping", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.CreateTankSensorMappingRequest) -> app.modules.zylo_liquid.models.TankSensorMapping'),
    ("get_tank_sensor_mapping", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, mapping_id: uuid.UUID) -> app.modules.zylo_liquid.models.TankSensorMapping'),
    ("close_tank_sensor_mapping", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, mapping_id: uuid.UUID) -> app.modules.zylo_liquid.models.TankSensorMapping'),
    ("list_tank_sensor_mappings", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, pagination: app.shared.pagination.PaginationParams, tank_id: uuid.UUID | None) -> app.shared.schemas.Page'),
    ("replace_tank_calibration_points", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID, data: app.modules.zylo_liquid.schemas.ReplaceTankCalibrationPointsRequest) -> list[app.modules.zylo_liquid.models.TankCalibrationPoint]'),
    ("list_tank_calibration_points", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, tank_id: uuid.UUID) -> list[app.modules.zylo_liquid.models.TankCalibrationPoint]'),
    ("_check_declaration_scope", '(db: sqlalchemy.ext.asyncio.session.AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, station: app.modules.zylo_liquid.models.Station, permission_code: str) -> None'),
]


@pytest.mark.parametrize(("nom", "signature"), SIGNATURES_LOT_1)
def test_facade_expose_la_signature_d_origine(nom: str, signature: str) -> None:
    fonction = getattr(service, nom)
    assert str(inspect.signature(fonction)) == signature


@pytest.mark.parametrize(("nom", "signature"), SIGNATURES_LOT_1)
def test_facade_conserve_le_nom_de_la_fonction(nom: str, signature: str) -> None:
    assert getattr(service, nom).__name__ == nom
