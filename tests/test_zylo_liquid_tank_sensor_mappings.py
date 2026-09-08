import uuid
from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import HolykellDeviceRegistry
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_tank(client: AsyncClient, headers: dict, station_code: str, tank_number: int = 1) -> str:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": "Station Sensor", "code": station_code}, headers=headers)
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": tank_number,
            "displayName": "Cuve",
            "capacityLiters": 1000,
            "tankHeightMm": 100,
            "newFuelProductName": f"Produit {station_code}",
            "newFuelProductCode": station_code[:10],
            "heightAlarmMm": 90,
            "heightAlertMm": 80,
            "lowAlarmMm": 10,
        },
        headers=headers,
    )
    return tank_res.json()["id"]


async def test_create_tank_sensor_mapping(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-01")
    serial = f"XM1234567HAR{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")

    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["hkSensorId"] == sensor_id
    assert body["measurementType"] == "product_level"
    assert body["active"] is True
    assert body["validUntil"] is None


async def test_create_tank_sensor_mapping_unknown_serial_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-02")

    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": "INCONNU-000", "measurementType": "product_level"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "sensor_not_found_in_holykell_registry"


async def test_create_tank_sensor_mapping_resolves_correct_channel_by_measurement_type(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Un même numéro de série physique porte plusieurs capteurs logiques
    (product_level/water_level/temperature) — le bon hkSensorId doit être
    résolu selon measurementType, jamais le premier trouvé au hasard."""
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-03")
    serial = f"XM7654321HAR{uuid.uuid4().hex[:6]}"
    product_sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")
    water_sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "water_level")
    assert product_sensor_id != water_sensor_id

    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "water_level"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["hkSensorId"] == water_sensor_id


async def test_create_tank_sensor_mapping_duplicate_active_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-04")
    serial = f"XM1111111HAR{uuid.uuid4().hex[:6]}"
    await register_holykell_sensor(zylo_liquid_organization["id"], serial, "temperature")

    payload = {"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "temperature"}
    first = await client.post("/api/v1/zylo-liquid/tank-sensor-mappings", json=payload, headers=headers)
    assert first.status_code == 201

    second = await client.post("/api/v1/zylo-liquid/tank-sensor-mappings", json=payload, headers=headers)
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "tank_sensor_mapping_already_active"


async def test_close_tank_sensor_mapping_then_replace_with_new_sensor(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Remplacement de sonde (Point 2 §1.3) : la nouvelle sonde physique a un
    hkSerialNumber/hkSensorId différent de l'ancienne — reprendre exactement
    la même sonde après clôture est bloqué par la contrainte d'unicité
    (hkSensorId, measurementType, tankId) déjà présente dans le schéma
    source (table tank_sensor_mapping), vérifiée sur la base réelle
    (issue #29) : ce n'est pas un scénario que ce endpoint doit permettre."""
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-05")
    old_serial = f"XM2222222HAR{uuid.uuid4().hex[:6]}"
    await register_holykell_sensor(zylo_liquid_organization["id"], old_serial, "product_level")

    payload = {"tankId": tank_id, "hkSerialNumber": old_serial, "measurementType": "product_level"}
    create_res = await client.post("/api/v1/zylo-liquid/tank-sensor-mappings", json=payload, headers=headers)
    mapping_id = create_res.json()["id"]

    close_res = await client.post(f"/api/v1/zylo-liquid/tank-sensor-mappings/{mapping_id}/close", headers=headers)
    assert close_res.status_code == 200
    assert close_res.json()["active"] is False
    assert close_res.json()["validUntil"] is not None

    already_closed = await client.post(f"/api/v1/zylo-liquid/tank-sensor-mappings/{mapping_id}/close", headers=headers)
    assert already_closed.status_code == 409
    assert already_closed.json()["error"]["code"] == "tank_sensor_mapping_already_closed"

    new_serial = f"XM2222222HAR{uuid.uuid4().hex[:6]}"
    await register_holykell_sensor(zylo_liquid_organization["id"], new_serial, "product_level")
    replace_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": new_serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert replace_res.status_code == 201


async def test_list_tank_sensor_mappings(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-06")
    serial = f"XM3333333HAR{uuid.uuid4().hex[:6]}"
    await register_holykell_sensor(zylo_liquid_organization["id"], serial, "water_level")

    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "water_level"},
        headers=headers,
    )
    res = await client.get(f"/api/v1/zylo-liquid/tank-sensor-mappings?tankId={tank_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 1


async def test_create_tank_sensor_mapping_response_has_no_live_state(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """La réponse de création porte la vérité *déclarée* du mapping, jamais
    l'état *mesuré* du sensor (qui appartient au registre Holykell, couche
    télémétrie). `live` est donc null ici, renseigné uniquement par la
    liste."""
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-07")
    serial = f"XM4444444HAR{uuid.uuid4().hex[:6]}"
    await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")

    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["live"] is None


async def test_list_tank_sensor_mappings_exposes_live_registry_state(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """La liste enrichit chaque mapping avec le dernier état *mesuré* du
    sensor (registre Holykell : dernière valeur, dernière visibilité, statut
    remonté, unité, cycle) — la double vérité déclaré/mesuré sur une seule
    réponse. Sans registre connu, `live` reste null, jamais un état
    inventé."""
    headers = _headers(registered_user, zylo_liquid_organization)
    tank_id = await _create_tank(client, headers, "TSM-08")
    serial = f"XM5555555HAR{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(zylo_liquid_organization["id"], serial, "product_level")

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
            .values(
                lastValue=1234.5,
                lastValueAt=datetime(2026, 8, 1, 10, 0, 0),
                hkLastStatus=1,
                hkLastSeenAt=datetime(2026, 8, 1, 10, 0, 5),
                hkUnit="mm",
                hkReportCycleSec=30,
            )
        )
        await db.commit()

    await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    res = await client.get(f"/api/v1/zylo-liquid/tank-sensor-mappings?tankId={tank_id}", headers=headers)
    assert res.status_code == 200
    row = res.json()["data"][0]
    assert row["hkSensorId"] == sensor_id
    live = row["live"]
    assert live is not None
    assert live["hkSerialNumber"] == serial
    assert live["lastValue"] == 1234.5
    assert live["lastValueAt"] == "2026-08-01T10:00:00"
    assert live["hkLastStatus"] == 1
    assert live["hkLastSeenAt"] == "2026-08-01T10:00:05"
    assert live["hkUnit"] == "mm"
    assert live["hkReportCycleSec"] == 30


async def test_tank_sensor_mapping_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings/00000000-0000-0000-0000-000000000000/close", headers=headers
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_sensor_mapping_not_found"


async def test_create_tank_sensor_mapping_unknown_tank_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": "00000000-0000-0000-0000-000000000000", "hkSerialNumber": "X", "measurementType": "product_level"},
        headers=headers,
    )
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "tank_not_found"
