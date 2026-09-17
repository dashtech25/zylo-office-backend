"""Destination de navire + ETA/statut (2026-09-17) — même patron que
`tests/test_zylo_tanker_vessel_tracking.py` (fixtures/helpers `_headers`/
`_create_vessel`/`_create_gps_device`/`_get_ingest_secret` réutilisés à
l'identique).

Couvre :
- `PUT`/`DELETE /vessels/{id}/destination` (set/clear, permission
  VESSEL_MANAGE déjà couverte par le owner de `registered_user`).
- Le calcul d'ETA dans `GET /vessels/current-positions` : cas avec
  destination + vitesse connues, cas sans destination (etaMinutes/etaAt
  restent null), cas vitesse nulle/None (idem, jamais une valeur
  inventée)."""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient


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


async def _setup_org(client: AsyncClient, registered_user: dict, organization: dict) -> tuple[dict, str]:
    headers = _headers(registered_user, organization)
    org_id = organization["id"]
    await _activate(client, headers, org_id, "zylo_liquid")
    await _activate(client, headers, org_id, "zylo_tanker")
    return headers, org_id


async def test_set_and_clear_vessel_destination(client: AsyncClient, registered_user: dict, organization: dict):
    headers, org_id = await _setup_org(client, registered_user, organization)
    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)

    # Aucune destination fixée initialement.
    get_res = await client.get(f"/api/v1/zylo-tanker/vessels/{vessel['id']}", headers=headers)
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["destinationLatitude"] is None
    assert get_res.json()["destinationSetAt"] is None

    set_res = await client.put(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/destination",
        json={"latitude": 4.05, "longitude": 9.70, "label": "Port de Douala"},
        headers=headers,
    )
    assert set_res.status_code == 200, set_res.text
    body = set_res.json()
    assert body["destinationLatitude"] == 4.05
    assert body["destinationLongitude"] == 9.70
    assert body["destinationLabel"] == "Port de Douala"
    assert body["destinationSetAt"] is not None

    clear_res = await client.delete(f"/api/v1/zylo-tanker/vessels/{vessel['id']}/destination", headers=headers)
    assert clear_res.status_code == 200, clear_res.text
    cleared = clear_res.json()
    assert cleared["destinationLatitude"] is None
    assert cleared["destinationLongitude"] is None
    assert cleared["destinationLabel"] is None
    assert cleared["destinationSetAt"] is None


async def test_set_vessel_destination_requires_vessel_manage_permission(client: AsyncClient, registered_user: dict, organization: dict):
    """Destination sur un navire inexistant -> 404, même patron que
    `get_vessel`/`AppError(vessel_not_found)`."""
    headers, org_id = await _setup_org(client, registered_user, organization)
    res = await client.put(
        f"/api/v1/zylo-tanker/vessels/{uuid.uuid4()}/destination",
        json={"latitude": 1.0, "longitude": 2.0},
        headers=headers,
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "vessel_not_found"


async def test_eta_computed_with_known_destination_and_speed(client: AsyncClient, registered_user: dict, organization: dict):
    """Navire avec destination fixée + dernière position portant une
    vitesse connue -> etaMinutes/etaAt calculés (jamais None)."""
    headers, org_id = await _setup_org(client, registered_user, organization)
    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id}

    # Destination à ~111km au nord de la position émise (1 degré de
    # latitude ~ 111.19km à l'équateur) — vitesse 20 km/h -> ETA attendue
    # proche de (111.19/20)*60 ~ 333.6 minutes.
    dest_lat, dest_lon = 1.0, 9.70
    dest_res = await client.put(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/destination",
        json={"latitude": dest_lat, "longitude": dest_lon, "label": "Destination test"},
        headers=headers,
    )
    assert dest_res.status_code == 200, dest_res.text

    recorded_at = datetime(2026, 9, 17, 8, 0, 0)
    ingest_res = await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={
            "deviceIdentifier": device["deviceIdentifier"], "recordedAt": recorded_at.isoformat(),
            "latitude": 0.0, "longitude": 9.70, "speedKmh": 20.0, "headingDeg": 0.0,
        },
        headers=ingest_headers,
    )
    assert ingest_res.status_code == 201, ingest_res.text

    res = await client.get("/api/v1/zylo-tanker/vessels/current-positions", headers=headers)
    assert res.status_code == 200, res.text
    entry = next(e for e in res.json() if e["vesselId"] == vessel["id"])
    assert entry["speedKmh"] == 20.0
    assert entry["headingDeg"] == 0.0
    assert entry["destinationLatitude"] == dest_lat
    assert entry["destinationLongitude"] == dest_lon
    assert entry["destinationLabel"] == "Destination test"
    assert entry["etaMinutes"] is not None
    assert 300.0 < entry["etaMinutes"] < 370.0
    assert entry["etaAt"] is not None
    assert entry["status"] == "underway"


