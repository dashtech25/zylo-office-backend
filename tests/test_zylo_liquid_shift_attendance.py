"""Scénario B1 (pointage des présences du tour) : feuille pré-remplie depuis le planning (A5)
avec statut initial « à pointer » (jamais « présent » par défaut), enregistrement en lot
tout-ou-rien avec erreurs par cellule, remplaçant lié (prévu et réel conservés côte à côte),
personne hors planning, résolution HH:MM, fenêtre de saisie du RT, verrou optimiste, tour clos /
validé, chevauchement réel, événement de domaine pour une absence non justifiée (sans incident),
droits (ni chef d'équipe, ni pompiste, ni caissier) et portée station."""

import uuid
from datetime import date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.shared import events


BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _ctx(client: AsyncClient, h: dict, organization: dict) -> dict:
    """Station + 3 pompes + un tour de 24 h « Journée » (00:00 -> 00:00, donc toujours en cours aujourd'hui)
    + personnel (1 RT, 1 CE, 3 pompistes) planifié AUJOURD'HUI : le pompiste 0 tient deux pompes."""
    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station B1{suffix}", "code": f"B{suffix}"}))["id"]
    product = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SU{suffix}"}))["id"]
    tank = (await _post(client, h, "/tanks", {
        "stationId": station, "fuelProductId": product, "tankNumber": 1, "displayName": "Cuve 1", "capacityLiters": 20000,
        "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
    }))["id"]
    rows = [{"rowNumber": i, "tankId": tank, "pumpNumber": i} for i in (1, 2, 3)]
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": rows}))["data"]]
    shift = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"},
    ]}))["data"][0]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}

    def row(n, code):
        return {"rowNumber": n, "firstName": f"P{n}", "lastName": f"N{suffix}", "email": f"b1-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    staff_rows = [row(1, "zylo_liquid_shift_manager"), row(2, "zylo_liquid_team_lead")] + [row(i, "zylo_liquid_pump_attendant") for i in (3, 4, 5, 6)]
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]
    ids = [s["staff"]["userId"] for s in staff]
    today = date.today()
    assignments = [
        {"userId": ids[0], "shiftRole": "shift_manager"}, {"userId": ids[1], "shiftRole": "team_lead"},
        {"userId": ids[2], "shiftRole": "pump_attendant", "pumpId": pumps[0]}, {"userId": ids[2], "shiftRole": "pump_attendant", "pumpId": pumps[1]},
        {"userId": ids[3], "shiftRole": "pump_attendant", "pumpId": pumps[2]},
    ]
    res = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": station, "from": today.isoformat(), "to": today.isoformat(),
        "occurrences": [{"date": today.isoformat(), "shiftDefinitionId": shift["id"], "assignments": assignments}],
    })
    assert res.status_code == 200, res.text
    occurrence = res.json()["planning"]["occurrences"][0]
    return {
        "station": station, "pumps": pumps, "shift": shift, "roles": roles, "occurrence": occurrence["id"], "suffix": suffix,
        "rt": ids[0], "ce": ids[1], "att": ids[2:],  # att[0] 2 pompes, att[1] 1 pompe, att[2] et att[3] libres (remplaçants)
    }


async def _get(client, headers, occurrence_id):
    return await client.get(f"{BASE}/shift-attendance?occurrenceId={occurrence_id}", headers=headers)


async def _put(client, headers, occurrence_id, lines, version=None):
    body = {"occurrenceId": occurrence_id, "lines": lines}
    if version is not None:
        body["version"] = version
    return await client.put(f"{BASE}/shift-attendance/bulk", json=body, headers=headers)


def _lines(sheet: dict) -> list[dict]:
    """Corps d'envoi issu du GET : toutes les lignes de la feuille, statut inchangé."""
    return [
        {
            "lineKey": l["lineKey"], "lineKind": l["lineKind"], "plannedAssignmentId": l["plannedAssignmentId"], "personUserId": l["personUserId"] if l["lineKind"] != "planned" else None,
            "externalName": l["externalName"], "replacesLineKey": l["replacesLineKey"], "status": l["status"], "arrivalTime": l["arrivalTime"],
            "departureTime": l["departureTime"], "reason": l["reason"], "note": l["note"],
        }
        for l in sheet["lines"]
    ]


