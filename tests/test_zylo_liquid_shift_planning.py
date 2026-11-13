"""Scénario A5 (planning des tours) : enregistrement en lot tout-ou-rien d'une
plage (occurrences + affectations), validation sur l'état final (chevauchement
d'une même personne, un responsable de tour, une pompe = un pompiste, un
pompiste peut tenir plusieurs pompes, rattachement à la station), jours passés
refusés, trous détectés, blocage de désactivation d'un tour / d'une personne
avec planning futur, horaires copiés du modèle, droits et portée station."""

import uuid
from datetime import date, timedelta

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal


BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _station(client: AsyncClient, headers: dict) -> str:
    suffix = uuid.uuid4().hex[:6]
    return (await _post(client, headers, "/stations", {"name": f"Station P{suffix}", "code": f"P{suffix}"}))["id"]


async def _ctx(client: AsyncClient, h: dict, organization: dict, pumps: int = 3) -> dict:
    """Station + pompes + 3 tours (Matin 06-14, Soir 14-22, Nuit 22-06) + personnel (1 RT, 1 CE, 3 pompistes)."""
    suffix = uuid.uuid4().hex[:6]
    station = await _station(client, h)
    product = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SU{suffix}"}))["id"]
    tank = (await _post(client, h, "/tanks", {
        "stationId": station, "fuelProductId": product, "tankNumber": 1, "displayName": "Cuve 1", "capacityLiters": 20000,
        "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
    }))["id"]
    pump_rows = [{"rowNumber": i, "tankId": tank, "pumpNumber": i} for i in range(1, pumps + 1)]
    pump_ids = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": pump_rows}))["data"]]
    shifts = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Matin", "startTime": "06:00", "endTime": "14:00"},
        {"rowNumber": 2, "shiftNumber": 2, "name": "Soir", "startTime": "14:00", "endTime": "22:00"},
        {"rowNumber": 3, "shiftNumber": 3, "name": "Nuit", "startTime": "22:00", "endTime": "06:00"},
    ]}))["data"]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}

    def row(n, code):
        return {"rowNumber": n, "firstName": f"P{n}", "lastName": f"N{suffix}", "email": f"a5-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    staff_rows = [row(1, "zylo_liquid_shift_manager"), row(2, "zylo_liquid_team_lead")] + [row(i, "zylo_liquid_pump_attendant") for i in (3, 4, 5)]
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]
    ids = [s["staff"]["userId"] for s in staff]
    return {
        "station": station, "pumps": pump_ids, "shifts": {s["name"]: s for s in shifts}, "roles": roles,
        "rt": ids[0], "ce": ids[1], "att": ids[2:], "suffix": suffix,
    }


def _days() -> tuple[date, date]:
    start = date.today() + timedelta(days=10)
    return start, start + timedelta(days=6)


def _occ(day: date, shift: dict, *assignments: dict) -> dict:
    return {"date": day.isoformat(), "shiftDefinitionId": shift["id"], "assignments": list(assignments)}


def _a(user_id: str, role: str, pump_id: str | None = None) -> dict:
    return {"userId": user_id, "shiftRole": role, **({"pumpId": pump_id} if pump_id else {})}


async def _save(client, headers, ctx, occurrences, start=None, end=None, version=None):
    d0, d1 = _days()
    body = {"stationId": ctx["station"], "from": (start or d0).isoformat(), "to": (end or d1).isoformat(), "occurrences": occurrences}
    if version is not None:
        body["version"] = version
    return await client.put(f"{BASE}/shift-planning/bulk", json=body, headers=headers)


async def _get(client, headers, ctx, start=None, end=None):
    d0, d1 = _days()
    return await client.get(f"{BASE}/shift-planning?stationId={ctx['station']}&from={(start or d0).isoformat()}&to={(end or d1).isoformat()}", headers=headers)


def _codes(res) -> set:
    return {(d["code"], d["cell"]["index"]) for d in res.json()["error"]["details"]}