async def test_eta_null_when_no_destination(client: AsyncClient, registered_user: dict, organization: dict):
    """Aucune destination fixée -> etaMinutes/etaAt restent null même avec
    position + vitesse connues (jamais une valeur inventée)."""
    headers, org_id = await _setup_org(client, registered_user, organization)
    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id}

    ingest_res = await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={
            "deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 17, 8, 0, 0).isoformat(),
            "latitude": 0.0, "longitude": 9.70, "speedKmh": 20.0,
        },
        headers=ingest_headers,
    )
    assert ingest_res.status_code == 201, ingest_res.text

    res = await client.get("/api/v1/zylo-tanker/vessels/current-positions", headers=headers)
    assert res.status_code == 200, res.text
    entry = next(e for e in res.json() if e["vesselId"] == vessel["id"])
    assert entry["destinationLatitude"] is None
    assert entry["etaMinutes"] is None
    assert entry["etaAt"] is None


async def test_eta_null_when_speed_is_zero_or_missing(client: AsyncClient, registered_user: dict, organization: dict):
    """Destination connue mais vitesse nulle (navire immobile) ou absente
    (boîtier ne la fournissant pas) -> etaMinutes/etaAt restent null,
    jamais un 0 déguisé en durée réelle."""
    headers, org_id = await _setup_org(client, registered_user, organization)
    suffix = uuid.uuid4().hex[:8]
    vessel = await _create_vessel(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, vessel["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": org_id}

    dest_res = await client.put(
        f"/api/v1/zylo-tanker/vessels/{vessel['id']}/destination",
        json={"latitude": 1.0, "longitude": 9.70},
        headers=headers,
    )
    assert dest_res.status_code == 200, dest_res.text

    # Vitesse nulle explicite.
    ingest_zero = await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={
            "deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 17, 8, 0, 0).isoformat(),
            "latitude": 0.0, "longitude": 9.70, "speedKmh": 0.0,
        },
        headers=ingest_headers,
    )
    assert ingest_zero.status_code == 201, ingest_zero.text

    res_zero = await client.get("/api/v1/zylo-tanker/vessels/current-positions", headers=headers)
    entry_zero = next(e for e in res_zero.json() if e["vesselId"] == vessel["id"])
    assert entry_zero["speedKmh"] == 0.0
    assert entry_zero["etaMinutes"] is None
    assert entry_zero["etaAt"] is None

    # Vitesse absente (jamais fournie par ce ping).
    suffix2 = uuid.uuid4().hex[:8]
    vessel2 = await _create_vessel(client, headers, suffix2)
    device2 = await _create_gps_device(client, headers, suffix2, vessel2["id"])
    await client.put(
        f"/api/v1/zylo-tanker/vessels/{vessel2['id']}/destination",
        json={"latitude": 1.0, "longitude": 9.70},
        headers=headers,
    )
    ingest_missing = await client.post(
        "/api/v1/zylo-tanker/gps/ingest",
        json={
            "deviceIdentifier": device2["deviceIdentifier"], "recordedAt": datetime(2026, 9, 17, 8, 0, 0).isoformat(),
            "latitude": 0.0, "longitude": 9.70,
        },
        headers=ingest_headers,
    )
    assert ingest_missing.status_code == 201, ingest_missing.text

    res_missing = await client.get("/api/v1/zylo-tanker/vessels/current-positions", headers=headers)
    entry_missing = next(e for e in res_missing.json() if e["vesselId"] == vessel2["id"])
    assert entry_missing["speedKmh"] is None
    assert entry_missing["etaMinutes"] is None
    assert entry_missing["etaAt"] is None
