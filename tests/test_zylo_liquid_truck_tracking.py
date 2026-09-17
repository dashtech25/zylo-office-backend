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

    # « now », pas une date fixe passée : l'affectation boîtier<->camion
    # (ouverte à la création du boîtier, juste au-dessus) est horodatée en
    # temps réel — une base de positions antérieure à cette affectation
    # serait exclue par le bornage par fenêtre d'affectation de
    # `run_truck_stop_detection` (2026-09-13, correction).
    base = datetime.now(timezone.utc).replace(tzinfo=None)

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
    # arrêt de 20 minutes au même endroit (dans le rayon par défaut) — écart
    # de 6 min (pas 2) depuis le dernier point d'approche : le dernier saut
    # (4.09 -> 4.15, ~6.7km) doit rester sous le seuil de plausibilité
    # (150 km/h), pas juste sous le rayon de détection d'arrêt.
    for i in range(21):
        await _ingest(14 + i, 4.15, 9.7)
    # reprise du mouvement
    for i in range(5):
        await _ingest(35 + i * 2, 4.15 + i * 0.01, 9.7)

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

    # Relatif à "maintenant", jamais une date calendaire figée : le boîtier
    # n'est associé au camion (donc l'historique d'association ne
    # commence) qu'à l'instant présent (étape 2, `GpsDeviceAssignment`) —
    # une date de position antérieure à une date calendaire fixe finit
    # toujours par se retrouver après "maintenant" au fil du temps.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Jamais avant l'ouverture de l'affectation boitier<->camion (voir
    # _open_gps_device_assignment) sinon la position tombe hors fenetre.
    recorded_at = now
    await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": recorded_at.isoformat(), "latitude": 4.06, "longitude": 9.71},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )

    since = (now - timedelta(hours=2)).isoformat().replace("+00:00", "") + "Z"
    until = (now + timedelta(hours=2)).isoformat().replace("+00:00", "") + "Z"

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


# ================================================================
# Étape 2 — flux métier (réaffectation, lieux nommés, réconciliation,
# alertes d'arrêt non qualifié)
# ================================================================


async def _ingest_stop_sequence(client: AsyncClient, ingest_headers: dict, device_identifier: str, base: datetime, lat: float, lon: float) -> None:
    """Séquence identique à `test_truck_stop_detected_after_stabilization`
    (approche, 21 min immobile au même endroit, reprise) — factorisée pour
    la réutiliser sur des coordonnées de lieu nommé."""
    async def _ingest(minutes_offset: int, ilat: float, ilon: float):
        res = await client.post(
            "/api/v1/zylo-liquid/gps/ingest",
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


async def test_gps_device_reassignment_preserves_history_and_removes_from_live(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck_a = await _create_truck(client, headers, f"A{suffix}")
    truck_b = await _create_truck(client, headers, f"B{suffix}")
    device = await _create_gps_device(client, headers, suffix, truck_a["id"])
    secret = await _get_ingest_secret(client, headers)

    await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 12, 8, 0, 0).isoformat(), "latitude": 4.05, "longitude": 9.70},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )

    # Camion A voit sa position en direct tant que le boîtier lui est associé.
    positions = await client.get("/api/v1/zylo-liquid/trucks/current-positions", headers=headers)
    entry_a = next(e for e in positions.json() if e["truckId"] == truck_a["id"])
    assert entry_a["latitude"] == 4.05

    # Dissociation (scénario 2).
    unassigned = await client.post(f"/api/v1/zylo-liquid/gps-devices/{device['id']}/unassign", headers=headers)
    assert unassigned.status_code == 200, unassigned.text
    assert unassigned.json()["truckId"] is None

    # Camion A n'a plus de position en direct — historique intact séparément.
    positions_after = await client.get("/api/v1/zylo-liquid/trucks/current-positions", headers=headers)
    entry_a_after = next(e for e in positions_after.json() if e["truckId"] == truck_a["id"])
    assert entry_a_after["latitude"] is None

    stops_history = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck_a['id']}/positions",
        params={"since": "2026-09-12T00:00:00Z", "until": "2026-09-13T00:00:00Z"},
        headers=headers,
    )
    # Le camion A n'a plus de boîtier actif -> plus de résolution "boîtier
    # courant" pour lister ses positions passées (limite v1 assumée dans le
    # plan) ; l'essentiel vérifié ici est que rien n'a explosé et que A ne
    # récupère jamais la position live du boîtier après réaffectation.
    assert stops_history.status_code == 200

    # Réassociation à un autre camion (B).
    reassigned = await client.patch(f"/api/v1/zylo-liquid/gps-devices/{device['id']}", json={"truckId": truck_b["id"]}, headers=headers)
    assert reassigned.status_code == 200, reassigned.text
    assert reassigned.json()["truckId"] == truck_b["id"]

    await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device["deviceIdentifier"], "recordedAt": datetime(2026, 9, 12, 9, 0, 0).isoformat(), "latitude": 4.09, "longitude": 9.72},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]},
    )
    positions_b = await client.get("/api/v1/zylo-liquid/trucks/current-positions", headers=headers)
    entry_b = next(e for e in positions_b.json() if e["truckId"] == truck_b["id"])
    assert entry_b["latitude"] == 4.09

    # Historique d'association : deux lignes, la première fermée.
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select as _select

        from app.location.models import GpsDeviceAssignment

        result = await db.execute(_select(GpsDeviceAssignment).where(GpsDeviceAssignment.gpsDeviceId == uuid.UUID(device["id"])).order_by(GpsDeviceAssignment.assignedAt))
        rows = result.scalars().all()
        assert len(rows) == 2
        assert rows[0].truckId == uuid.UUID(truck_a["id"])
        assert rows[0].unassignedAt is not None
        assert rows[1].truckId == uuid.UUID(truck_b["id"])
        assert rows[1].unassignedAt is None


