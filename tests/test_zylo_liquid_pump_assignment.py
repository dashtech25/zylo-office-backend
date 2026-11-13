"""Scénario B4 (affectation réelle des pompistes aux pompes) : brouillon prérempli depuis le planning A5
(rien de stocké), confirmation tout-ou-rien avec erreurs par cellule, prévu et réel conservés côte à côte
(écart jamais bloquant), un pompiste sur plusieurs pompes, pompe fermée avec observation, verrou après
confirmation, verrou optimiste, audit, événement après commit, vue réduite du pompiste, droits (RT/gérant
manage, chef d'équipe lecture seule) et portée station, fonctions publiques pour B5/D3.

Le tour « ouvert » est posé directement en base (occurrence `opened` + rapport + lignes de pompe) : B4 ne dépend
que du modèle d'occurrence et du rapport de B3, pas de son API d'ouverture."""

import uuid
from datetime import date, datetime, timezone

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.shared import events
from app.modules.zylo_liquid.exploitation import pumps_affectation as pumps_affectation

BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _scoped_user(client: AsyncClient, owner_headers: dict, organization: dict, role_code: str, station_id: str) -> tuple[dict, str]:
    email = f"{role_code}-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "fullName": f"Scoped {role_code[-6:]}"})
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


async def _ctx(client: AsyncClient, h: dict, organization: dict, plan: bool = True) -> dict:
    """Station, 3 pompes, tour de 24 h, personnel (RT, CE, 2 pompistes libres) + un pompiste CONNECTABLE (`att_login`)
    planifié sur la pompe 3 ; le pompiste `att[0]` est planifié sur les pompes 1 et 2 (un pompiste, deux pompes).
    Le tour est ensuite ouvert directement en base (occurrence `opened` + rapport + 3 lignes de pompe)."""
    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station B4{suffix}", "code": f"D{suffix}"}))["id"]
    product = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SB{suffix}"}))["id"]
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
        return {"rowNumber": n, "firstName": f"P{n}", "lastName": f"N{suffix}", "email": f"b4-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    staff_rows = [row(1, "zylo_liquid_shift_manager"), row(2, "zylo_liquid_team_lead"), row(3, "zylo_liquid_pump_attendant"), row(4, "zylo_liquid_pump_attendant"), row(5, "zylo_liquid_pump_attendant")]
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]
    ids = [s["staff"]["userId"] for s in staff]
    att_headers, att_login = await _scoped_user(client, h, organization, "zylo_liquid_pump_attendant", station)
    today = date.today()
    assignments = [{"userId": ids[0], "shiftRole": "shift_manager"}, {"userId": ids[1], "shiftRole": "team_lead"}]
    if plan:
        assignments += [
            {"userId": ids[2], "shiftRole": "pump_attendant", "pumpId": pumps[0]}, {"userId": ids[2], "shiftRole": "pump_attendant", "pumpId": pumps[1]},
            {"userId": att_login, "shiftRole": "pump_attendant", "pumpId": pumps[2]},
        ]
    res = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": station, "from": today.isoformat(), "to": today.isoformat(),
        "occurrences": [{"date": today.isoformat(), "shiftDefinitionId": shift["id"], "assignments": assignments}],
    })
    assert res.status_code == 200, res.text
    occurrence = res.json()["planning"]["occurrences"][0]["id"]
    report = await _open_tour(station, occurrence, pumps, tank, ids[0])
    return {
        "station": station, "pumps": pumps, "occurrence": occurrence, "report": report, "roles": roles, "organization": organization,
        "rt": ids[0], "ce": ids[1], "att": ids[2:], "att_login": att_login, "att_headers": att_headers,
    }


async def _open_tour(station: str, occurrence: str, pumps: list[str], tank: str, rt_user: str) -> str:
    from app.modules.zylo_liquid.models import ShiftOccurrence, ShiftReport, ShiftReportPumpLine

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(occurrence)).values(status="opened", openedAt=now))
        occ = await db.get(ShiftOccurrence, uuid.UUID(occurrence))
        report = ShiftReport(
            stationId=uuid.UUID(station), occurrenceId=occ.id, shiftDate=occ.shiftDate, shiftNumber=occ.shiftNumber, shiftName=occ.name,
            startTime=occ.startTime, endTime=occ.endTime, responsibleUserId=uuid.UUID(rt_user), openedByUserId=uuid.UUID(rt_user), openedAt=now,
        )
        db.add(report)
        await db.flush()
        for number, pump in enumerate(pumps, start=1):
            db.add(ShiftReportPumpLine(
                reportId=report.id, pumpId=uuid.UUID(pump), pumpNumber=number, pumpName=f"Pompe {number}", tankId=uuid.UUID(tank),
                fuelProductName="Super", openingIndex=1000 * number, openingSource="initial",
            ))
        await db.commit()
        return str(report.id)


