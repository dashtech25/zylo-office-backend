"""Tests du mécanisme de calcul du rapprochement (processus-double-sources-
verite, Phase 6 §3-5, Bloc 7 de 08-plan-implementation.md) : calcul
paresseux à la demande, jamais une tâche planifiée. Chaque test insère
directement une contrepartie télémétrique (aucun endpoint de création
manuelle n'existe pour DeliveryDetected/TankMeasurement/Alert — cohérent
avec l'audit déjà établi de ces tables, purement algorithmiques)."""

import uuid
from datetime import datetime

from httpx import AsyncClient

from app.alerts.models import Alert
from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import DeliveryDetected, HolykellDeviceRegistry, Tank, TankMeasurement, TankSensorMapping


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _setup_station_product_tank(client: AsyncClient, headers: dict, suffix: str) -> tuple[str, str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {suffix}", "code": f"P{suffix[:8]}"}, headers=headers)
    fuel_product_id = fp_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "tankNumber": 1, "displayName": f"Cuve {suffix}",
            "capacityLiters": 20000, "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        },
        headers=headers,
    )
    return station_id, fuel_product_id, tank_res.json()["id"]


async def test_delivery_reconciliation_matched_within_tolerance(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    async with AsyncSessionLocal() as db:
        db.add(DeliveryDetected(
            tankId=uuid.UUID(tank_id), startTime=datetime(2026, 2, 1, 8, 15), startHeightMm=500, endTime=datetime(2026, 2, 1, 8, 45),
            endHeightMm=1500, volumeLiters=5030,  # écart de 30 L, sous la tolérance par défaut max(50, 2%*5000=100) = 100
        ))
        await db.commit()

    res = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "matched"
    assert body["counterpartType"] == "DeliveryDetected"
    assert body["discrepancyValue"] == 30

    # Le pointeur de la déclaration doit référencer ce résultat.
    list_res = await client.get(f"/api/v1/zylo-liquid/delivery-declarations?stationId={station_id}", headers=headers)
    declaration_row = next(r for r in list_res.json()["data"] if r["id"] == declaration_id)
    assert declaration_row["reconciledWithId"] == body["id"]
    assert declaration_row["reconciledWithType"] == "ReconciliationRecord"


async def test_delivery_reconciliation_discrepancy_beyond_tolerance(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    async with AsyncSessionLocal() as db:
        db.add(DeliveryDetected(
            tankId=uuid.UUID(tank_id), startTime=datetime(2026, 2, 1, 8, 15), startHeightMm=500, endTime=datetime(2026, 2, 1, 8, 45),
            endHeightMm=1500, volumeLiters=4500,  # écart de 500 L, bien au-delà de la tolérance
        ))
        await db.commit()

    res = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "discrepancy"
    assert res.json()["discrepancyValue"] == 500


async def test_delivery_reconciliation_pending_when_no_counterpart(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, _tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    res = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "pending"
    assert res.json()["counterpartType"] is None


async def test_manual_gauging_reconciliation_matched(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/manual-gauging-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "declaredHeightMm": 1200, "method": "dipstick"},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    async with AsyncSessionLocal() as db:
        from app.modules.zylo_liquid.models import HolykellAccount

        holykell_account = HolykellAccount(organizationId=uuid.UUID(zylo_liquid_organization["id"]), holykellUsername="u", holykellPassword="p")
        db.add(holykell_account)
        await db.flush()
        registry = HolykellDeviceRegistry(
            holykellAccountId=holykell_account.id, hkGroupId=1, hkGroupName="G", hkDeviceId=1, hkSerialNumber=f"SN{suffix}",
            hkSensorId=int(uuid.uuid4().int % 900000) + 100000, hkSensorName="Level", syncFrom=datetime(2026, 1, 1), discoveredAt=datetime(2026, 1, 1),
        )
        db.add(registry)
        await db.flush()
        db.add(TankSensorMapping(
            tankId=uuid.UUID(tank_id), hkSensorId=registry.hkSensorId, measurementType="product_level",
            active=True, validFrom=datetime(2026, 1, 1), createdAt=datetime(2026, 1, 1),
        ))
        db.add(TankMeasurement(
            hkSensorId=registry.hkSensorId, hkDeviceSerial=registry.hkSerialNumber,
            measuredAt=datetime(2026, 2, 1, 8, 5), rawValue=1205, insertedAt=datetime(2026, 2, 1, 8, 5),
        ))
        await db.commit()

    res = await client.post(f"/api/v1/zylo-liquid/manual-gauging-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "matched"  # écart de 5mm, sous la tolérance par défaut de 10mm
    assert res.json()["counterpartType"] == "TankMeasurement"


async def test_quality_check_reconciliation_matched_when_both_agree(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/quality-check-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "waterDetected": True, "waterHeightMm": 8, "method": "water_paste"},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    async with AsyncSessionLocal() as db:
        db.add(Alert(
            stationId=uuid.UUID(station_id), tankId=uuid.UUID(tank_id), type="water", severity="high",
            triggeredAt=datetime(2026, 2, 1, 8, 10), triggeredValue=8,
        ))
        await db.commit()

    res = await client.post(f"/api/v1/zylo-liquid/quality-check-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "matched"
    assert res.json()["counterpartType"] == "Alert"


async def test_quality_check_reconciliation_discrepancy_when_declared_but_no_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    declaration_res = await client.post(
        "/api/v1/zylo-liquid/quality-check-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "waterDetected": True, "waterHeightMm": 8, "method": "water_paste"},
        headers=headers,
    )
    declaration_id = declaration_res.json()["id"]

    res = await client.post(f"/api/v1/zylo-liquid/quality-check-declarations/{declaration_id}/reconcile", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "discrepancy"


async def test_stock_reconciliation_insufficient_data_without_telemetry(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Sans mesure télémétrique du tout pour cette cuve, le rapprochement
    ventes<->stock doit se déclarer honnêtement 'insufficient_data', jamais
    inventer un écart."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)

    res = await client.post(f"/api/v1/zylo-liquid/tanks/{tank_id}/reconcile-stock?day=2026-02-01", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "insufficient_data"
    assert res.json()["subjectType"] == "TankStockDay"