def _full_morning(ctx, day: date) -> dict:
    shift = ctx["shifts"]["Matin"]
    p = ctx["pumps"]
    return _occ(
        day, shift, _a(ctx["rt"], "shift_manager"), _a(ctx["ce"], "team_lead"),
        _a(ctx["att"][0], "pump_attendant", p[0]), _a(ctx["att"][1], "pump_attendant", p[1]), _a(ctx["att"][2], "pump_attendant", p[2]),
    )


async def _scoped_user(client: AsyncClient, owner_headers: dict, organization: dict, role_code: str, station_id: str) -> tuple[dict, str]:
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
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"]}, str(user_id)


async def test_bulk_save_success_multi_pump_and_grid(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    res = await _save(client, h, ctx, [_full_morning(ctx, d0), _full_morning(ctx, d0 + timedelta(days=1))])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["createdOccurrences"] == 2 and body["addedAssignments"] == 10 and body["assignmentsCount"] == 10

    # Lecture de la grille : occurrences, affectations nommées, personnel éligible sans e-mail.
    grid = (await _get(client, h, ctx)).json()
    assert [s["name"] for s in grid["shifts"]] == ["Matin", "Soir", "Nuit"] and len(grid["pumps"]) == 3
    assert [o["status"] for o in grid["occurrences"]] == ["planned", "planned"]
    assert grid["occurrences"][0]["startTime"] == "06:00" and grid["occurrences"][0]["endsAt"].endswith("14:00:00")
    assert sorted(grid["staff"]) == ["pump_attendant", "shift_manager", "team_lead"]
    assert len(grid["staff"]["pump_attendant"]) == 3 and "email" not in grid["staff"]["shift_manager"][0]
    assert grid["version"] == body["planning"]["version"]

    # Un pompiste sur PLUSIEURS pompes dans un même tour : accepté (6 pompistes pour 14 pompes).
    p = ctx["pumps"]
    two_pumps = _occ(d0 + timedelta(days=2), ctx["shifts"]["Soir"], _a(ctx["att"][0], "pump_attendant", p[0]), _a(ctx["att"][0], "pump_attendant", p[1]), _a(ctx["att"][0], "pump_attendant"))
    first_two = await _save(client, h, ctx, [two_pumps])
    assert first_two.status_code == 200, first_two.text
    # Les cases que le lot ne reprend pas (état final) sont vidées : les deux matins disparaissent.
    assert first_two.json()["createdOccurrences"] == 1 and first_two.json()["deletedOccurrences"] == 2
    # Relancé à l'identique : rien ne change.
    again = await _save(client, h, ctx, [two_pumps])
    assert again.status_code == 200 and again.json()["createdOccurrences"] == 0 and again.json()["addedAssignments"] == 0

    # Échange de deux pompes entre deux pompistes : pas refusé à tort (validation sur l'état final).
    swap = _occ(d0 + timedelta(days=2), ctx["shifts"]["Soir"], _a(ctx["att"][1], "pump_attendant", p[0]), _a(ctx["att"][2], "pump_attendant", p[1]))
    done = await _save(client, h, ctx, [swap])
    assert done.status_code == 200, done.text
    assert done.json()["createdOccurrences"] == 0 and done.json()["deletedOccurrences"] == 0
    assert done.json()["addedAssignments"] == 2 and done.json()["removedAssignments"] == 3
    # Vider la dernière case supprime l'occurrence.
    emptied = await _save(client, h, ctx, [])
    assert emptied.json()["planning"]["occurrences"] == []


async def test_all_or_nothing_reports_every_cell(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    good = _full_morning(ctx, d0)
    bad = _occ(d0 + timedelta(days=1), ctx["shifts"]["Soir"], _a(ctx["rt"], "shift_manager"), _a(str(uuid.uuid4()), "pump_attendant"), _a(ctx["att"][0], "boss"))
    res = await _save(client, h, ctx, [good, bad])
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "shift_planning_invalid" and "rien n'a été enregistré" in error["message"]
    assert _codes(res) == {("person_not_in_station", 1), ("shift_role_invalid", 2)}
    detail = error["details"][0]
    assert set(detail) == {"cell", "field", "code", "message"} and detail["cell"]["date"] == (d0 + timedelta(days=1)).isoformat()
    assert all(d["message"] for d in error["details"])
    # Rien d'écrit, même pour la case valide.
    assert (await _get(client, h, ctx)).json()["occurrences"] == []


async def test_person_overlap_same_day_uses_copied_hours(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    matin, soir, nuit = ctx["shifts"]["Matin"], ctx["shifts"]["Soir"], ctx["shifts"]["Nuit"]
    d1 = d0 + timedelta(days=1)
    # Deux tours consécutifs 06-14 puis 14-22 : frontière exacte acceptée (intervalles semi-ouverts).
    ok = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "pump_attendant")), _occ(d0, soir, _a(ctx["att"][0], "pump_attendant"))])
    assert ok.status_code == 200, ok.text
    # Matin du lendemain planifié pour une autre personne (copie 06:00-14:00).
    ok = await _save(client, h, ctx, [_occ(d1, matin, _a(ctx["att"][1], "pump_attendant"))], start=d1, end=d1)
    assert ok.status_code == 200, ok.text
    # Les modèles changent (Matin 06-10, Soir 10-14) : l'occurrence déjà planifiée garde 06:00-14:00 (copie, jamais resynchronisée).
    upd = await _post(client, h, "/shift-definitions/bulk", {"stationId": ctx["station"], "rows": [
        {"rowNumber": 1, "id": matin["id"], "shiftNumber": 1, "name": "Matin", "startTime": "06:00", "endTime": "10:00"},
        {"rowNumber": 2, "id": soir["id"], "shiftNumber": 2, "name": "Soir", "startTime": "10:00", "endTime": "14:00"},
    ]})
    assert upd["updatedCount"] == 2
    grid = (await _get(client, h, ctx)).json()
    morning = next(o for o in grid["occurrences"] if o["name"] == "Matin" and o["date"] == d0.isoformat())
    assert morning["endTime"] == "14:00" and morning["differsFromDefinition"] is True
    assert next(s for s in grid["shifts"] if s["name"] == "Matin")["endTime"] == "10:00"
    # Ré-enregistrer l'existant tel quel ne re-copie rien et ne signale aucun faux conflit.
    same = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "pump_attendant")), _occ(d0, soir, _a(ctx["att"][0], "pump_attendant")), _occ(d1, matin, _a(ctx["att"][1], "pump_attendant"))])
    assert same.status_code == 200 and same.json()["addedAssignments"] == 0
    # Le Soir du lendemain prend les NOUVEAUX horaires (10-14) : la même personne y chevauche son Matin copié (06-14).
    clash = await _save(client, h, ctx, [
        _occ(d0, matin, _a(ctx["att"][0], "pump_attendant")), _occ(d0, soir, _a(ctx["att"][0], "pump_attendant")),
        _occ(d1, matin, _a(ctx["att"][1], "pump_attendant")), _occ(d1, soir, _a(ctx["att"][1], "pump_attendant")),
    ])
    assert clash.status_code == 422
    detail = clash.json()["error"]["details"][0]
    assert detail["code"] == "person_overlap" and detail["cell"]["shiftDefinitionId"] == soir["id"] and detail["cell"]["date"] == d1.isoformat()
    assert "« Matin » (06:00 → 14:00)" in detail["message"] and "chevauche « Soir »" in detail["message"]
    assert len(clash.json()["error"]["details"]) == 1

    # Nuit de la veille hors plage enregistrée : Nuit du jour X (22:00 -> 06:00) pour une personne, puis Nuit raccourcie
    # et Matin avancé à 05:00 ; planifier le Matin du jour X+1 seul (plage d'un jour) doit voir la nuit voisine.
    night_day = d0 + timedelta(days=4)
    assert (await _save(client, h, ctx, [_occ(night_day, nuit, _a(ctx["att"][2], "pump_attendant"))], start=night_day, end=night_day)).status_code == 200
    await _post(client, h, "/shift-definitions/bulk", {"stationId": ctx["station"], "rows": [
        {"rowNumber": 1, "id": nuit["id"], "shiftNumber": 3, "name": "Nuit", "startTime": "22:00", "endTime": "04:00"},
        {"rowNumber": 2, "id": matin["id"], "shiftNumber": 1, "name": "Matin", "startTime": "05:00", "endTime": "10:00"},
    ]})
    nxt = night_day + timedelta(days=1)
    res = await _save(client, h, ctx, [_occ(nxt, matin, _a(ctx["att"][2], "pump_attendant"))], start=nxt, end=nxt)
    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert detail["code"] == "person_overlap" and "« Nuit » (22:00 → 06:00)" in detail["message"] and "chevauche « Matin »" in detail["message"]
    assert detail["cell"]["shiftRole"] == "pump_attendant" and detail["cell"]["index"] == 0