def _set(lines: list[dict], sheet: dict, user_id: str, **changes) -> dict:
    index = next(i for i, l in enumerate(sheet["lines"]) if l["personUserId"] == user_id and l["lineKind"] == "planned")
    lines[index].update(changes)
    return lines[index]


def _codes(res) -> set:
    return {(d["rowNumber"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def _insert_occurrence(station_id: str, shift_id: str, day: date, starts_at: datetime, ends_at: datetime, assignments: list[tuple[str, str]], name: str = "Nuit") -> str:
    """Tour posé directement en base (le planning refuse les jours passés) : sert aux cas hors fenêtre et au chevauchement."""
    from app.modules.zylo_liquid.models import ShiftAssignment, ShiftOccurrence

    async with AsyncSessionLocal() as db:
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station_id), shiftDefinitionId=uuid.UUID(shift_id), shiftDate=day, shiftNumber=1, name=name,
            startTime=f"{starts_at:%H:%M}", endTime=f"{ends_at:%H:%M}", startsAt=starts_at, endsAt=ends_at, status="planned",
        )
        db.add(occurrence)
        await db.flush()
        for user_id, role in assignments:
            db.add(ShiftAssignment(occurrenceId=occurrence.id, userId=uuid.UUID(user_id), shiftRole=role))
        await db.commit()
        return str(occurrence.id)


async def _set_status(occurrence_id: str, status: str) -> None:
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(occurrence_id)).values(status=status))
        await db.commit()


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


