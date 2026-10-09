"""Scénario A9 (définir les tours d'une station) : upsert en lot tout-ou-rien,
validation sur l'état final (unicité, chevauchement avec passage de minuit,
tour de 24 h exclusif), durée calculée, droits par station."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal


BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _station(client: AsyncClient, headers: dict) -> str:
    suffix = uuid.uuid4().hex[:6]
    res = await client.post(f"{BASE}/stations", json={"name": f"Station T{suffix}", "code": f"T{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _scoped_user(client: AsyncClient, owner_headers: dict, organization: dict, role_code: str, station_id: str) -> dict:
    email = f"{role_code}-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "fullName": "Scoped Test"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    token = login.json()["accessToken"]

    from app.identity.models import OrganizationUser, User

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=organization["id"], userId=user.id))
        await db.commit()
        user_id = user.id
    roles = await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=owner_headers)
    role = next(r for r in roles.json() if r["code"] == role_code)
    res = await client.post(
        f"/api/v1/rbac/organizations/{organization['id']}/user-roles",
        json={"userId": str(user_id), "roleId": role["id"], "resourceType": "station", "resourceId": station_id},
        headers=owner_headers,
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"]}

def _row(n: int, number: int, name: str, start: str, end: str, active: bool = True, **extra) -> dict:
    return {"rowNumber": n, "shiftNumber": number, "name": name, "startTime": start, "endTime": end, "active": active, **extra}


async def _bulk(client, headers, station, rows):
    return await client.post(f"{BASE}/shift-definitions/bulk", json={"stationId": station, "rows": rows}, headers=headers)


async def _list(client, headers, station, suffix=""):
    return await client.get(f"{BASE}/shift-definitions?stationId={station}{suffix}", headers=headers)


def _pairs(res) -> set:
    return {(d["rowNumber"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def _three(client, h, station):
    res = await _bulk(client, h, station, [
        _row(1, 1, "Matin", "06:00", "14:00"), _row(2, 2, "Soir", "14:00", "22:00"), _row(3, 3, "Nuit", "22:00", "06:00"),
    ])
    assert res.status_code == 200, res.text
    return res.json()


async def test_bulk_create_three_shifts_with_duration_and_midnight(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    body = await _three(client, h, station)
    assert body["createdCount"] == 3 and body["updatedCount"] == 0
    # Frontière exacte 14:00/14:00 et 22:00/22:00 acceptée (intervalles semi-ouverts).
    assert [(s["durationMinutes"], s["crossesMidnight"]) for s in body["data"]] == [(480, False), (480, False), (480, True)]
    listing = await _list(client, h, station)
    assert [s["name"] for s in listing.json()["data"]] == ["Matin", "Soir", "Nuit"]
    assert listing.json()["meta"]["total"] == 3


async def test_full_day_shift_duration(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [_row(1, 1, "Tour de 24 h", "06:15", "06:15")])
    assert res.status_code == 200, res.text
    assert res.json()["data"][0]["durationMinutes"] == 1440 and res.json()["data"][0]["crossesMidnight"] is True


async def test_full_day_exclusive(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [_row(1, 1, "Jour", "06:15", "06:15"), _row(2, 2, "Autre", "01:00", "02:00")])
    assert res.status_code == 422
    codes = {d["code"] for d in res.json()["error"]["details"]}
    assert codes == {"shift_full_day_exclusive"} and {d["rowNumber"] for d in res.json()["error"]["details"]} == {1, 2}
    # Un tour de 24 h INACTIF ne bloque pas.
    ok = await _bulk(client, h, station, [_row(1, 1, "Jour", "06:15", "06:15", active=False), _row(2, 2, "Autre", "01:00", "02:00")])
    assert ok.status_code == 200, ok.text


async def test_all_or_nothing_with_row_errors(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [
        _row(1, 1, "Matin", "06:00", "14:00"),
        _row(2, 0, "", "25:00", "14:7"),
        _row(3, 3, "x" * 101, "15:00", "16:00"),
    ])
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "shift_definition_bulk_invalid"
    assert _pairs(res) == {
        (2, "shiftNumber", "shift_number_invalid"), (2, "name", "shift_name_required"),
        (2, "startTime", "time_invalid"), (2, "endTime", "time_invalid"), (3, "name", "shift_name_too_long"),
    }
    assert (await _list(client, h, station)).json()["meta"]["total"] == 0


async def test_duplicates_in_batch_and_in_database(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "10:00"), _row(2, 1, "matin", "11:00", "12:00")])
    assert res.status_code == 422
    assert _pairs(res) == {
        (1, "shiftNumber", "shift_number_duplicate_in_batch"), (2, "shiftNumber", "shift_number_duplicate_in_batch"),
        (1, "name", "shift_name_duplicate_in_batch"), (2, "name", "shift_name_duplicate_in_batch"),
    }
    await _three(client, h, station)
    res = await _bulk(client, h, station, [_row(1, 3, "Matin", "02:00", "03:00")])
    assert {(r, f, c) for r, f, c in _pairs(res) if c != "shift_overlap"} == {(1, "shiftNumber", "shift_number_taken"), (1, "name", "shift_name_taken")}
    assert "« Nuit »" in next(d["message"] for d in res.json()["error"]["details"] if d["code"] == "shift_number_taken")


async def test_overlap_message_and_midnight(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    res = await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "14:30"), _row(2, 2, "Soir", "14:00", "22:00")])
    assert res.status_code == 422
    msg = next(d for d in res.json()["error"]["details"] if d["rowNumber"] == 2)
    assert msg["field"] == "startTime" and msg["code"] == "shift_overlap"
    assert msg["message"] == "Le tour « Soir » (14:00 → 22:00) chevauche « Matin » (06:00 → 14:30). Décalez l'heure de début à 14:30 ou plus tard."
    # Passage de minuit : Nuit 22:00 → 06:30 chevauche Matin 06:00 → 14:00 ; 23:00 → 01:00 chevauche aussi 00:30 → 02:00.
    res = await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "14:00"), _row(2, 2, "Nuit", "22:00", "06:30")])
    assert (2, "endTime", "shift_overlap") in _pairs(res)
    res = await _bulk(client, h, station, [_row(1, 1, "A", "23:00", "01:00"), _row(2, 2, "B", "00:30", "02:00")])
    assert res.status_code == 422
    # Un tour inactif est ignoré pour le chevauchement.
    ok = await _bulk(client, h, station, [_row(1, 1, "A", "23:00", "01:00"), _row(2, 2, "B", "00:30", "02:00", active=False)])
    assert ok.status_code == 200, ok.text


async def test_overlap_with_existing_shift_not_in_batch(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    await _three(client, h, station)
    res = await _bulk(client, h, station, [_row(1, 4, "Extra", "13:00", "15:00")])
    assert res.status_code == 422
    assert {d["code"] for d in res.json()["error"]["details"]} == {"shift_overlap"}


async def test_update_by_id_swap_numbers_and_deactivate(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    shifts = (await _three(client, h, station))["data"]
    matin, soir, nuit = shifts
    # Échange des numéros 1 et 2 + désactivation de Nuit, dans un seul lot ; Nuit reste inclus par id.
    res = await _bulk(client, h, station, [
        _row(1, 2, matin["name"], "06:00", "14:00", id=matin["id"]),
        _row(2, 1, soir["name"], "14:00", "22:00", id=soir["id"]),
        _row(3, 3, nuit["name"], "22:00", "06:00", active=False, id=nuit["id"]),
    ])
    assert res.status_code == 200, res.text
    assert res.json()["createdCount"] == 0 and res.json()["updatedCount"] == 3
    listing = await _list(client, h, station)
    assert [s["name"] for s in listing.json()["data"]] == ["Soir", "Matin", "Nuit"]
    inactive = await _list(client, h, station, "&active=false")
    assert [s["name"] for s in inactive.json()["data"]] == ["Nuit"]
    assert inactive.json()["data"][0]["id"] == nuit["id"]
    # Relancé à l'identique : rien ne change, rien n'est compté comme modifié.
    again = await _bulk(client, h, station, [_row(1, 2, "Matin", "06:00", "14:00", id=matin["id"])])
    assert again.status_code == 200 and again.json()["updatedCount"] == 0
    # Réactivation possible.
    react = await _bulk(client, h, station, [_row(1, 3, "Nuit", "22:00", "06:00", id=nuit["id"])])
    assert react.status_code == 200 and react.json()["data"][0]["active"] is True


async def test_update_unknown_or_foreign_id(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    other = await _station(client, h)
    foreign = (await _bulk(client, h, other, [_row(1, 1, "Matin", "06:00", "14:00")])).json()["data"][0]
    for bad_id in (str(uuid.uuid4()), foreign["id"]):
        res = await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "14:00", id=bad_id)])
        assert res.status_code == 422
        assert (1, "name", "shift_not_found") in _pairs(res)
    # Mêmes numéro/nom dans une autre station : autorisé.
    assert (await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "14:00")])).status_code == 200


async def test_attendant_reads_but_cannot_write_and_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    other = await _station(client, h)
    await _three(client, h, station)
    await _bulk(client, h, other, [_row(1, 1, "Autre", "06:00", "14:00")])

    attendant = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_pump_attendant", station)
    listing = await client.get(f"{BASE}/shift-definitions", headers=attendant)
    assert listing.status_code == 200, listing.text
    assert {s["stationId"] for s in listing.json()["data"]} == {station}
    assert (await _bulk(client, attendant, station, [_row(1, 9, "X", "01:00", "02:00", active=False)])).status_code == 403

    # Gérant scopé à UNE station : écrit chez lui, refusé ailleurs.
    manager = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_station_admin", station)
    assert (await _bulk(client, manager, station, [_row(1, 9, "X", "01:00", "02:00", active=False)])).status_code == 200
    assert (await _bulk(client, manager, other, [_row(1, 9, "X", "01:00", "02:00", active=False)])).status_code == 403
    lead = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_team_lead", station)
    assert (await _list(client, lead, station)).status_code == 200
    assert (await _bulk(client, lead, station, [_row(1, 10, "Y", "03:00", "04:00")])).status_code == 403


async def test_audit_entries_written(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.audit.models import AuditLog

    h = _headers(registered_user, zylo_liquid_organization)
    station = await _station(client, h)
    shifts = (await _three(client, h, station))["data"]
    await _bulk(client, h, station, [_row(1, 1, "Matin", "06:00", "13:00", id=shifts[0]["id"])])
    async with AsyncSessionLocal() as db:
        actions = (await db.execute(
            select(AuditLog.action).where(AuditLog.entityType == "ShiftDefinition", AuditLog.scopeResourceId == uuid.UUID(station))
        )).scalars().all()
    assert sorted(actions) == ["zyloLiquid.shiftDefinition.create"] * 3 + ["zyloLiquid.shiftDefinition.update"]