async def test_two_shift_managers_and_pump_taken_and_roles(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    p, soir = ctx["pumps"], ctx["shifts"]["Soir"]
    # Deux responsables de tour : tous deux signalés (le second est un autre porteur du rôle).
    rt2, _uid = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    me = (await client.get("/api/v1/auth/me", headers=rt2)).json()["id"]
    res = await _save(client, h, ctx, [_occ(d0, soir, _a(ctx["rt"], "shift_manager"), _a(me, "shift_manager"))])
    assert res.status_code == 422
    assert _codes(res) == {("shift_manager_duplicate", 0), ("shift_manager_duplicate", 1)}
    # Une pompe doublée : un seul pompiste par pompe et par tour.
    res = await _save(client, h, ctx, [_occ(d0, soir, _a(ctx["att"][0], "pump_attendant", p[0]), _a(ctx["att"][1], "pump_attendant", p[0]))])
    assert _codes(res) == {("pump_taken", 0), ("pump_taken", 1)}
    assert "Une pompe n'a qu'un pompiste par tour" in res.json()["error"]["details"][0]["message"]
    # Deux rôles pour la même personne dans un tour, et ligne en double.
    res = await _save(client, h, ctx, [_occ(d0, soir, _a(ctx["att"][0], "pump_attendant"), _a(ctx["att"][0], "pump_attendant", p[0]), _a(ctx["rt"], "shift_manager"), _a(ctx["rt"], "shift_manager"))])
    assert _codes(res) == {("assignment_duplicate", 2), ("assignment_duplicate", 3), ("shift_manager_duplicate", 2), ("shift_manager_duplicate", 3)}
    res = await _save(client, h, ctx, [_occ(d0, soir, _a(ctx["att"][0], "pump_attendant"), _a(ctx["att"][0], "team_lead"))])
    assert {c for c, _i in _codes(res)} == {"person_multiple_roles", "person_not_eligible"}


async def test_person_not_attached_or_not_eligible_and_pump_rules(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    other = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    matin = ctx["shifts"]["Matin"]
    # Personne d'une AUTRE station : pas rattachée ici.
    res = await _save(client, h, ctx, [_occ(d0, matin, _a(other["att"][0], "pump_attendant"))])
    assert _codes(res) == {("person_not_in_station", 0)}
    assert "n'est plus rattachée à la station" in res.json()["error"]["details"][0]["message"]
    # Pompiste placé comme responsable de tour : n'a pas le rôle.
    res = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "shift_manager"))])
    assert _codes(res) == {("person_not_eligible", 0)}
    assert "n'a pas le rôle « Responsable de tour »" in res.json()["error"]["details"][0]["message"]
    # Pompe d'une autre station ; pompe sur un non-pompiste.
    res = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "pump_attendant", other["pumps"][0]), _a(ctx["ce"], "team_lead", ctx["pumps"][0]))])
    assert _codes(res) == {("pump_not_found", 0), ("pump_requires_attendant", 1)}
    # Pompe désactivée : refus à la création, mais l'affectation existante reste (ambre) et ne bloque pas.
    ok = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "pump_attendant", ctx["pumps"][0]))])
    assert ok.status_code == 200
    await client.patch(f"{BASE}/pumps/{ctx['pumps'][0]}", json={"active": False}, headers=h)
    again = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["att"][0], "pump_attendant", ctx["pumps"][0]))])
    assert again.status_code == 200
    grid = again.json()["planning"]
    assert grid["occurrences"][0]["assignments"][0]["pumpInactive"] is True and any(w["code"] == "pump_inactive" for w in grid["warnings"])
    res = await _save(client, h, ctx, [_occ(d0 + timedelta(days=1), matin, _a(ctx["att"][1], "pump_attendant", ctx["pumps"][0]))])
    assert _codes(res) == {("pump_inactive", 0)} and "La pompe N° 1 est désactivée" in res.json()["error"]["details"][0]["message"]
    # Tour inactif : pas de nouvelle planification.
    await _post(client, h, "/shift-definitions/bulk", {"stationId": ctx["station"], "rows": [
        {"rowNumber": 1, "id": ctx["shifts"]["Soir"]["id"], "shiftNumber": 2, "name": "Soir", "startTime": "14:00", "endTime": "22:00", "active": False},
    ]})
    res = await _save(client, h, ctx, [_occ(d0, ctx["shifts"]["Soir"], _a(ctx["att"][1], "pump_attendant"))])
    assert {c for c, _i in _codes(res)} == {"shift_inactive"}