async def test_sheet_is_prefilled_from_planning_with_pending_status(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await _get(client, h, ctx["occurrence"])
    assert res.status_code == 200, res.text
    sheet = res.json()
    # Aucune feuille enregistrée : lignes virtuelles, version 0, pas de signature.
    assert sheet["sheetId"] is None and sheet["version"] == 0 and sheet["signature"] is None and sheet["lifecycleStatus"] == "declared"
    # Une ligne par PERSONNE planifiée (le pompiste sur deux pompes = une seule ligne), ordre RT, CE, pompes par numéro.
    assert [l["shiftRole"] for l in sheet["lines"]] == ["shift_manager", "team_lead", "pump_attendant", "pump_attendant"]
    assert [l["personUserId"] for l in sheet["lines"]] == [ctx["rt"], ctx["ce"], ctx["att"][0], ctx["att"][1]]
    # Statut initial : « à pointer », jamais « présent » ; rien d'inventé (aucune heure).
    assert all(l["status"] == "pending" and l["arrivalTime"] is None and l["departureTime"] is None and l["lineId"] is None for l in sheet["lines"])
    assert all(l["lineKey"].startswith("planned:") and l["lineKind"] == "planned" for l in sheet["lines"])
    assert [p["pumpNumber"] for p in sheet["lines"][2]["plannedPumps"]] == [1, 2] and [p["pumpNumber"] for p in sheet["lines"][3]["plannedPumps"]] == [3]
    assert sheet["summary"]["total"] == 4 and sheet["summary"]["pointed"] == 0 and sheet["summary"]["toPoint"] == 4
    # Personnes éligibles : nom seulement, jamais l'e-mail ; ceux déjà sur la feuille sont marqués.
    eligible = {p["userId"]: p for p in sheet["eligiblePeople"]}
    assert ctx["att"][2] in eligible and eligible[ctx["att"][2]]["onSheet"] is False and eligible[ctx["rt"]]["onSheet"] is True
    assert all("email" not in p for p in sheet["eligiblePeople"])
    assert sheet["access"]["canWrite"] is True and sheet["access"]["blockedCode"] is None


async def test_bulk_success_replacement_signature_and_unjustified_event(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("AttendanceAbsenceUnjustified", handler)
    try:
        lines = _lines(sheet)
        _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:00")
        _set(lines, sheet, ctx["ce"], status="present", arrivalTime="00:00")
        late = _set(lines, sheet, ctx["att"][0], status="late", arrivalTime="08:15", reason="Panne de moto")
        absent = _set(lines, sheet, ctx["att"][1], status="absent_unjustified")
        # Remplaçant lié à l'absent : un pompiste libre, présent à 08:20.
        lines.append({"lineKey": "new-1", "lineKind": "replacement", "personUserId": ctx["att"][2], "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:20"})
        res = await _put(client, h, ctx["occurrence"], lines, version=0)
        assert res.status_code == 200, res.text
    finally:
        events._handlers["AttendanceAbsenceUnjustified"].remove(handler)
    body = res.json()
    assert body["version"] == 1 and body["sheetId"] is not None
    sig = body["signature"]
    assert sig["firstSignedByUserId"] == sig["lastSignedByUserId"] and sig["firstSignedAt"] == sig["lastSignedAt"]
    by_person = {(l["personUserId"], l["lineKind"]): l for l in body["lines"]}
    pointed_late = by_person[(ctx["att"][0], "planned")]
    assert pointed_late["status"] == "late" and pointed_late["arrivalTime"] == "08:15" and pointed_late["delayMinutes"] == 8 * 60 + 15 and pointed_late["reason"] == "Panne de moto"
    # Prévu (pompe de l'absent) et réel (remplaçant) coexistent : la ligne remplaçant suit sa cible, le prévu n'est pas écrasé.
    replacement = by_person[(ctx["att"][2], "replacement")]
    absent_line = by_person[(ctx["att"][1], "planned")]
    assert replacement["replacesLineKey"] == absent_line["lineKey"] and replacement["shiftRole"] == "pump_attendant"
    assert absent_line["status"] == "absent_unjustified" and [p["pumpNumber"] for p in absent_line["plannedPumps"]] == [3]
    assert [p["pumpNumber"] for p in replacement["plannedPumps"]] == [3]
    assert body["summary"] == {
        "total": 4, "pointed": 4, "toPoint": 0, "present": 3, "late": 1, "absentJustified": 0, "absentUnjustified": 1,
        "replaced": 1, "replacementLines": 1, "unplannedLines": 0,
    }
    # Événement de domaine publié après commit : aucun incident n'est créé par B1.
    assert len(received) == 1 and received[0]["personUserId"] == uuid.UUID(ctx["att"][1]) and str(received[0]["stationId"]) == ctx["station"]
    incidents = await client.get(f"{BASE}/incident-declarations?stationId={ctx['station']}", headers=h)
    assert incidents.status_code == 200 and incidents.json()["meta"]["total"] == 0

    # Second enregistrement : version 2, signature rafraîchie, premier enregistrement conservé ; l'événement n'est pas republié.
    received.clear()
    events.subscribe("AttendanceAbsenceUnjustified", handler)
    try:
        second_lines = _lines(body)
        _set(second_lines, body, ctx["rt"], departureTime="17:30")
        res2 = await _put(client, h, ctx["occurrence"], second_lines, version=1)
    finally:
        events._handlers["AttendanceAbsenceUnjustified"].remove(handler)
    assert res2.status_code == 200, res2.text
    second = res2.json()
    assert second["version"] == 2 and second["signature"]["firstSignedAt"] == sig["firstSignedAt"] and second["signature"]["lastSignedAt"] >= sig["lastSignedAt"]
    rt_line = next(l for l in second["lines"] if l["personUserId"] == ctx["rt"])
    assert rt_line["departureTime"] == "17:30" and rt_line["departedAt"].endswith("17:30:00")
    assert received == []

    # Audit de chaque enregistrement.
    audit = await client.get(f"/api/v1/audit/organizations/{zylo_liquid_organization['id']}/logs?action=zyloLiquid.shiftAttendance.save", headers=h)
    if audit.status_code == 200:
        assert audit.json()["meta"]["total"] >= 2


async def test_all_or_nothing_reports_every_cell(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:05")  # ligne valide : ne doit pas être enregistrée non plus
    _set(lines, sheet, ctx["ce"], status="pending", arrivalTime="08:00")  # status_required_for_time
    _set(lines, sheet, ctx["att"][0], status="present")  # arrival_required
    _set(lines, sheet, ctx["att"][1], status="absent_justified", arrivalTime="08:00")  # arrival_forbidden + reason_required
    res = await _put(client, h, ctx["occurrence"], lines, version=0)
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "shift_attendance_invalid" and "rien n'a été enregistré" in error["message"]
    assert _codes(res) == {
        (2, "arrivalTime", "status_required_for_time"), (3, "arrivalTime", "arrival_required"),
        (4, "arrivalTime", "arrival_forbidden"), (4, "reason", "reason_required"),
    }
    detail = error["details"][0]
    assert set(detail) == {"rowNumber", "lineKey", "field", "code", "message"} and detail["lineKey"] == lines[detail["rowNumber"] - 1]["lineKey"]
    assert all(d["message"] for d in error["details"])
    # Rien d'écrit, même pour la ligne valide.
    after = (await _get(client, h, ctx["occurrence"])).json()
    assert after["sheetId"] is None and after["version"] == 0 and all(l["status"] == "pending" for l in after["lines"])


async def test_time_resolution_and_time_errors(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    # Tour de 8 h (demain 06:00 -> 14:00) posé en base : un départ « avant » l'arrivée ne se résout à aucun jour.
    tomorrow = date.today() + timedelta(days=1)
    start = datetime.combine(tomorrow, datetime.min.time()) + timedelta(hours=6)
    morning = await _insert_occurrence(ctx["station"], ctx["shift"]["id"], tomorrow, start, start + timedelta(hours=8), [(ctx["rt"], "shift_manager"), (ctx["ce"], "team_lead"), (ctx["att"][0], "pump_attendant")], name="Matin")
    sheet = (await _get(client, h, morning)).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="08:10", departureTime="08:00")  # départ avant arrivée
    _set(lines, sheet, ctx["ce"], status="present", arrivalTime="25:00")  # heure invalide
    _set(lines, sheet, ctx["att"][0], status="present", arrivalTime="08:10", departureTime="08:10")  # départ égal à l'arrivée
    res = await _put(client, h, morning, lines)
    assert res.status_code == 422
    assert _codes(res) == {(1, "departureTime", "departure_before_arrival"), (2, "arrivalTime", "time_invalid"), (3, "departureTime", "departure_before_arrival")}
    messages = {d["rowNumber"]: d["message"] for d in res.json()["error"]["details"]}
    assert "avant l'arrivée" in messages[1] and "08:00" in messages[1] and "08:10" in messages[1]
    # Arrivée hors du tour (16:00 pour un tour 06:00-14:00 : après la fin, et la veille serait à plus de 12 h du début).
    far = _lines(sheet)
    _set(far, sheet, ctx["rt"], status="present", arrivalTime="16:00")
    refused = await _put(client, h, morning, far)
    assert refused.status_code == 422 and (1, "arrivalTime", "time_out_of_range") in _codes(refused)
    assert "ne correspond à aucun moment de ce tour" in refused.text
    # Heure valide : arrivée 05:52 (avant le début) et départ 14:05 (après la fin), dates résolues du jour.
    good = _lines(sheet)
    _set(good, sheet, ctx["rt"], status="present", arrivalTime="05:52", departureTime="14:05")
    ok = await _put(client, h, morning, good)
    assert ok.status_code == 200, ok.text
    rt = next(l for l in ok.json()["lines"] if l["personUserId"] == ctx["rt"])
    assert rt["arrivedAt"].endswith("05:52:00") and rt["departedAt"].endswith("14:05:00") and rt["arrivedAt"][:10] == rt["departedAt"][:10]

    # Tour de 24 h : un départ « 00:00 » est résolu au LENDEMAIN (fin du tour).
    full = (await _get(client, h, ctx["occurrence"])).json()
    ok_lines = _lines(full)
    _set(ok_lines, full, ctx["rt"], status="present", arrivalTime="00:00", departureTime="00:00")
    saved = await _put(client, h, ctx["occurrence"], ok_lines)
    assert saved.status_code == 200, saved.text
    rt24 = next(l for l in saved.json()["lines"] if l["personUserId"] == ctx["rt"])
    day_start = datetime.fromisoformat(saved.json()["shift"]["startsAt"])
    assert datetime.fromisoformat(rt24["arrivedAt"]) == day_start and datetime.fromisoformat(rt24["departedAt"]) == day_start + timedelta(days=1)


async def test_replacement_rules_and_person_twice(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:10")
    absent = _set(lines, sheet, ctx["att"][1], status="absent_unjustified")
    present = _set(lines, sheet, ctx["att"][0], status="present", arrivalTime="00:10")
    planned = [dict(l) for l in lines]
    base = len(planned)  # les lignes ajoutées commencent à base + 1
    extra = [
        # remplaçant d'un PRÉSENT
        {"lineKey": "r1", "lineKind": "replacement", "personUserId": ctx["att"][2], "replacesLineKey": present["lineKey"], "status": "present", "arrivalTime": "08:00"},
        # même personne remplaçante deux fois
        {"lineKey": "r2", "lineKind": "replacement", "personUserId": ctx["att"][3], "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"},
        {"lineKey": "r3", "lineKind": "replacement", "personUserId": ctx["att"][3], "replacesLineKey": absent["lineKey"], "status": "late", "arrivalTime": "08:30"},
        # personne déjà planifiée sur la feuille, ajoutée hors planning
        {"lineKey": "u1", "lineKind": "unplanned", "personUserId": ctx["rt"], "status": "present", "arrivalTime": "08:00"},
    ]
    res = await _put(client, h, ctx["occurrence"], planned + extra)
    assert res.status_code == 422, res.text
    codes = _codes(res)
    assert (base + 1, "replacesLineKey", "replacement_not_absent") in codes
    assert (base + 3, "personUserId", "person_twice_on_sheet") in codes
    assert (base + 4, "personUserId", "person_twice_on_sheet") in codes
    # Un remplaçant ne peut être que présent ou en retard.
    bad_status = await _put(client, h, ctx["occurrence"], planned + [{"lineKey": "r4", "lineKind": "replacement", "personUserId": ctx["att"][2], "replacesLineKey": absent["lineKey"], "status": "absent_unjustified"}])
    assert (base + 1, "status", "replacement_status_invalid") in _codes(bad_status)
    # Un seul remplaçant par absent (deux personnes différentes pour le même absent).
    dup = await _put(client, h, ctx["occurrence"], planned + [
        {"lineKey": "r5", "lineKind": "replacement", "personUserId": ctx["att"][3], "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"},
        {"lineKey": "r6", "lineKind": "replacement", "personUserId": ctx["att"][2], "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"},
    ])
    assert dup.status_code == 422 and (base + 2, "replacesLineKey", "replacement_duplicate") in _codes(dup)
    assert "Un seul remplaçant par absent" in dup.text
    # Un remplaçant sans le rôle de l'absent : un porteur du rôle RT ne remplace pas un pompiste.
    rt2, rt2_id = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    wrong = await _put(client, h, ctx["occurrence"], planned + [{"lineKey": "r7", "lineKind": "replacement", "personUserId": rt2_id, "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"}])
    assert wrong.status_code == 422 and (base + 1, "personUserId", "replacement_not_eligible") in _codes(wrong)
    assert "n'a pas le rôle" in wrong.text
    # Personne hors station.
    stranger = await _put(client, h, ctx["occurrence"], planned + [{"lineKey": "r8", "lineKind": "replacement", "personUserId": str(uuid.uuid4()), "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"}])
    assert stranger.status_code == 422 and (base + 1, "personUserId", "person_not_in_station") in _codes(stranger)
    # Rien n'a été écrit par ces refus.
    assert (await _get(client, h, ctx["occurrence"])).json()["sheetId"] is None


async def test_replacement_not_absent_after_absent_returns_and_external_replacement(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    absent = _set(lines, sheet, ctx["att"][1], status="absent_justified", reason="Maladie")
    lines.append({"lineKey": "ext", "lineKind": "replacement", "externalName": "Jean Intérimaire", "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"})
    ok = await _put(client, h, ctx["occurrence"], lines)
    assert ok.status_code == 200, ok.text
    saved = ok.json()
    external = next(l for l in saved["lines"] if l["lineKind"] == "replacement")
    assert external["personUserId"] is None and external["externalName"] == "Jean Intérimaire" and external["personName"] == "Jean Intérimaire"
    assert any(w["code"] == "external_replacement_no_account" for w in saved["warnings"])
    # L'absent revient : tant que la ligne remplaçant existe, l'enregistrement est refusé avec le message qui dit de la retirer.
    back = _lines(saved)
    _set(back, saved, ctx["att"][1], status="late", arrivalTime="09:00")
    refused = await _put(client, h, ctx["occurrence"], back, version=saved["version"])
    assert refused.status_code == 422 and any(code == "replacement_not_absent" for _r, _f, code in _codes(refused))
    assert "retirez le remplaçant" in refused.text
    # Remplaçant retiré de l'envoi (état final) : accepté, la ligne remplaçant est supprimée, le prévu reste.
    fixed = [l for l in back if l["lineKind"] != "replacement"]
    done = await _put(client, h, ctx["occurrence"], fixed, version=saved["version"])
    assert done.status_code == 200, done.text
    assert not [l for l in done.json()["lines"] if l["lineKind"] == "replacement"]
    assert next(l for l in done.json()["lines"] if l["personUserId"] == ctx["att"][1])["status"] == "late"


async def test_unplanned_person_and_one_shift_manager_present(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:30")
    lines.append({"lineKey": "x1", "lineKind": "unplanned", "personUserId": ctx["att"][2], "status": "present", "arrivalTime": "09:00"})
    ok = await _put(client, h, ctx["occurrence"], lines)
    assert ok.status_code == 200, ok.text
    unplanned = next(l for l in ok.json()["lines"] if l["lineKind"] == "unplanned")
    assert unplanned["personUserId"] == ctx["att"][2] and unplanned["shiftRole"] == "pump_attendant" and unplanned["plannedPumps"] == []
    assert ok.json()["summary"]["unplannedLines"] == 1 and any(w["code"] == "unplanned_person" for w in ok.json()["warnings"])
    # Un deuxième RT présent (hors planning, porteur du rôle RT) est refusé.
    rt2, rt2_id = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    again = _lines(ok.json())
    again.append({"lineKey": "x2", "lineKind": "unplanned", "personUserId": rt2_id, "status": "present", "arrivalTime": "09:30"})
    refused = await _put(client, h, ctx["occurrence"], again, version=ok.json()["version"])
    assert refused.status_code == 422 and any(code == "shift_manager_duplicate" for _r, _f, code in _codes(refused))
    # Un nom libre n'est pas permis pour une personne hors planning.
    external = _lines(ok.json()) + [{"lineKey": "x3", "lineKind": "unplanned", "externalName": "Visiteur", "status": "present", "arrivalTime": "09:30"}]
    res = await _put(client, h, ctx["occurrence"], external, version=ok.json()["version"])
    assert res.status_code == 422 and any(code == "external_not_allowed" for _r, _f, code in _codes(res))


async def test_optimistic_version_conflict(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:30")
    first = await _put(client, h, ctx["occurrence"], lines, version=0)
    assert first.status_code == 200
    stale = await _put(client, h, ctx["occurrence"], lines, version=0)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "attendance_changed"
    # Une feuille sans ligne n'est pas enregistrable.
    empty = await _put(client, h, ctx["occurrence"], [], version=1)
    assert empty.status_code == 422 and empty.json()["error"]["code"] == "attendance_empty"


async def test_window_closed_and_validated_and_change_reason(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rt_headers, rt_user = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    sheet = (await _get(client, rt_headers, ctx["occurrence"])).json()
    # Dans la fenêtre : le RT (non planifié) pointe, signé en son nom ; avertissement « pointé par un non-RT planifié ».
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:30")
    ok = await _put(client, rt_headers, ctx["occurrence"], lines, version=0)
    assert ok.status_code == 200, ok.text
    assert ok.json()["signature"]["lastSignedByUserId"] == rt_user
    assert any(w["code"] == "signed_by_non_planned_manager" for w in ok.json()["warnings"])

    # Tour planifié dans 10 jours : trop tôt pour le RT, jamais pour le gérant (le planning n'accepte que des dates à venir).
    future = date.today() + timedelta(days=10)
    res = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": ctx["station"], "from": future.isoformat(), "to": future.isoformat(),
        "occurrences": [{"date": future.isoformat(), "shiftDefinitionId": ctx["shift"]["id"], "assignments": [{"userId": ctx["rt"], "shiftRole": "shift_manager"}]}],
    })
    assert res.status_code == 200, res.text
    future_occurrence = res.json()["planning"]["occurrences"][0]["id"]
    future_sheet = (await _get(client, rt_headers, future_occurrence)).json()
    assert future_sheet["access"]["canWrite"] is False and future_sheet["access"]["blockedCode"] == "attendance_too_early"
    too_early = await _put(client, rt_headers, future_occurrence, _lines(future_sheet))
    assert too_early.status_code == 422 and too_early.json()["error"]["code"] == "attendance_too_early" and "pas encore ouvert" in too_early.json()["error"]["message"]
    manager_lines = _lines(future_sheet)
    manager_lines[0].update(status="present", arrivalTime="05:00")
    assert (await _put(client, h, future_occurrence, manager_lines)).status_code == 200

    # Tour d'il y a 3 jours (hors fenêtre de 12 h après la fin) : refusé au RT, permis au gérant.
    past_start = datetime.combine(date.today() - timedelta(days=3), datetime.min.time())
    past = await _insert_occurrence(ctx["station"], ctx["shift"]["id"], past_start.date(), past_start, past_start + timedelta(days=1), [(ctx["rt"], "shift_manager")], name="Journée")
    past_sheet = (await _get(client, rt_headers, past)).json()
    closed = await _put(client, rt_headers, past, _lines(past_sheet))
    assert closed.status_code == 422 and closed.json()["error"]["code"] == "attendance_window_closed" and "demandez au gérant" in closed.json()["error"]["message"]
    past_lines = _lines(past_sheet)
    past_lines[0].update(status="present", arrivalTime="08:00")
    assert (await _put(client, h, past, past_lines)).status_code == 200

    # Tour clos : toute ligne modifiée exige une raison de correction.
    await _set_status(past, "closed")
    current = (await _get(client, h, past)).json()
    edit = _lines(current)
    edit[0].update(departureTime="17:00")
    no_reason = await _put(client, h, past, edit, version=current["version"])
    assert no_reason.status_code == 422 and (1, "changeReason", "change_reason_required") in _codes(no_reason)
    edit[0]["changeReason"] = "Oubli du départ"
    with_reason = await _put(client, h, past, edit, version=current["version"])
    assert with_reason.status_code == 200, with_reason.text
    assert with_reason.json()["lines"][0]["changeReason"] == "Oubli du départ"
    assert with_reason.json()["access"]["requiresChangeReason"] is True

    # Tour validé : feuille verrouillée pour tous (le gérant aussi).
    await _set_status(past, "validated")
    locked = await _put(client, h, past, _lines(with_reason.json()), version=with_reason.json()["version"])
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "attendance_locked"
    assert (await _get(client, h, past)).json()["lifecycleStatus"] == "locked"


async def test_person_overlap_with_another_shift(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    today_start = datetime.combine(date.today(), datetime.min.time())
    # Tour de nuit d'hier 22:00 -> aujourd'hui 10:00, où le pompiste libre travaille (pointé présent, sans départ).
    night = await _insert_occurrence(ctx["station"], ctx["shift"]["id"], date.today() - timedelta(days=1), today_start - timedelta(hours=2), today_start + timedelta(hours=10), [(ctx["att"][2], "pump_attendant")])
    night_sheet = (await _get(client, h, night)).json()
    night_lines = _lines(night_sheet)
    night_lines[0].update(status="present", arrivalTime="22:00")
    saved = await _put(client, h, night, night_lines)
    assert saved.status_code == 200, saved.text
    assert saved.json()["lines"][0]["arrivedAt"].startswith((today_start - timedelta(hours=2)).strftime("%Y-%m-%dT%H:00"))
    # Le même pompiste ne peut pas être remplaçant aujourd'hui à 08:00 : l'intervalle réel chevauche la nuit.
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    absent = _set(lines, sheet, ctx["att"][1], status="absent_unjustified")
    lines.append({"lineKey": "ov", "lineKind": "replacement", "personUserId": ctx["att"][2], "replacesLineKey": absent["lineKey"], "status": "present", "arrivalTime": "08:00"})
    res = await _put(client, h, ctx["occurrence"], lines)
    assert res.status_code == 422, res.text
    overlap = [d for d in res.json()["error"]["details"] if d["code"] == "person_overlap"]
    assert overlap and "chevauche" in overlap[0]["message"] and "Nuit" in overlap[0]["message"]
    # Départ de la nuit renseigné à 06:00 : plus de chevauchement avec 08:00 (autorisé, repos signalé).
    fixed_night = _lines(saved.json())
    fixed_night[0].update(departureTime="06:00")
    assert (await _put(client, h, night, fixed_night, version=saved.json()["version"])).status_code == 200
    ok = await _put(client, h, ctx["occurrence"], lines)
    assert ok.status_code == 200, ok.text
    assert any(w["code"] == "rest_between_shifts" for w in ok.json()["warnings"])


async def test_planning_locked_once_attendance_started_and_summary(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    today = date.today().isoformat()
    summary_url = f"{BASE}/shift-attendance/summary?stationId={ctx['station']}&from={today}&to={today}"
    before = (await client.get(summary_url, headers=h)).json()
    assert before["occurrences"][0]["hasSheet"] is False and before["occurrences"][0]["summary"]["toPoint"] == 4
    sheet = (await _get(client, h, ctx["occurrence"])).json()
    lines = _lines(sheet)
    _set(lines, sheet, ctx["rt"], status="present", arrivalTime="00:10")
    _set(lines, sheet, ctx["att"][1], status="absent_justified", reason="Congé accordé")
    assert (await _put(client, h, ctx["occurrence"], lines)).status_code == 200
    after = (await client.get(summary_url, headers=h)).json()["occurrences"][0]
    assert after["hasSheet"] is True and after["summary"]["pointed"] == 2 and after["summary"]["toPoint"] == 2
    assert after["summary"]["present"] == 1 and after["summary"]["absentJustified"] == 1
    # Le planning de ce tour n'est plus modifiable depuis A5 (le prévu n'est jamais écrasé) et la grille le marque verrouillé.
    grid = (await client.get(f"{BASE}/shift-planning?stationId={ctx['station']}&from={today}&to={today}", headers=h)).json()
    assert grid["occurrences"][0]["locked"] is True
    planning = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": ctx["station"], "from": today, "to": today,
        "occurrences": [{"date": today, "shiftDefinitionId": ctx["shift"]["id"], "assignments": [{"userId": ctx["rt"], "shiftRole": "shift_manager"}]}],
    })
    assert planning.status_code == 422 and any(d["code"] == "occurrence_locked" for d in planning.json()["error"]["details"])


async def test_permissions_roles_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    org = zylo_liquid_organization
    ctx = await _ctx(client, h, org)
    other = await _ctx(client, h, org)
    # Ni chef d'équipe, ni pompiste, ni caissier : aucun droit sur le pointage (ni lecture, ni écriture).
    for code in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier"):
        headers, _uid = await _scoped_user(client, h, org, code, ctx["station"])
        assert (await _get(client, headers, ctx["occurrence"])).status_code == 403, code
        assert (await _put(client, headers, ctx["occurrence"], [])).status_code == 403, code
    # Auditeur : lecture seule.
    auditor, _uid = await _scoped_user(client, h, org, "zylo_liquid_auditor", ctx["station"])
    read = await _get(client, auditor, ctx["occurrence"])
    assert read.status_code == 200 and read.json()["access"]["canWrite"] is False and read.json()["access"]["blockedCode"] == "permission_denied"
    assert (await _put(client, auditor, ctx["occurrence"], _lines(read.json()))).status_code == 403
    # RT et gérant : lecture + écriture sur LEUR station, jamais sur une autre (portée station).
    for code in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        headers, _uid = await _scoped_user(client, h, org, code, ctx["station"])
        mine = await _get(client, headers, ctx["occurrence"])
        assert mine.status_code == 200 and mine.json()["access"]["canWrite"] is True, code
        assert (await _get(client, headers, other["occurrence"])).status_code == 403, code
        assert (await _put(client, headers, other["occurrence"], _lines(mine.json()))).status_code == 403, code
        assert (await client.get(f"{BASE}/shift-attendance/summary?stationId={other['station']}&from={date.today()}&to={date.today()}", headers=headers)).status_code == 403
    # Le gérant possède toutes les permissions du RT (anti-élévation de assign_role) ; le CE, le pompiste et le caissier aucune du pointage.
    from app.rbac.service import get_role_permission_codes

    async with AsyncSessionLocal() as db:
        perms = {code: await get_role_permission_codes(db, uuid.UUID(ctx["roles"][code])) for code in (
            "zylo_liquid_station_admin", "zylo_liquid_shift_manager", "zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier", "zylo_liquid_auditor")}
    assert set(perms["zylo_liquid_shift_manager"]) <= set(perms["zylo_liquid_station_admin"])
    attendance = {"zyloLiquid.shiftAttendance.read", "zyloLiquid.shiftAttendance.manage"}
    assert attendance <= set(perms["zylo_liquid_shift_manager"]) and attendance <= set(perms["zylo_liquid_station_admin"])
    assert "zyloLiquid.shiftAttendance.read" in perms["zylo_liquid_auditor"] and "zyloLiquid.shiftAttendance.manage" not in perms["zylo_liquid_auditor"]
    for code in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier"):
        assert not (attendance & set(perms[code])), code
    # Tour inexistant : 404, pas de fuite.
    assert (await _get(client, h, str(uuid.uuid4()))).status_code == 404
