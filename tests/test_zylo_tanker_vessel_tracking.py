"""Tracking GPS des navires (généralisation Zylo Tanker, 2026-09-16) —
mêmes scénarios que `tests/test_zylo_liquid_truck_tracking.py`, appliqués
à un navire : chaîne complète position -> arrêt -> qualification/alerte,
jamais seulement la position brute (décision corrigée du commanditaire,
voir le plan de mission).

Note (judgment call documenté dans le rapport) : les permissions de
tracking partagées (GPS_DEVICE_*, TRACKING_*) restent enregistrées avec
`Permission.moduleCode == "zylo_liquid"` (héritage de leur seed d'origine,
`app/modules/zylo_liquid/seed.py`) — `grant_module_permissions_to_owner`
ne les accorde donc au owner que si zylo_liquid est ACTIF, même si les
routes elles-mêmes sont accessibles sous /zylo-tanker dès que zylo_tanker
est actif (garde `require_module_active_any`). Ces tests activent donc les
deux modules pour l'organisation, comme le ferait en pratique une
organisation qui suit à la fois camions et navires — limite connue pour
une organisation "navire seul", non corrigée dans ce chantier (voir le
rapport)."""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.alerts.models import Alert
from app.core.database import AsyncSessionLocal


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _activate(client: AsyncClient, headers: dict, org_id: str, module_code: str) -> None:
    res = await client.post(f"/api/v1/modules/organizations/{org_id}/activate", json={"moduleCode": module_code}, headers=headers)
    assert res.status_code == 200, res.text


async def _create_vessel(client: AsyncClient, headers: dict, suffix: str) -> dict:
    res = await client.post("/api/v1/zylo-tanker/vessels", json={"name": f"Navire {suffix}", "code": f"IMO-{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _create_gps_device(client: AsyncClient, headers: dict, suffix: str, vessel_id: str | None) -> dict:
    body = {"deviceIdentifier": f"SAT-{suffix}"}
    if vessel_id is not None:
        body["vesselId"] = vessel_id
    res = await client.post("/api/v1/zylo-tanker/gps-devices", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _get_ingest_secret(client: AsyncClient, headers: dict) -> str:
    res = await client.get("/api/v1/zylo-tanker/gps-ingest-credential", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["secretToken"]


async def _ingest_stop_sequence(client: AsyncClient, ingest_headers: dict, device_identifier: str, base: datetime, lat: float, lon: float) -> None:
    """Même séquence que côté camion (`_ingest_stop_sequence` de
    `test_zylo_liquid_truck_tracking.py`) : approche, 21 min immobile,
    reprise — mêmes seuils par défaut (rayon 150m, stabilisation 10min)."""
    async def _ingest(minutes_offset: int, ilat: float, ilon: float):
        res = await client.post(
            "/api/v1/zylo-tanker/gps/ingest",
            json={"deviceIdentifier": device_identifier, "recordedAt": (base + timedelta(minutes=minutes_offset)).isoformat(), "latitude": ilat, "longitude": ilon},
            headers=ingest_headers,
        )
        assert res.status_code == 201, res.text

    for i in range(5):
        await _ingest(i * 2, lat - 0.01 + i * 0.002, lon)
    for i in range(21):
        await _ingest(10 + i, lat, lon)
    for i in range(5):
        await _ingest(31 + i * 2, lat + i * 0.01, lon)


async def test_vessel_stop_detected_and_appears_in_stops(client: AsyncClient, registered_user: dict, organization: dict):
    """Chaîne complète : Vessel -> GpsDevice(vesselId) -> ingestion via le
    webhook -> TruckStopEvent.vesselId créé -> visible via
    GET /vessels/{id}/stops (mêmes seuils/algorithme que côté camion,
    `detect_truck_stops`, jamais réimplémenté)."""
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await _activate(client, headers, org_id, "zylo_liquid")
    await _activate(client, headers, org_id, "zylo_tanker")

    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])
    assert device["vesselId"] == vessel["id"]
    assert device["truckId"] is None
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id}

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    # Coordonnées isolées (aucun lieu de tracking créé dans ce test) —
    # l'arrêt doit donc rester non qualifié et déclencher une alerte.
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, -7.30, 12.40)

    stops = await client.get(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert stops.status_code == 200, stops.text
    events = stops.json()
    assert len(events) == 1
    assert events[0]["vesselId"] == vessel["id"]
    assert events[0]["truckId"] is None
    assert events[0]["latitude"] == -7.30

    # Ré-ingestion : pas de doublon d'arrêt (même idempotence que côté camion).
    res = await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": (base + timedelta(minutes=50)).isoformat(), "latitude": -7.20, "longitude": 12.40},
        headers=ingest_headers,
    )
    assert res.status_code == 201, res.text
    stops_again = await client.get(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert len(stops_again.json()) == 1

    # Arrêt hors de tout lieu connu -> alerte truck_stop_unqualified avec
    # vesselId renseigné (jamais truckId) — vérifiée directement en base
    # plutôt que via GET /alerts (mounted uniquement sous /zylo-liquid
    # aujourd'hui, voir la note en tête de fichier).
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Alert).where(Alert.vesselId == uuid.UUID(vessel["id"]), Alert.type == "truck_stop_unqualified"))
        alerts = result.scalars().all()
    assert len(alerts) == 1
    assert alerts[0].truckId is None
    assert alerts[0].stationId is None
    assert alerts[0].status == "active"