async def test_past_day_refused_and_today_allowed(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    today = date.today()
    matin = ctx["shifts"]["Matin"]
    past = today - timedelta(days=1)
    res = await _save(client, h, ctx, [_occ(past, matin, _a(ctx["rt"], "shift_manager"))], start=past, end=today + timedelta(days=1))
    assert res.status_code == 422
    assert {c for c, _i in _codes(res)} == {"planning_day_in_past"} and "est passé" in res.json()["error"]["details"][0]["message"]
    # Aujourd'hui : modifiable (tour planifié pas encore ouvert).
    ok = await _save(client, h, ctx, [_occ(today, matin, _a(ctx["rt"], "shift_manager"))], start=today, end=today + timedelta(days=2))
    assert ok.status_code == 200, ok.text
    # Hors plage déclarée.
    res = await _save(client, h, ctx, [_occ(today + timedelta(days=9), matin, _a(ctx["rt"], "shift_manager"))], start=today, end=today + timedelta(days=2))
    assert {c for c, _i in _codes(res)} == {"date_out_of_range"}
    # Plage invalide (> 31 jours).
    assert (await _get(client, h, ctx, today, today + timedelta(days=40))).status_code == 422


async def test_gaps_and_warnings(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, d6 = _days()
    p, matin, nuit = ctx["pumps"], ctx["shifts"]["Matin"], ctx["shifts"]["Nuit"]
    # Matin du premier jour : RT + une seule pompe couverte, pas de chef d'équipe.
    res = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["rt"], "shift_manager"), _a(ctx["att"][0], "pump_attendant", p[0]))])
    assert res.status_code == 200
    gaps = res.json()["planning"]["gaps"]
    day0 = [g for g in gaps if g["date"] == d0.isoformat() and g["shiftDefinitionId"] == matin["id"]]
    assert {(g["kind"], g["pumpId"]) for g in day0} == {("team_lead_missing", None), ("pump_unattended", p[1]), ("pump_unattended", p[2])}
    assert next(g for g in day0 if g["kind"] == "team_lead_missing")["severity"] == "amber"
    assert all(g["severity"] == "red" for g in day0 if g["kind"] == "pump_unattended")
    # Un tour jamais planifié : responsable manquant + toutes les pompes.
    soir_gaps = [g for g in gaps if g["date"] == d0.isoformat() and g["shiftDefinitionId"] == ctx["shifts"]["Soir"]["id"]]
    assert {g["kind"] for g in soir_gaps} == {"shift_manager_missing", "team_lead_missing", "pump_unattended"}
    # Jour fermé : pas un trou (mais avertissement si on y planifie).
    closed_iso = (d0 + timedelta(days=1)).isoweekday()
    patched = await client.patch(f"{BASE}/stations/{ctx['station']}", json={"closedWeekdays": str(closed_iso)}, headers=h)
    assert patched.status_code == 200, patched.text
    grid = (await _get(client, h, ctx)).json()
    assert grid["closedWeekdays"] == [closed_iso]
    assert not [g for g in grid["gaps"] if g["date"] == (d0 + timedelta(days=1)).isoformat()]
    res = await _save(client, h, ctx, [_occ(d0 + timedelta(days=1), matin, _a(ctx["rt"], "shift_manager"))])
    assert any(w["code"] == "closed_day" for w in res.json()["planning"]["warnings"])

    # Avertissements : repos < 11 h (Nuit 22-06 puis Matin 06-14 le lendemain = 0 h), 4 nuits, 7 jours sur 7.
    monday = d0 + timedelta(days=(7 - d0.weekday()) % 7)  # premier lundi >= d0 : semaine entière dans le futur
    week = [monday + timedelta(days=i) for i in range(7)]
    full_week = [_occ(day, nuit, _a(ctx["att"][0], "pump_attendant")) for day in week[:4]] + [_occ(day, matin, _a(ctx["att"][0], "pump_attendant")) for day in week[4:]]
    res = await _save(client, h, ctx, full_week, start=week[0], end=week[6])
    assert res.status_code == 200, res.text
    codes = {w["code"] for w in res.json()["planning"]["warnings"]}
    assert {"rest_week_none", "too_many_nights"} <= codes


