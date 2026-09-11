"""Tests du tracking GPS des camions-citernes (mission « tracking »,
étape 1 : position + arrêts sur carte). Couvre :
  - CRUD des boîtiers GPS (référentiel) ;
  - secret d'ingestion par organisation (génération, régénération) ;
  - ingestion de positions : secret invalide (401), boîtier inconnu (404),
    succès (201) ;
  - détection d'arrêt : positions stables pendant N minutes -> arrêt
    confirmé et persisté, jamais dupliqué à l'ingestion suivante ;
  - positions actuelles (carte) et permissions (403 sans droit)."""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_truck(client: AsyncClient, headers: dict, suffix: str) -> dict:
    res = await client.post("/api/v1/zylo-liquid/trucks", json={"plateNumber": f"CM-{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _create_gps_device(client: AsyncClient, headers: dict, suffix: str, truck_id: str | None) -> dict:
    body = {"deviceIdentifier": f"IMEI-{suffix}"}
    if truck_id is not None:
        body["truckId"] = truck_id
    res = await client.post("/api/v1/zylo-liquid/gps-devices", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _get_ingest_secret(client: AsyncClient, headers: dict) -> str:
    res = await client.get("/api/v1/zylo-liquid/gps-ingest-credential", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["secretToken"]


async def test_create_update_list_gps_device(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    assert device["truckId"] == truck["id"]
    assert device["active"] is True

    updated = await client.patch(f"/api/v1/zylo-liquid/gps-devices/{device['id']}", json={"label": "Boîtier test"}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["label"] == "Boîtier test"

    listed = await client.get("/api/v1/zylo-liquid/gps-devices", params={"truckId": truck["id"]}, headers=headers)
    assert listed.status_code == 200, listed.text
    assert any(d["id"] == device["id"] for d in listed.json()["data"])


async def test_gps_device_identifier_unique_per_organization(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    await _create_gps_device(client, headers, suffix, None)
    dup = await client.post("/api/v1/zylo-liquid/gps-devices", json={"deviceIdentifier": f"IMEI-{suffix}"}, headers=headers)
    assert dup.status_code == 409


async def test_ingest_credential_get_and_regenerate(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    first = await _get_ingest_secret(client, headers)
    second = await _get_ingest_secret(client, headers)
    assert first == second  # généré une seule fois, réutilisé ensuite

    regen = await client.post("/api/v1/zylo-liquid/gps-ingest-credential/regenerate", headers=headers)
    assert regen.status_code == 200, regen.text
    assert regen.json()["secretToken"] != first


async def test_ingest_position_success(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)

    res = await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 11, 8, 0, 0).isoformat(), "latitude": 4.05, "longitude": 9.7},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["latitude"] == 4.05
    assert body["gpsDeviceId"] == device["id"]


async def test_ingest_position_accepts_timezone_aware_recorded_at(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Régression : une passerelle (Traccar notamment) envoie souvent un
    horodatage avec fuseau explicite (ex. "+00:00") — trouvé en testant le
    pont Traccar->Zylo Liquid réel (mission « tracking », 2026-09-11).
    recordedAt étant une colonne TIMESTAMP WITHOUT TIME ZONE, un fuseau
    non dépouillé fait planter l'insertion (offset-naive vs offset-aware)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)

    res = await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": "2026-09-11T15:00:00.000+00:00", "latitude": 4.0611, "longitude": 9.7869},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )
    assert res.status_code == 201, res.text


async def test_ingest_position_invalid_secret_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    await _create_gps_device(client, headers, suffix, None)

    res = await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": f"IMEI-{suffix}", "recordedAt": datetime(2026, 9, 11, 8, 0, 0).isoformat(), "latitude": 4.05, "longitude": 9.7},
        headers={"X-Gps-Ingest-Secret": "not-a-real-secret", "X-Organization-Id": zylo_liquid_organization["id"]},
    )
    assert res.status_code == 401


async def test_ingest_position_unknown_device_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    secret = await _get_ingest_secret(client, headers)

    res = await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": "IMEI-NEVER-REGISTERED", "recordedAt": datetime(2026, 9, 11, 8, 0, 0).isoformat(), "latitude": 4.05, "longitude": 9.7},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )
    assert res.status_code == 404


async def test_truck_stop_detected_after_stabilization(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Positions groupées au même endroit pendant plus de 10 minutes (seuil
    par défaut) -> un arrêt confirmé apparaît dans /trucks/{id}/stops,
    jamais dupliqué si on ré-ingère par la suite."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]}

    base = datetime(2026, 9, 11, 8, 0, 0)

    async def _ingest(minutes_offset: int, lat: float, lon: float):
        res = await client.post(
            "/api/v1/zylo-liquid/gps/ingest",
            json={
                "deviceIdentifier": device["deviceIdentifier"],
                "recordedAt": (base + timedelta(minutes=minutes_offset)).isoformat(),
                "latitude": lat, "longitude": lon,
            },
            headers=ingest_headers,
        )
        assert res.status_code == 201, res.text

    # approche (positions éloignées, > rayon de détection)
    for i in range(5):
        await _ingest(i * 2, 4.05 + i * 0.01, 9.7)
    # arrêt de 20 minutes au même endroit (dans le rayon par défaut)
    for i in range(21):
        await _ingest(10 + i, 4.15, 9.7)
    # reprise du mouvement
    for i in range(5):
        await _ingest(31 + i * 2, 4.15 + i * 0.01, 9.7)

    stops = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert stops.status_code == 200, stops.text
    events = stops.json()
    assert len(events) == 1
    assert events[0]["latitude"] == 4.15

    # ré-ingestion d'une position identique : pas de doublon d'arrêt
    await _ingest(50, 4.25, 9.7)
    stops_again = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert len(stops_again.json()) == 1


async def test_truck_current_positions_reflects_last_ping(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)

    await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 11, 9, 0, 0).isoformat(), "latitude": 4.06, "longitude": 9.71},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )

    res = await client.get("/api/v1/zylo-liquid/trucks/current-positions", headers=headers)
    assert res.status_code == 200, res.text
    entry = next(e for e in res.json() if e["truckId"] == truck["id"])
    assert entry["latitude"] == 4.06
    assert entry["longitude"] == 9.71


async def test_truck_positions_and_stops_accept_timezone_aware_query_params(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Régression : le frontend envoie since/until au format ISO suffixé
    'Z' (`Date.prototype.toISOString()`), donc tz-aware une fois parsé par
    Pydantic — alors que recordedAt/startAt sont des colonnes TIMESTAMP
    WITHOUT TIME ZONE. Sans dépouillement du fuseau côté service, asyncpg
    lève une 500 (offset-naive vs offset-aware), masquée en erreur CORS
    côté navigateur (bug trouvé et corrigé dans cette même mission,
    2026-09-11)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)

    await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 11, 9, 0, 0).isoformat(), "latitude": 4.06, "longitude": 9.71},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )

    since = "2026-09-10T09:00:00.000Z"
    until = "2026-09-12T09:00:00.000Z"

    positions = await client.get(f"/api/v1/zylo-liquid/trucks/{truck['id']}/positions", params={"since": since, "until": until}, headers=headers)
    assert positions.status_code == 200, positions.text
    assert len(positions.json()) == 1

    stops = await client.get(f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops", params={"since": since, "until": until}, headers=headers)
    assert stops.status_code == 200, stops.text


async def test_gps_device_management_requires_permission(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]

    outsider_email = f"outsider-gps-{suffix}@example.com"
    outsider_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": outsider_email, "password": outsider_password, "fullName": "Outsider GPS Test"})
    login = await client.post("/api/v1/auth/login", json={"email": outsider_email, "password": outsider_password})
    outsider_token = login.json()["accessToken"]

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        outsider_user = (await db.execute(select(User).where(User.email == outsider_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=outsider_user.id))
        await db.commit()

    outsider_headers = {"Authorization": f"Bearer {outsider_token}", "X-Organization-Id": zylo_liquid_organization["id"]}
    res = await client.post("/api/v1/zylo-liquid/gps-devices", json={"deviceIdentifier": f"IMEI-{suffix}"}, headers=outsider_headers)
    assert res.status_code == 403