async def test_vessel_stop_matched_to_known_location_no_alert(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await _activate(client, headers, org_id, "zylo_liquid")
    await _activate(client, headers, org_id, "zylo_tanker")

    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id}

    loc_lat, loc_lon = 5.30, 10.80
    created = await client.post(
        "/api/v1/zylo-tanker/tracking-locations",
        json={"name": f"Port {suffix}", "type": "port", "latitude": loc_lat, "longitude": loc_lon, "radiusMeters": 150},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    location = created.json()

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, loc_lat, loc_lon)

    stops = await client.get(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    events = stops.json()
    assert len(events) == 1
    assert events[0]["locationId"] == location["id"]
    assert events[0]["reconciliationStatus"] == "none"

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Alert).where(Alert.vesselId == uuid.UUID(vessel["id"]), Alert.type == "truck_stop_unqualified"))
        alerts = result.scalars().all()
    assert len(alerts) == 0


async def test_vessel_current_positions_and_gps_device_manage_permission(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await _activate(client, headers, org_id, "zylo_liquid")
    await _activate(client, headers, org_id, "zylo_tanker")

    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])

    secret = await _get_ingest_secret(client, headers)
    await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 16, 9, 0, 0).isoformat(), "latitude": 4.06, "longitude": 9.71},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id},
    )

    res = await client.get("/api/v1/zylo-tanker/vessels/current-positions", headers=headers)
    assert res.status_code == 200, res.text
    entry = next(e for e in res.json() if e["vesselId"] == vessel["id"])
    assert entry["latitude"] == 4.06
    assert entry["longitude"] == 9.71


async def test_zylo_liquid_truck_routes_blocked_when_module_inactive(client: AsyncClient, registered_user: dict, organization: dict):
    """Régression (plan de mission, faille corrigée en généralisant
    `app/location/router.py`) : avant cette généralisation, ce routeur
    n'avait AUCUNE garde `require_module_active` au niveau du routeur —
    ses routes camion étaient donc accessibles même si l'organisation
    n'avait jamais activé zylo_liquid. Aucun test ne le couvrait. Ce test
    n'active délibérément AUCUN module."""
    headers = _headers(registered_user, organization)

    for path in [
        "/api/v1/zylo-liquid/gps-devices",
        "/api/v1/zylo-liquid/trucks/current-positions",
        "/api/v1/zylo-liquid/tracking-locations",
        "/api/v1/zylo-liquid/tracking-settings",
    ]:
        res = await client.get(path, headers=headers)
        assert res.status_code == 403, f"{path} -> {res.status_code} {res.text}"
        assert res.json()["error"]["code"] == "module_inactive", f"{path} -> {res.json()}"

    # Même vérification côté navire, sous /zylo-tanker (jamais actif ici
    # non plus).
    for path in [
        "/api/v1/zylo-tanker/vessels/current-positions",
        "/api/v1/zylo-tanker/gps-devices",
    ]:
        res = await client.get(path, headers=headers)
        assert res.status_code == 403, f"{path} -> {res.status_code} {res.text}"
        assert res.json()["error"]["code"] == "module_inactive", f"{path} -> {res.json()}"