async def test_reassigning_device_to_truck_with_active_device_conflicts(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    await _create_gps_device(client, headers, f"1{suffix}", truck["id"])
    other_device = await _create_gps_device(client, headers, f"2{suffix}", None)

    res = await client.patch(f"/api/v1/zylo-liquid/gps-devices/{other_device['id']}", json={"truckId": truck["id"]}, headers=headers)
    assert res.status_code == 409


async def test_tracking_location_crud_and_move_protection(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]

    created = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": f"Port {suffix}", "type": "port", "latitude": 4.15, "longitude": 9.70, "radiusMeters": 150},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    location = created.json()

    # Jamais visité -> déplacement libre.
    moved = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"latitude": 4.20}, headers=headers)
    assert moved.status_code == 200, moved.text
    assert moved.json()["latitude"] == 4.20

    # Suppression sans historique -> suppression physique (204/200, jamais "deleted" visible ensuite dans la liste par défaut).
    deleted = await client.delete(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    listed = await client.get("/api/v1/zylo-liquid/tracking-locations", headers=headers)
    assert all(l["id"] != location["id"] for l in listed.json())


async def test_truck_stop_matched_to_known_location_no_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]}

    loc_lat, loc_lon = 4.30, 9.80
    created = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": f"Entrepôt {suffix}", "type": "entrepot", "latitude": loc_lat, "longitude": loc_lon, "radiusMeters": 150},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    location = created.json()

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, loc_lat, loc_lon)

    stops = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    events = stops.json()
    assert len(events) == 1
    assert events[0]["locationId"] == location["id"]
    assert events[0]["reconciliationStatus"] == "none"

    alerts = await client.get("/api/v1/zylo-liquid/alerts", params={"truckId": truck["id"], "type": "truck_stop_unqualified"}, headers=headers)
    assert alerts.status_code == 200, alerts.text
    assert alerts.json()["meta"]["total"] == 0


