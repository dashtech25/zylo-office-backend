import uuid
from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import HolykellDeviceRegistry
from app.shared.currency import Currency
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_currency() -> str:
    # `currency.code` est limité à 3 caractères (norme ISO 4217) et la base de
    # test est persistante entre les sessions : un code court déterministe
    # finit par entrer en collision. Code aléatoire + nouvelle tentative sur
    # violation d'unicité → tests idempotents.
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        for _ in range(10):
            code = uuid.uuid4().hex[:3].upper()
            currency = Currency(code=code, name=code, symbol=code, decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            return str(currency.id)
    raise AssertionError("impossible d'allouer un code devise unique")


async def _create_tank_with_sensor(client: AsyncClient, headers: dict, organization_id: str, station_code: str) -> tuple[str, str, str, int]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Mon", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {station_code}", "code": station_code[:10]}, headers=headers)
    fuel_product_id = fp_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "fuelProductId": fuel_product_id,
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank_id = tank_res.json()["id"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    serial = f"XM_MON_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
            .values(lastValue=1000, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
        )
        await db.commit()
    return station_id, tank_id, fuel_product_id, sensor_id


async def test_current_state_monetary_value_with_applicable_price(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, fuel_product_id, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-01")
    currency_id = await _create_currency()
    price_res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert price_res.status_code == 201, price_res.text
    currency_code = (await client.patch(f"/api/v1/currencies/{currency_id}", json={}, headers=headers)).json()["code"]

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["volumeLiters"] == 20000  # 1000mm sur calibration linéaire 0-2000/0-40000
    assert body["monetaryValue"] == 20000 * 730
    assert body["currencyCode"] == currency_code
    assert body["monetaryValueNotCalculableReason"] is None


async def test_current_state_monetary_value_without_price_is_not_calculable(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    _, tank_id, _, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-02")

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["monetaryValue"] is None  # jamais 0
    assert body["monetaryValueNotCalculableReason"] == "no_applicable_price"


async def test_current_state_monetary_value_uses_price_effective_before_now(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Un prix planifié dans le futur ne doit jamais être utilisé pour
    l'instant présent (niveau_1_...md §16)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, tank_id, fuel_product_id, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-03")
    currency_id = await _create_currency()
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 700, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 999, "currencyId": currency_id, "effectiveFrom": "2099-01-01T00:00:00"},
        headers=headers,
    )

    res = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}/current-state", headers=headers)
    body = res.json()
    assert body["monetaryValue"] == 20000 * 700  # jamais le prix futur (999)


async def test_network_summary_monetary_total_same_currency(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency()
    station_id, tank_id, fuel_product_id, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-04")
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    product = res.json()["products"][0]
    assert product["totalMonetaryValue"] == 20000 * 730
    assert product["monetaryValueNotCalculableReason"] is None


async def test_network_summary_monetary_incomplete_when_one_tank_has_no_price(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Deux cuves du même produit, une seule avec un prix -> le total
    monétaire de la ligne produit n'est jamais partiel silencieusement."""
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency()
    station_id, tank_id, fuel_product_id, _ = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-05")
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    # deuxième cuve du même produit, dans une station sans prix défini
    st2_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Mon2", "code": "MON-05B"}, headers=headers)
    station2_id = st2_res.json()["id"]
    tank2_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station2_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "fuelProductId": fuel_product_id,
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    tank2_id = tank2_res.json()["id"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank2_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    serial2 = f"XM_MON05B_{uuid.uuid4().hex[:6]}"
    sensor2_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial2, "product_level")
    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank2_id, "hkSerialNumber": serial2, "measurementType": "product_level"},
        headers=headers,
    )
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor2_id)
            .values(lastValue=1000, lastValueAt=datetime(2026, 8, 1, 10, 0, 0), hkLastStatus=1)
        )
        await db.commit()

    res = await client.get("/api/v1/zylo-liquid/network/summary", headers=headers)
    assert res.status_code == 200
    product = res.json()["products"][0]
    assert product["tankCount"] == 2
    assert product["totalMonetaryValue"] is None
    assert product["monetaryValueNotCalculableReason"] == "incomplete_pricing"


async def test_network_snapshot_includes_monetary_value(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency()
    station_id, tank_id, fuel_product_id, sensor_id = await _create_tank_with_sensor(client, headers, zylo_liquid_organization["id"], "MON-06")
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )

    from app.modules.zylo_liquid.models import TankMeasurement

    async with AsyncSessionLocal() as db:
        db.add(TankMeasurement(hkSensorId=sensor_id, hkDeviceSerial="XM_MON06", hkUnit="mm", measuredAt=datetime(2026, 6, 1, 8, 0, 0), rawValue=1000, insertedAt=datetime.utcnow(), isCorrection=False))
        await db.commit()

    res = await client.get("/api/v1/zylo-liquid/network/snapshot?at=2026-07-01T00:00:00", headers=headers)
    assert res.status_code == 200
    product = res.json()["products"][0]
    assert product["totalMonetaryValue"] == 20000 * 730