async def test_warnings_rest_between_shifts(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    # Soir (14-22) puis Matin (06-14) du lendemain : 8 h de repos, autorisé mais signalé.
    res = await _save(client, h, ctx, [
        _occ(d0, ctx["shifts"]["Soir"], _a(ctx["att"][0], "pump_attendant")),
        _occ(d0 + timedelta(days=1), ctx["shifts"]["Matin"], _a(ctx["att"][0], "pump_attendant")),
    ])
    assert res.status_code == 200, res.text
    rest = [w for w in res.json()["planning"]["warnings"] if w["code"] == "rest_between_shifts"]
    assert len(rest) == 1 and rest[0]["date"] == (d0 + timedelta(days=1)).isoformat() and "moins de 11 h" in rest[0]["message"]


async def test_block_deactivation_of_shift_and_person_with_future_planning(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    soir = ctx["shifts"]["Soir"]
    ok = await _save(client, h, ctx, [
        _occ(d0, soir, _a(ctx["att"][0], "pump_attendant")),
        _occ(d0 + timedelta(days=1), soir, _a(ctx["att"][0], "pump_attendant")),
        _occ(d0 + timedelta(days=2), soir, _a(ctx["att"][1], "pump_attendant")),
    ])
    assert ok.status_code == 200, ok.text
    # Tour : désactivation bloquée, message avec les dates.
    off = await client.post(f"{BASE}/shift-definitions/bulk", json={"stationId": ctx["station"], "rows": [
        {"rowNumber": 1, "id": soir["id"], "shiftNumber": 2, "name": "Soir", "startTime": "14:00", "endTime": "22:00", "active": False},
    ]}, headers=h)
    assert off.status_code == 422
    detail = off.json()["error"]["details"][0]
    assert (detail["rowNumber"], detail["field"], detail["code"]) == (1, "active", "shift_has_planned_occurrences")
    assert "« Soir »" in detail["message"] and "Retirez ces affectations dans l'onglet Planning" in detail["message"]
    assert str(d0.day) in detail["message"]
    # Personne : désactivation et changement de poste bloqués.
    deact = await client.post(f"{BASE}/station-staff/{ctx['att'][0]}/deactivate", headers=h)
    assert deact.status_code == 409 and deact.json()["error"]["code"] == "person_has_planned_shifts"
    assert "Remplacez-la dans l'onglet Planning" in deact.json()["error"]["message"]
    change = await client.put(f"{BASE}/station-staff/{ctx['att'][0]}/role", json={"roleId": ctx["roles"]["zylo_liquid_team_lead"]}, headers=h)
    assert change.status_code == 409 and change.json()["error"]["code"] == "person_has_planned_shifts"
    # Le même poste (no-op) n'est pas bloqué ; une personne sans planning se désactive normalement.
    same = await client.put(f"{BASE}/station-staff/{ctx['att'][0]}/role", json={"roleId": ctx["roles"]["zylo_liquid_pump_attendant"]}, headers=h)
    assert same.status_code == 200, same.text
    free = await client.post(f"{BASE}/station-staff/{ctx['att'][2]}/deactivate", headers=h)
    assert free.status_code == 200, free.text
    # Après retrait du planning futur, tout redevient possible.
    assert (await _save(client, h, ctx, [])).status_code == 200
    assert (await client.post(f"{BASE}/station-staff/{ctx['att'][0]}/deactivate", headers=h)).status_code == 200
    assert (await client.post(f"{BASE}/shift-definitions/bulk", json={"stationId": ctx["station"], "rows": [
        {"rowNumber": 1, "id": soir["id"], "shiftNumber": 2, "name": "Soir", "startTime": "14:00", "endTime": "22:00", "active": False},
    ]}, headers=h)).status_code == 200
    # Une personne désactivée n'est plus proposée ni acceptée dans un nouveau planning.
    res = await _save(client, h, ctx, [_occ(d0, ctx["shifts"]["Matin"], _a(ctx["att"][0], "pump_attendant"))])
    assert {c for c, _i in _codes(res)} == {"person_inactive"}


async def test_concurrent_change_returns_409_and_audit(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.audit.models import AuditLog

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    matin = ctx["shifts"]["Matin"]
    version = (await _get(client, h, ctx)).json()["version"]
    first = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["rt"], "shift_manager"))], version=version)
    assert first.status_code == 200, first.text
    stale = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["ce"], "team_lead"))], version=version)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "planning_changed"
    fresh = await _save(client, h, ctx, [_occ(d0, matin, _a(ctx["rt"], "shift_manager"), _a(ctx["ce"], "team_lead"))], version=first.json()["planning"]["version"])
    assert fresh.status_code == 200
    await _save(client, h, ctx, [])
    async with AsyncSessionLocal() as db:
        actions = (await db.execute(
            select(AuditLog.action).where(AuditLog.entityType == "ShiftOccurrence", AuditLog.scopeResourceId == uuid.UUID(ctx["station"]))
        )).scalars().all()
    assert sorted(actions) == ["zyloLiquid.shiftPlanning.create", "zyloLiquid.shiftPlanning.delete", "zyloLiquid.shiftPlanning.update"]