async def test_truck_stop_unqualified_creates_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]}

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    # Coordonnées volontairement isolées (aucun lieu créé dans ce test).
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, -12.50, 45.60)

    alerts = await client.get("/api/v1/zylo-liquid/alerts", params={"truckId": truck["id"], "type": "truck_stop_unqualified"}, headers=headers)
    assert alerts.status_code == 200, alerts.text
    data = alerts.json()["data"]
    assert len(data) == 1
    assert data[0]["truckId"] == truck["id"]
    assert data[0]["stationId"] is None
    assert data[0]["status"] == "active"

    # L'alerte se traite comme n'importe quelle alerte existante (get/acknowledge).
    detail = await client.get(f"/api/v1/zylo-liquid/alerts/{data[0]['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    ack = await client.post(f"/api/v1/zylo-liquid/alerts/{data[0]['id']}/acknowledge", headers=headers)
    assert ack.status_code == 200, ack.text
    assert ack.json()["status"] == "acknowledged"


async def test_truck_stop_reconciliation_ambiguous_then_resolve(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]}

    # Deux lieux ~200m l'un de l'autre, arrêt exactement à mi-chemin ->
    # écart de distance nul, toujours ambigu quel que soit le seuil.
    lat_a, lon_a = 4.5000, 9.9000
    lat_b, lon_b = 4.5018, 9.9000
    stop_lat, stop_lon = 4.5009, 9.9000
    loc_a = (await client.post("/api/v1/zylo-liquid/tracking-locations", json={"name": f"Lieu A {suffix}", "latitude": lat_a, "longitude": lon_a, "radiusMeters": 150}, headers=headers)).json()
    loc_b = (await client.post("/api/v1/zylo-liquid/tracking-locations", json={"name": f"Lieu B {suffix}", "latitude": lat_b, "longitude": lon_b, "radiusMeters": 150}, headers=headers)).json()

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, stop_lat, stop_lon)

    stops = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    events = stops.json()
    assert len(events) == 1
    assert events[0]["locationId"] is None
    assert events[0]["reconciliationStatus"] == "pending"

    pending = await client.get("/api/v1/zylo-liquid/truck-stop-reconciliations", headers=headers)
    assert pending.status_code == 200, pending.text
    matching = [r for r in pending.json() if r["stopEventId"] == events[0]["id"]]
    assert len(matching) == 1
    reconciliation = matching[0]
    assert set(reconciliation["candidateLocationIds"]) == {loc_a["id"], loc_b["id"]}

    resolved = await client.post(
        f"/api/v1/zylo-liquid/truck-stop-reconciliations/{reconciliation['id']}/resolve",
        json={"locationId": loc_a["id"]},
        headers=headers,
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["resolvedLocationId"] == loc_a["id"]

    stops_after = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    assert stops_after.json()[0]["locationId"] == loc_a["id"]
    assert stops_after.json()[0]["reconciliationStatus"] == "resolved"


async def test_truck_stop_comments_multiple_editable_deletable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    truck = await _create_truck(client, headers, suffix)
    device = await _create_gps_device(client, headers, suffix, truck["id"])
    secret = await _get_ingest_secret(client, headers)
    ingest_headers = {"X-Gps-Ingest-Secret": secret, "X-Organization-Id": zylo_liquid_organization["id"]}

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    await _ingest_stop_sequence(client, ingest_headers, device["deviceIdentifier"], base, 1.10, 2.20)
    stops = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": base.isoformat(), "until": (base + timedelta(hours=2)).isoformat()},
        headers=headers,
    )
    stop_id = stops.json()[0]["id"]

    c1 = await client.post(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", json={"body": "Bouchon au rond-point."}, headers=headers)
    assert c1.status_code == 201, c1.text
    c2 = await client.post(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", json={"body": "Contrôle de police."}, headers=headers)
    assert c2.status_code == 201, c2.text

    listed = await client.get(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", headers=headers)
    assert len(listed.json()) == 2

    updated = await client.patch(f"/api/v1/zylo-liquid/truck-stop-comments/{c1.json()['id']}", json={"body": "Bouchon, résolu."}, headers=headers)
    assert updated.status_code == 200, updated.text
    assert updated.json()["body"] == "Bouchon, résolu."

    deleted = await client.delete(f"/api/v1/zylo-liquid/truck-stop-comments/{c2.json()['id']}", headers=headers)
    assert deleted.status_code == 204

    listed_after = await client.get(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", headers=headers)
    assert len(listed_after.json()) == 1