async def _get(client, headers, report_id):
    return await client.get(f"{BASE}/shift-reports/{report_id}/assignments", headers=headers)


async def _put(client, headers, report_id, rows, version=0, decided_by=None):
    body = {"assignmentVersion": version, "rows": rows}
    if decided_by is not None:
        body["decidedByUserId"] = decided_by
    return await client.put(f"{BASE}/shift-reports/{report_id}/assignments", json=body, headers=headers)


def _rows_from(view: dict) -> list[dict]:
    """Corps d'envoi issu du GET (état affiché, brouillon prérempli)."""
    return [{"pumpId": r["pumpId"], "userId": r["userId"], "closedForShift": r["closedForShift"], "note": r["note"]} for r in view["rows"]]


def _codes(res) -> set:
    return {(d["rowKey"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def test_get_is_prefilled_from_planning_and_nothing_is_stored(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await _get(client, h, ctx["report"])
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["assignmentVersion"] == 0 and view["confirmed"] is False and view["prefilledFromPlanning"] is True
    assert view["restricted"] is False and view["shift"]["status"] == "opened"
    # Une ligne par pompe, préremplie avec le pompiste PRÉVU (un pompiste sur deux pompes), écart « conforme », rien de stocké.
    assert [r["pumpNumber"] for r in view["rows"]] == [1, 2, 3]
    assert [r["userId"] for r in view["rows"]] == [ctx["att"][0], ctx["att"][0], ctx["att_login"]]
    assert [r["plannedUserId"] for r in view["rows"]] == [r["userId"] for r in view["rows"]]
    assert all(r["deviation"] == "conforme" and r["segmentId"] is None and r["rowKey"] == f"pump:{r['pumpId']}" for r in view["rows"])
    assert view["byAttendant"][0]["pumpNumbers"] in ([1, 2], [3]) and sorted(sum((b["pumpNumbers"] for b in view["byAttendant"]), [])) == [1, 2, 3]
    assert view["summary"] == {"pumps": 3, "attendants": 2, "deviations": 0, "unassigned": 0, "closed": 0}
    # Éligibles : nom seulement (jamais d'e-mail), prévus en tête avec le nombre de pompes prévues ; CE éligible = chef d'équipe.
    eligible = view["eligibleAttendants"]
    assert all("email" not in p for p in eligible) and {p["userId"] for p in eligible} >= {ctx["att"][0], ctx["att"][1], ctx["att"][2], ctx["att_login"]}
    assert [p["planned"] for p in eligible][:2] == [True, True] and next(p for p in eligible if p["userId"] == ctx["att"][0])["plannedPumpCount"] == 2
    assert [p["userId"] for p in view["eligibleTeamLeads"]] == [ctx["ce"]] and view["plannedDecider"]["userId"] == ctx["ce"]
    assert ctx["rt"] not in {p["userId"] for p in eligible}
    assert view["access"]["canManage"] is True and view["access"]["locked"] is False
    from app.modules.zylo_liquid import service

    async with AsyncSessionLocal() as db:
        assert await pumps_affectation.list_assignment_segments(db, uuid.UUID(ctx["report"])) == []
        assert await pumps_affectation.is_pump_assignment_confirmed(db, uuid.UUID(ctx["report"])) is False
        assert await pumps_affectation.get_current_assignee(db, uuid.UUID(ctx["report"]), uuid.UUID(ctx["pumps"][0])) is None


async def test_confirm_keeps_planned_vs_real_locks_and_audits(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("PumpAssignmentConfirmed", handler)
    view = (await _get(client, h, ctx["report"])).json()
    rows = _rows_from(view)
    # Le chef d'équipe a décidé : pompe 3 → pompiste libre (non prévu au planning) ; le titulaire prévu n'est plus affecté.
    rows[2].update(userId=ctx["att"][1], note="titulaire absent")
    res = await _put(client, h, ctx["report"], rows, decided_by=ctx["ce"])
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["confirmed"] is True and out["assignmentVersion"] == 1 and out["prefilledFromPlanning"] is False
    assert out["confirmedBy"] is not None and out["confirmedAt"] is not None and out["decidedBy"]["userId"] == ctx["ce"]
    assert out["access"]["locked"] is True and out["access"]["lockedCode"] == "assignment_locked" and out["access"]["canManage"] is False
    # Prévu conservé, réel enregistré, écart calculé et jamais bloquant ; le prévu sans pompe est signalé en information.
    third = out["rows"][2]
    assert third["plannedUserId"] == ctx["att_login"] and third["userId"] == ctx["att"][1] and third["deviation"] == "not_planned" and third["note"] == "titulaire absent"
    assert out["rows"][0]["deviation"] == "conforme" and out["rows"][0]["segmentId"] is not None
    assert [p["userId"] for p in out["plannedWithoutPump"]] == [ctx["att_login"]]
    assert out["summary"]["deviations"] == 1 and out["summary"]["attendants"] == 2
    assert received and received[-1]["deviations"] == 1 and received[-1]["pumps"] == 3 and str(received[-1]["reportId"]) == ctx["report"]

    from app.audit.models import AuditLog
    from app.modules.zylo_liquid import service
    from app.modules.zylo_liquid.models import ShiftPumpAssignment

    async with AsyncSessionLocal() as db:
        segments = await pumps_affectation.list_assignment_segments(db, uuid.UUID(ctx["report"]), current_only=True)
        assert len(segments) == 3 and all(s.kind == "start" and s.endsAt is None and s.recordedByUserId is not None for s in segments)
        by_pump = {str(s.pumpId): s for s in segments}
        assert str(by_pump[ctx["pumps"][2]].plannedUserId) == ctx["att_login"] and str(by_pump[ctx["pumps"][2]].userId) == ctx["att"][1]
        assert float(by_pump[ctx["pumps"][0]].startIndex) == 1000.0
        assert await pumps_affectation.get_current_assignee(db, uuid.UUID(ctx["report"]), uuid.UUID(ctx["pumps"][2])) == uuid.UUID(ctx["att"][1])
        assert sorted(await pumps_affectation.list_pumps_held_by(db, uuid.UUID(ctx["report"]), uuid.UUID(ctx["att"][0]))) == sorted(uuid.UUID(p) for p in ctx["pumps"][:2])
        assert await pumps_affectation.is_pump_assignment_confirmed(db, uuid.UUID(ctx["report"])) is True
        audit = (await db.execute(select(AuditLog).where(AuditLog.action == "zyloLiquid.pumpAssignment.confirm").order_by(AuditLog.createdAt.desc()))).scalars().first()
        assert audit is not None and audit.changes["deviations"] == 1 and audit.changes["pumps"] == 3
        assert (await db.execute(select(ShiftPumpAssignment).where(ShiftPumpAssignment.reportId == uuid.UUID(ctx["report"])))).scalars().all().__len__() == 3
    # Verrou : toute nouvelle saisie ou remise au planning est refusée (changement = B5).
    again = await _put(client, h, ctx["report"], rows, version=1)
    assert again.status_code == 409 and again.json()["error"]["code"] == "assignment_locked"
    reset = await client.post(f"{BASE}/shift-reports/{ctx['report']}/assignments/reset-to-planning", headers=h)
    assert reset.status_code == 409 and reset.json()["error"]["code"] == "assignment_locked"
    # Le GET relit le réel ET le prévu, l'écart reste calculé.
    reread = (await _get(client, h, ctx["report"])).json()
    assert reread["rows"][2]["plannedUserId"] == ctx["att_login"] and reread["rows"][2]["userId"] == ctx["att"][1]


async def test_all_or_nothing_reports_every_cell(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        await db.execute(update(User).where(User.id == uuid.UUID(ctx["att"][2])).values(status="suspended"))
        await db.commit()
    rows = _rows_from((await _get(client, h, ctx["report"])).json())
    rows[0].update(userId=None)  # pump_unassigned
    rows[1].update(userId=ctx["ce"])  # attendant_not_eligible (chef d'équipe)
    rows[2].update(userId=ctx["att"][2])  # attendant_inactive
    res = await _put(client, h, ctx["report"], rows)
    assert res.status_code == 422, res.text
    body = res.json()["error"]
    assert body["code"] == "pump_assignment_invalid" and "rien n'a été enregistré" in body["message"]
    key = lambda i: f"pump:{ctx['pumps'][i]}"  # noqa: E731
    assert _codes(res) == {(key(0), "userId", "pump_unassigned"), (key(1), "userId", "attendant_not_eligible"), (key(2), "userId", "attendant_inactive")}
    messages = {d["rowKey"]: d["message"] for d in body["details"]}
    assert "Choisissez le pompiste de la Pompe N° 1" in messages[key(0)] and "Pompe fermée pour ce tour" in messages[key(0)]
    assert "n'est pas pompiste sur cette station" in messages[key(1)] and "n'a plus accès" in messages[key(2)]
    # Pompe fermée sans observation, pompiste ET fermée, observation trop longue, décideur non chef d'équipe, pompe inconnue/dupliquée/manquante.
    rows = _rows_from((await _get(client, h, ctx["report"])).json())
    rows[0].update(userId=None, closedForShift=True, note=None)
    rows[1].update(closedForShift=True, note="panne")
    rows[2].update(note="x" * 256)
    res = await _put(client, h, ctx["report"], rows, decided_by=ctx["att"][0])
    assert res.status_code == 422
    assert _codes(res) == {
        (key(0), "note", "closed_pump_needs_note"), (key(1), "userId", "closed_pump_has_attendant"),
        (key(2), "note", "note_too_long"), ("decidedBy", "decidedByUserId", "decider_not_eligible"),
    }
    rows = _rows_from((await _get(client, h, ctx["report"])).json())
    rows = rows[:2] + [rows[1], {"pumpId": str(uuid.uuid4()), "userId": ctx["att"][0], "closedForShift": False, "note": None}]
    res = await _put(client, h, ctx["report"], rows)
    assert res.status_code == 422
    codes = {c for _k, _f, c in _codes(res)}
    assert codes == {"pump_row_duplicate", "pump_row_unknown", "pump_row_missing"}
    # Rien n'a été enregistré : toujours un brouillon, version 0, aucun segment.
    view = (await _get(client, h, ctx["report"])).json()
    assert view["confirmed"] is False and view["assignmentVersion"] == 0 and all(r["segmentId"] is None for r in view["rows"])


async def test_closed_pump_with_note_and_one_attendant_many_pumps(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rows = _rows_from((await _get(client, h, ctx["report"])).json())
    rows[1].update(userId=None, closedForShift=True, note="  Compteur en panne  ")
    rows[2].update(userId=ctx["att"][0])  # le même pompiste tient les pompes 1 et 3 (aucun plafond)
    res = await _put(client, h, ctx["report"], rows)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["rows"][1]["closedForShift"] is True and out["rows"][1]["userId"] is None and out["rows"][1]["note"] == "Compteur en panne" and out["rows"][1]["deviation"] == "closed"
    assert out["summary"] == {"pumps": 3, "attendants": 1, "deviations": 1, "unassigned": 0, "closed": 1}
    assert out["byAttendant"][0]["pumpNumbers"] == [1, 3]


async def test_no_planning_means_empty_rows_and_refusal_until_assigned(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, plan=False)
    view = (await _get(client, h, ctx["report"])).json()
    # Rien n'est inventé : sans pompiste prévu, chaque pompe reste vide.
    assert all(r["userId"] is None and r["plannedUserId"] is None and r["deviation"] == "empty" for r in view["rows"]) and view["summary"]["unassigned"] == 3
    res = await _put(client, h, ctx["report"], _rows_from(view))
    assert res.status_code == 422 and {c for _k, _f, c in _codes(res)} == {"pump_unassigned"}
    # Affectation à la main : « non prévu » partout, jamais bloquant.
    rows = _rows_from(view)
    for r in rows:
        r["userId"] = ctx["att"][0]
    res = await _put(client, h, ctx["report"], rows)
    assert res.status_code == 200 and [r["deviation"] for r in res.json()["rows"]] == ["not_planned"] * 3


async def test_optimistic_version_and_tour_not_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rows = _rows_from((await _get(client, h, ctx["report"])).json())
    stale = await _put(client, h, ctx["report"], rows, version=3)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "assignment_changed"
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(ctx["occurrence"])).values(status="closed"))
        await db.commit()
    closed = await _put(client, h, ctx["report"], rows)
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "shift_not_open"
    view = (await _get(client, h, ctx["report"])).json()
    assert view["access"]["locked"] is True and view["access"]["lockedCode"] == "shift_not_open" and view["access"]["canManage"] is False
    reset = await client.post(f"{BASE}/shift-reports/{ctx['report']}/assignments/reset-to-planning", headers=h)
    assert reset.status_code == 409 and reset.json()["error"]["code"] == "shift_not_open"


async def test_reset_to_planning_returns_the_planning_draft(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await client.post(f"{BASE}/shift-reports/{ctx['report']}/assignments/reset-to-planning", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["prefilledFromPlanning"] is True and [r["deviation"] for r in res.json()["rows"]] == ["conforme"] * 3


async def test_permissions_roles_attendant_view_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    org = zylo_liquid_organization
    ctx = await _ctx(client, h, org)
    rt_headers, _rt = await _scoped_user(client, h, org, "zylo_liquid_shift_manager", ctx["station"])
    admin_headers, _adm = await _scoped_user(client, h, org, "zylo_liquid_station_admin", ctx["station"])
    ce_headers, _ce = await _scoped_user(client, h, org, "zylo_liquid_team_lead", ctx["station"])
    cashier_headers, _c = await _scoped_user(client, h, org, "zylo_liquid_cashier", ctx["station"])
    auditor_headers, _a = await _scoped_user(client, h, org, "zylo_liquid_auditor", ctx["station"])
    # Autre station : un RT d'une autre station n'a aucune portée sur ce rapport.
    other = (await _post(client, h, "/stations", {"name": f"Autre {uuid.uuid4().hex[:5]}", "code": f"O{uuid.uuid4().hex[:5]}"}))["id"]
    other_rt, _o = await _scoped_user(client, h, org, "zylo_liquid_shift_manager", other)
    body_rows = _rows_from((await _get(client, h, ctx["report"])).json())
    # Lecture : RT, gérant, CE, caissier, auditeur, pompiste (vue réduite) ; écriture : RT et gérant seulement.
    for headers in (rt_headers, admin_headers, ce_headers, cashier_headers, auditor_headers):
        assert (await _get(client, headers, ctx["report"])).status_code == 200
    for headers in (ce_headers, cashier_headers, auditor_headers, ctx["att_headers"], other_rt):
        denied = await _put(client, headers, ctx["report"], body_rows)
        assert denied.status_code == 403, denied.text
        reset = await client.post(f"{BASE}/shift-reports/{ctx['report']}/assignments/reset-to-planning", headers=headers)
        assert reset.status_code == 403
    assert (await _get(client, other_rt, ctx["report"])).status_code == 403
    ce_view = (await _get(client, ce_headers, ctx["report"])).json()
    assert ce_view["access"]["canManage"] is False and ce_view["restricted"] is False
    # Le pompiste voit uniquement SES pompes : jamais les collègues ni les listes de personnel.
    own = (await _get(client, ctx["att_headers"], ctx["report"])).json()
    assert own["restricted"] is True and [r["pumpNumber"] for r in own["rows"]] == [3] and own["rows"][0]["userId"] == ctx["att_login"]
    assert own["eligibleAttendants"] == [] and own["eligibleTeamLeads"] == [] and own["plannedWithoutPump"] == [] and own["decidedBy"] is None
    # « Mon affectation du tour » : vide tant que rien n'est confirmé, puis SES pompes seulement.
    mine = await client.get(f"{BASE}/my-shift-assignment", headers=ctx["att_headers"])
    assert mine.status_code == 200 and mine.json() == {"assignments": []}
    # Le RT saisit, le gérant aussi (à sa place sur un autre rapport) ; le pompiste libre n'a pas de tour.
    res = await _put(client, rt_headers, ctx["report"], body_rows, decided_by=ctx["ce"])
    assert res.status_code == 200, res.text
    mine = (await client.get(f"{BASE}/my-shift-assignment", headers=ctx["att_headers"])).json()["assignments"]
    assert len(mine) == 1 and mine[0]["reportId"] == ctx["report"] and [p["pumpNumber"] for p in mine[0]["pumps"]] == [3] and mine[0]["shiftName"] == "Journée"
    assert (await client.get(f"{BASE}/my-shift-assignment", headers=ce_headers)).json() == {"assignments": []}
    ctx2 = await _ctx(client, h, org)
    admin2, _ = await _scoped_user(client, h, org, "zylo_liquid_station_admin", ctx2["station"])
    res = await _put(client, admin2, ctx2["report"], _rows_from((await _get(client, h, ctx2["report"])).json()))
    assert res.status_code == 200, res.text
    # Rapport inconnu : 404 (jamais un 403 qui révélerait son existence).
    assert (await _get(client, h, str(uuid.uuid4()))).status_code == 404