async def test_permissions_roles_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    other = await _ctx(client, h, zylo_liquid_organization)
    d0, _ = _days()
    await _save(client, h, ctx, [_full_morning(ctx, d0)])

    org = zylo_liquid_organization
    # Lecture seule : responsable de tour, chef d'équipe, pompiste, caissier, auditeur.
    for code in ("zylo_liquid_shift_manager", "zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier", "zylo_liquid_auditor"):
        headers, _uid = await _scoped_user(client, h, org, code, ctx["station"])
        res = await _get(client, headers, ctx)
        assert res.status_code == 200, (code, res.text)
        assert len(res.json()["occurrences"]) == 1
        assert (await _save(client, headers, ctx, [])).status_code == 403, code
        # Portée station : aucune lecture de la station voisine.
        assert (await _get(client, headers, other)).status_code == 403, code

    # Gérant scopé : lit et écrit chez lui, refusé ailleurs.
    manager, _uid = await _scoped_user(client, h, org, "zylo_liquid_station_admin", ctx["station"])
    assert (await _get(client, manager, ctx)).status_code == 200
    assert (await _save(client, manager, ctx, [_full_morning(ctx, d0)])).status_code == 200
    assert (await _get(client, manager, other)).status_code == 403
    assert (await _save(client, manager, other, [])).status_code == 403

    # Le gérant possède toutes les permissions du responsable de tour (donc du planning en lecture).
    from app.rbac.service import get_role_permission_codes

    async with AsyncSessionLocal() as db:
        manager_perms = await get_role_permission_codes(db, uuid.UUID(ctx["roles"]["zylo_liquid_station_admin"]))
        rt_perms = await get_role_permission_codes(db, uuid.UUID(ctx["roles"]["zylo_liquid_shift_manager"]))
    assert {"zyloLiquid.shiftPlanning.read", "zyloLiquid.shiftPlanning.manage"} <= set(manager_perms)
    assert set(rt_perms) <= set(manager_perms)
    assert "zyloLiquid.shiftPlanning.manage" not in rt_perms
