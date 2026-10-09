"""Scénario B3 (ouverture du tour) : passage `planned -> opened` et création du rapport de tour (une ligne par
pompe active et par cuve active) en UNE transaction tout-ou-rien, index d'ouverture = fermeture précédente
calculée par le SERVEUR (décimal exact), premier tour « initial », écart de continuité avec motif, un seul
tour ouvert par station, fenêtre d'ouverture, ouverture hors planning, gardes de désactivation de pompe/cuve et
de changement de cuve, corrections tant que le tour est ouvert, droits et portée station."""

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal


BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


def _now() -> datetime:
    return datetime.now(ZoneInfo("Africa/Douala")).replace(tzinfo=None)


async def _insert_occurrence(station_id: str, shift: dict, starts_at: datetime, ends_at: datetime, rt_user_id: str | None = None, status: str = "planned") -> str:
    from app.modules.zylo_liquid.models import ShiftAssignment, ShiftOccurrence

    async with AsyncSessionLocal() as db:
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station_id), shiftDefinitionId=uuid.UUID(shift["id"]), shiftDate=starts_at.date(), shiftNumber=shift["shiftNumber"], name=shift["name"],
            startTime=f"{starts_at:%H:%M}", endTime=f"{ends_at:%H:%M}", startsAt=starts_at, endsAt=ends_at, status=status,
        )
        db.add(occurrence)
        await db.flush()
        if rt_user_id:
            db.add(ShiftAssignment(occurrenceId=occurrence.id, userId=uuid.UUID(rt_user_id), shiftRole="shift_manager"))
        await db.commit()
        return str(occurrence.id)


async def _close_report(report: dict, pump_closings: dict[str, str] | None = None, tank_stocks: dict[str, str] | None = None) -> None:
    """Simule la fermeture (D1/D2 non codés) : occurrence `closed`, index de fermeture et stock réel écrits en base."""
    from app.modules.zylo_liquid.models import ShiftOccurrence, ShiftReportPumpLine, ShiftReportTankLine

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(report["occurrenceId"])).values(status="closed"))
        for pump_id, value in (pump_closings or {}).items():
            await db.execute(update(ShiftReportPumpLine).where(ShiftReportPumpLine.reportId == uuid.UUID(report["id"]), ShiftReportPumpLine.pumpId == uuid.UUID(pump_id)).values(closingIndex=Decimal(value)))
        for tank_id, value in (tank_stocks or {}).items():
            await db.execute(update(ShiftReportTankLine).where(ShiftReportTankLine.reportId == uuid.UUID(report["id"]), ShiftReportTankLine.tankId == uuid.UUID(tank_id)).values(closingRealStockLiters=Decimal(value)))
        await db.commit()


async def _ctx(client: AsyncClient, h: dict, organization: dict, full_day: bool = False) -> dict:
    """Station avec 2 cuves (Super 20 000 L, Gas-oil 30 000 L), 3 pompes (1-2 sur la cuve 1, 3 sur la cuve 2),
    3 tours contigus et un responsable de tour."""
    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station B3{suffix}", "code": f"O{suffix}"}))["id"]
    super_id = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SU{suffix}"}))["id"]
    gas_id = (await _post(client, h, "/fuel-products", {"name": f"Gasoil{suffix}", "code": f"GO{suffix}"}))["id"]
    tanks = []
    for number, product, capacity in ((1, super_id, 20000), (2, gas_id, 30000)):
        tanks.append((await _post(client, h, "/tanks", {
            "stationId": station, "fuelProductId": product, "tankNumber": number, "displayName": f"Cuve {number}", "capacityLiters": capacity,
            "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        }))["id"])
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "tankId": tanks[0], "pumpNumber": 1}, {"rowNumber": 2, "tankId": tanks[0], "pumpNumber": 2}, {"rowNumber": 3, "tankId": tanks[1], "pumpNumber": 3},
    ]}))["data"]]
    rows = (
        [{"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"}]  # tour de 24 h : couvre toujours « maintenant »
        if full_day else [
            {"rowNumber": 1, "shiftNumber": 1, "name": "Matin", "startTime": "06:00", "endTime": "14:00"},
            {"rowNumber": 2, "shiftNumber": 2, "name": "Soir", "startTime": "14:00", "endTime": "22:00"},
            {"rowNumber": 3, "shiftNumber": 3, "name": "Nuit", "startTime": "22:00", "endTime": "06:00"},
        ]
    )
    shifts = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": rows}))["data"]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "firstName": "RT", "lastName": f"Un{suffix}", "email": f"b3-rt1-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles["zylo_liquid_shift_manager"]},
        {"rowNumber": 2, "firstName": "RT", "lastName": f"Deux{suffix}", "email": f"b3-rt2-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles["zylo_liquid_shift_manager"]},
        {"rowNumber": 3, "firstName": "CE", "lastName": f"Chef{suffix}", "email": f"b3-ce-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles["zylo_liquid_team_lead"]},
    ]}))["data"]
    return {
        "station": station, "tanks": tanks, "pumps": pumps, "shifts": shifts, "roles": roles,
        "rt1": staff[0]["staff"]["userId"], "rt2": staff[1]["staff"]["userId"], "lead": staff[2]["staff"]["userId"],
    }


async def _live_occurrence(ctx: dict, shift_index: int = 0, rt: str | None = None, starts_in: timedelta = timedelta(minutes=-10), length: timedelta = timedelta(hours=8)) -> str:
    start = _now() + starts_in
    return await _insert_occurrence(ctx["station"], ctx["shifts"][shift_index], start, start + length, rt)


async def _context(client, h, station):
    res = await client.get(f"{BASE}/shift-opening/context?stationId={station}", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def _body(context: dict, ctx: dict, occurrence_id: str | None, **over) -> dict:
    """Corps d'ouverture « tout va bien » construit depuis le contexte : index et stocks saisis seulement pour les lignes initiales."""
    pump_lines = []
    for p in context["pumps"]:
        line = {"pumpId": p["pumpId"]}
        if p["origin"] == "initial":
            line["openingIndex"] = f"{1000 + p['pumpNumber']}.50"
        else:
            line["displayedCarriedIndex"] = p["carriedIndex"]
        pump_lines.append(line)
    tank_lines = []
    for t in context["tanks"]:
        line = {"tankId": t["tankId"]}
        if t["origin"] == "initial":
            line["openingStockLiters"] = 5000
        else:
            line["displayedCarriedStockLiters"] = t["carriedStockLiters"]
        tank_lines.append(line)
    body = {"stationId": ctx["station"], "pumpLines": pump_lines, "tankLines": tank_lines}
    if occurrence_id:
        body["occurrenceId"] = occurrence_id
    body.update(over)
    return body


async def _open(client, h, ctx, occurrence_id, **over):
    context = await _context(client, h, ctx["station"])
    return await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, occurrence_id, **over), headers=h)


def _codes(res) -> set:
    return {(d["cell"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


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


# ---------------------------------------------------------------- contexte et premier tour

async def test_first_shift_context_is_all_initial_and_nothing_invented(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, h, ctx["station"])
    assert context["hasPreviousShift"] is False and context["openReport"] is None and context["blockers"] == []
    assert [p["pumpNumber"] for p in context["pumps"]] == [1, 2, 3]
    assert all(p["origin"] == "initial" and p["carriedIndex"] is None and p["lastClosing"] is None for p in context["pumps"])
    assert all(t["origin"] == "initial" and t["carriedStockLiters"] is None for t in context["tanks"])
    row = next(o for o in context["occurrences"] if o["occurrenceId"] == occurrence)
    assert row["canOpen"] is True and row["planned"] is True and row["plannedResponsibleUserId"] == ctx["rt1"]
    # Les tours actifs sans occurrence sont proposés « hors planning », jamais ouvrables par erreur si hors fenêtre.
    assert any(o["occurrenceId"] is None and o["planned"] is False for o in context["occurrences"])
    assert {r["userId"] for r in context["eligibleResponsibles"]} == {ctx["rt1"], ctx["rt2"]}  # ni le chef d'équipe ni le gérant
    assert all("email" not in r for r in context["eligibleResponsibles"])


async def test_open_first_shift_creates_report_with_initial_lines(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    res = await _open(client, h, ctx, occurrence)
    assert res.status_code == 201, res.text
    report = res.json()
    assert report["status"] == "opened" and report["occurrenceId"] == occurrence and report["offPlanning"] is False
    assert report["responsibleUserId"] == ctx["rt1"] and report["plannedResponsibleUserId"] == ctx["rt1"] and report["responsibleDiffersFromPlanned"] is False
    assert [l["pumpNumber"] for l in report["pumpLines"]] == [1, 2, 3]
    first = report["pumpLines"][0]
    assert first["openingSource"] == "initial" and Decimal(first["openingIndex"]) == Decimal("1001.50") and first["carriedIndex"] is None and first["correctable"] is True
    assert first["pumpName"].startswith("Pompe N° 1") and first["fuelProductName"].startswith("Super")  # instantané des libellés
    assert [l["tankNumber"] for l in report["tankLines"]] == [1, 2]
    assert all(l["openingStockSource"] == "initial" and Decimal(l["openingStockLiters"]) == 5000 for l in report["tankLines"])

    current = await client.get(f"{BASE}/shift-reports/current?stationId={ctx['station']}", headers=h)
    assert current.status_code == 200 and current.json()["id"] == report["id"]
    assert (await client.get(f"{BASE}/shift-reports/{report['id']}", headers=h)).json()["id"] == report["id"]
    context = await _context(client, h, ctx["station"])
    assert context["openReport"]["id"] == report["id"]
    row = next(o for o in context["occurrences"] if o["occurrenceId"] == occurrence)
    assert row["status"] == "opened" and row["canOpen"] is False

    # A5 : le tour ouvert est verrouillé dans la grille du planning.
    day = _now().date()
    planning = await client.get(f"{BASE}/shift-planning?stationId={ctx['station']}&from={day - timedelta(days=1)}&to={day + timedelta(days=1)}", headers=h)
    opened = next(o for o in planning.json()["occurrences"] if o["id"] == occurrence)
    assert opened["status"] == "opened" and opened["locked"] is True

    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        actions = set((await db.execute(select(AuditLog.action).where(AuditLog.entityId == uuid.UUID(report["id"])))).scalars().all())
    assert "zyloLiquid.shiftReport.open" in actions


async def test_no_current_report_is_404(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await client.get(f"{BASE}/shift-reports/current?stationId={ctx['station']}", headers=h)
    assert res.status_code == 404 and res.json()["error"]["code"] == "no_open_shift"


# ---------------------------------------------------------------- tout-ou-rien

async def test_opening_is_all_or_nothing_and_reports_every_cell(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, h, ctx["station"])
    body = _body(context, ctx, occurrence)
    body["pumpLines"][0].pop("openingIndex")                       # index manquant
    body["pumpLines"][1]["openingIndex"] = "12.345"                # trop de décimales
    body["pumpLines"].pop()                                        # ligne de pompe absente
    body["tankLines"][0]["openingStockLiters"] = 45000             # dépasse la capacité (20 000)
    body["tankLines"][1].pop("openingStockLiters")                 # stock manquant
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 422, res.text
    error = res.json()["error"]
    assert error["code"] == "shift_opening_invalid"
    p1, p2, p3 = (f"pump:{p}" for p in ctx["pumps"])
    t1, t2 = (f"tank:{t}" for t in ctx["tanks"])
    assert _codes(res) == {
        (p1, "openingIndex", "opening_index_missing"), (p2, "openingIndex", "opening_index_invalid"), (p3, "pumpId", "pump_line_missing"),
        (t1, "openingStockLiters", "stock_exceeds_capacity"), (t2, "openingStockLiters", "stock_missing"),
    }
    messages = {d["code"]: d["message"] for d in error["details"]}
    assert "Saisissez l'index affiché sur la pompe N° 1" in messages["opening_index_missing"]
    assert "capacité de la cuve 1" in messages["stock_exceeds_capacity"]
    # Rien n'a été créé : le tour est toujours planifié, aucun rapport.
    assert (await client.get(f"{BASE}/shift-reports/current?stationId={ctx['station']}", headers=h)).status_code == 404
    assert (await _context(client, h, ctx["station"]))["openReport"] is None
    # Une fois corrigé, l'ouverture réussit (formulaire jamais vidé : mêmes lignes renvoyées).
    assert (await _open(client, h, ctx, occurrence)).status_code == 201


async def test_unknown_and_duplicate_lines_are_reported(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, h, ctx["station"])
    body = _body(context, ctx, occurrence)
    body["pumpLines"].append(dict(body["pumpLines"][0]))
    ghost = str(uuid.uuid4())
    body["pumpLines"].append({"pumpId": ghost, "openingIndex": "1"})
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    codes = {c for _, _, c in _codes(res)}
    assert res.status_code == 422 and {"pump_line_duplicate", "pump_line_unknown"} <= codes


# ---------------------------------------------------------------- un seul tour ouvert

async def test_only_one_open_shift_per_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = await _live_occurrence(ctx, 0, rt=ctx["rt1"])
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    assert (await _open(client, h, ctx, first)).status_code == 201
    other = await _open(client, h, ctx, second)
    assert other.status_code == 409 and other.json()["error"]["code"] == "shift_already_open"
    assert "encore ouvert" in other.json()["error"]["message"]
    again = await _open(client, h, ctx, first)
    assert again.status_code == 409 and again.json()["error"]["code"] == "shift_already_open"
    assert "vient d'être ouvert" in again.json()["error"]["message"]


# ---------------------------------------------------------------- continuité

async def _open_then_close_first(client, h, ctx, closings: dict[str, str], stocks: dict[str, str]) -> dict:
    first = await _live_occurrence(ctx, 0, starts_in=timedelta(hours=-20), length=timedelta(hours=8), rt=ctx["rt1"])
    # Tour terminé il y a plus de 12 h : on l'ouvre via sa fenêtre en le plaçant temporairement dans le présent.
    from app.modules.zylo_liquid.models import ShiftOccurrence

    now = _now()
    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(first)).values(startsAt=now - timedelta(minutes=5), endsAt=now + timedelta(hours=3)))
        await db.commit()
    res = await _open(client, h, ctx, first)
    assert res.status_code == 201, res.text
    report = res.json()
    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(first)).values(startsAt=now - timedelta(hours=9), endsAt=now - timedelta(hours=1)))
        await db.commit()
    await _close_report(report, closings, stocks)
    return report


async def test_opening_index_is_carried_from_previous_closing_in_exact_decimal(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    p1, p2, p3 = ctx["pumps"]
    await _open_then_close_first(client, h, ctx, {p1: "125480.35", p2: "98211.10", p3: "0.07"}, {ctx["tanks"][0]: "14487.00", ctx["tanks"][1]: "20000.50"})
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    context = await _context(client, h, ctx["station"])
    assert context["hasPreviousShift"] is True
    by_number = {p["pumpNumber"]: p for p in context["pumps"]}
    assert Decimal(by_number[1]["carriedIndex"]) == Decimal("125480.35") and by_number[1]["origin"] == "carried"
    assert by_number[1]["lastClosing"]["shiftName"] == "Matin" and by_number[1]["lastClosing"]["daysAgo"] in (0, 1)
    assert Decimal(by_number[3]["carriedIndex"]) == Decimal("0.07")  # pas d'arrondi flottant
    assert all(t["origin"] == "previous_real_stock" for t in context["tanks"]) and Decimal(context["tanks"][0]["carriedStockLiters"]) == Decimal("14487.00")

    res = await _open(client, h, ctx, second)
    assert res.status_code == 201, res.text
    report = res.json()
    lines = {l["pumpNumber"]: l for l in report["pumpLines"]}
    assert lines[1]["openingSource"] == "carried" and Decimal(lines[1]["openingIndex"]) == Decimal("125480.35") and lines[1]["previousLineId"] is not None
    assert lines[1]["correctable"] is False
    assert {l["tankNumber"]: Decimal(l["openingStockLiters"]) for l in report["tankLines"]} == {1: Decimal("14487.00"), 2: Decimal("20000.50")}
    assert all(l["openingStockSource"] == "previous_real_stock" for l in report["tankLines"])


async def test_continuity_break_needs_reason_and_note_and_refuses_hand_typed_index(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    p1, p2, p3 = ctx["pumps"]
    await _open_then_close_first(client, h, ctx, {p1: "125480.35", p2: "98211.10", p3: "500.00"}, {ctx["tanks"][0]: "14487.00", ctx["tanks"][1]: "20000.00"})
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    context = await _context(client, h, ctx["station"])

    # Index tapé à la main sur une cellule reportée : refusé, message qui dit comment corriger.
    body = _body(context, ctx, second)
    body["pumpLines"][0]["openingIndex"] = "125480.00"
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 422 and (f"pump:{p1}", "openingIndex", "opening_index_not_continuous") in _codes(res)
    message = next(d["message"] for d in res.json()["error"]["details"] if d["code"] == "opening_index_not_continuous")
    assert "125 480,00" in message.replace(" ", " ") and "125 480,35" in message.replace(" ", " ") and "L'index sur la pompe est différent" in message

    # Écart déclaré : motif obligatoire, précision d'au moins 10 caractères, index différent du report.
    body = _body(context, ctx, second)
    body["pumpLines"][0].update(openingIndex="125481.00", continuityBreak={"reason": "bogus", "note": "court"})
    body["pumpLines"][1].update(openingIndex="98211.10", continuityBreak={"reason": "other", "note": "Compteur relu avec le pompiste"})
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert {c for _, _, c in _codes(res)} == {"continuity_reason_invalid", "continuity_note_too_short", "continuity_break_same_value"}

    # Un index plus BAS n'est accepté qu'avec « compteur remplacé » ou « remis à zéro ».
    body = _body(context, ctx, second)
    body["pumpLines"][0].update(openingIndex="125000.00", continuityBreak={"reason": "carry_error", "note": "Erreur de report constatée"})
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 422 and (f"pump:{p1}", "openingIndex", "opening_below_previous") in _codes(res)

    body = _body(context, ctx, second)
    body["pumpLines"][0].update(openingIndex="3.00", continuityBreak={"reason": "meter_replaced", "note": "Compteur remplacé ce matin"})
    body["pumpLines"][1].update(openingIndex="98300.00", continuityBreak={"reason": "carry_error", "note": "Litres apparus au dernier tour"})
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 201, res.text
    lines = {l["pumpNumber"]: l for l in res.json()["pumpLines"]}
    assert lines[1]["openingSource"] == "continuity_break" and Decimal(lines[1]["openingIndex"]) == Decimal("3.00") and Decimal(lines[1]["carriedIndex"]) == Decimal("125480.35")
    assert Decimal(lines[1]["gap"]) == Decimal("3.00") - Decimal("125480.35") and lines[1]["continuityBreakReason"] == "meter_replaced"
    assert lines[2]["openingSource"] == "continuity_break" and Decimal(lines[2]["gap"]) == Decimal("88.90")
    assert lines[3]["openingSource"] == "carried"
    assert {w["code"] for w in res.json()["warnings"]} >= {"continuity_break"}


async def test_displayed_carried_value_changed_is_409(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    p1, p2, p3 = ctx["pumps"]
    await _open_then_close_first(client, h, ctx, {p1: "125480.35", p2: "10.00", p3: "20.00"}, {ctx["tanks"][0]: "100.00", ctx["tanks"][1]: "200.00"})
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    context = await _context(client, h, ctx["station"])
    body = _body(context, ctx, second)
    body["pumpLines"][0]["displayedCarriedIndex"] = "125480.30"
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "opening_index_changed"
    assert "125 480,35" in res.json()["error"]["details"][0]["message"].replace(" ", " ")
    assert (await client.get(f"{BASE}/shift-reports/current?stationId={ctx['station']}", headers=h)).status_code == 404


async def test_stock_carried_from_real_stock_cannot_be_overwritten(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    p1, p2, p3 = ctx["pumps"]
    await _open_then_close_first(client, h, ctx, {p1: "1.00", p2: "2.00", p3: "3.00"}, {ctx["tanks"][0]: "14487.00"})  # cuve 2 sans stock réel
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    context = await _context(client, h, ctx["station"])
    assert context["tanks"][0]["origin"] == "previous_real_stock" and context["tanks"][1]["origin"] == "initial"
    body = _body(context, ctx, second)
    body["tankLines"][0].pop("displayedCarriedStockLiters")
    body["tankLines"][0]["openingStockLiters"] = 14000
    body["tankLines"][1].pop("openingStockLiters")
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert {(c, code) for c, _, code in _codes(res)} == {(f"tank:{ctx['tanks'][0]}", "stock_not_continuous"), (f"tank:{ctx['tanks'][1]}", "stock_missing")}


# ---------------------------------------------------------------- fenêtre d'ouverture

async def test_opening_window(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    early = await _live_occurrence(ctx, 0, starts_in=timedelta(hours=3), rt=ctx["rt1"])
    over = await _live_occurrence(ctx, 1, starts_in=timedelta(hours=-9), length=timedelta(hours=8), rt=ctx["rt1"])
    soon = await _live_occurrence(ctx, 2, starts_in=timedelta(minutes=45), rt=ctx["rt1"])
    res = await _open(client, h, ctx, early)
    assert res.status_code == 422 and res.json()["error"]["code"] == "shift_too_early" and "ne peut pas être ouvert avant" in res.json()["error"]["message"]
    res = await _open(client, h, ctx, over)
    assert res.status_code == 422 and res.json()["error"]["code"] == "shift_window_over" and "Prévenez le gérant" in res.json()["error"]["message"]
    context = await _context(client, h, ctx["station"])
    rows = {o["occurrenceId"]: o for o in context["occurrences"] if o["occurrenceId"]}
    if early in rows:  # le contexte ne liste que les tours d'aujourd'hui (et d'hier encore en cours) : « dans 3 h » peut être demain
        assert rows[early]["canOpen"] is False and rows[early]["blockedCode"] == "shift_too_early"
    assert soon not in rows or rows[soon]["canOpen"] is True  # début - 60 min <= maintenant
    assert (await _open(client, h, ctx, soon)).status_code == 201


# ---------------------------------------------------------------- hors planning et responsable

async def test_off_planning_opening_and_responsible_rules(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, full_day=True)
    today = _now()
    shift = ctx["shifts"][0]
    context = await _context(client, h, ctx["station"])
    # Aucune occurrence planifiée : le tour actif est proposé « hors planning », ouvrable (24 h = fenêtre toujours ouverte).
    row = next(o for o in context["occurrences"] if o["shiftDefinitionId"] == shift["id"] and o["date"] == str(today.date()))
    assert row["occurrenceId"] is None and row["planned"] is False and row["canOpen"] is True
    off = {"shiftDefinitionId": shift["id"], "date": str(today.date())}

    # Aucun RT prévu ni choisi : refusé avec un message qui dit quoi faire.
    res = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, None, offPlanning=off), headers=h)
    assert res.status_code == 422 and (("header", "responsibleUserId", "responsible_required") in _codes(res))
    # Un chef d'équipe n'est pas un responsable de tour éligible.
    res = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, None, offPlanning=off, responsibleUserId=ctx["lead"]), headers=h)
    assert res.status_code == 422 and (("header", "responsibleUserId", "responsible_not_eligible") in _codes(res))
    # Date invalide (avant-hier).
    bad = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, None, offPlanning={"shiftDefinitionId": shift["id"], "date": str(today.date() - timedelta(days=3))}, responsibleUserId=ctx["rt1"]), headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "off_planning_date_invalid"

    res = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, None, offPlanning=off, responsibleUserId=ctx["rt2"], responsiblePhone="677000000"), headers=h)
    assert res.status_code == 201, res.text
    report = res.json()
    assert report["offPlanning"] is True and report["plannedResponsibleUserId"] is None and report["responsiblePhone"] == "677000000"
    assert "off_planning" in {w["code"] for w in report["warnings"]}
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        occurrence = await db.get(ShiftOccurrence, uuid.UUID(report["occurrenceId"]))
        assert occurrence.offPlanning is True and occurrence.status == "opened" and str(occurrence.openedByUserId)


async def test_responsible_differs_from_planned_is_signalled(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    res = await _open(client, h, ctx, occurrence, responsibleUserId=ctx["rt2"])
    assert res.status_code == 201, res.text
    report = res.json()
    assert report["responsibleUserId"] == ctx["rt2"] and report["plannedResponsibleUserId"] == ctx["rt1"] and report["responsibleDiffersFromPlanned"] is True
    assert "responsible_differs_from_planned" in {w["code"] for w in report["warnings"]}


# ---------------------------------------------------------------- gardes pompe / cuve

async def test_pump_and_tank_guards_while_shift_is_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    pump = ctx["pumps"][0]
    # Avant l'ouverture : tout est permis (comme en A1).
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"active": False}, headers=h)).status_code == 200
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"active": True}, headers=h)).status_code == 200

    report = (await _open(client, h, ctx, occurrence)).json()
    res = await client.patch(f"{BASE}/pumps/{pump}", json={"active": False}, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "pump_in_open_shift"
    assert "Fermez le tour avant de la désactiver" in res.json()["error"]["message"] and "« Matin » ouvert depuis" in res.json()["error"]["message"]
    res = await client.patch(f"{BASE}/pumps/{pump}", json={"tankId": ctx["tanks"][1]}, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "pump_tank_locked_in_open_shift"
    # Autres modifications (marque) et cuve identique : non bloquées.
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"brand": "Tokheim"}, headers=h)).status_code == 200
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"tankId": ctx["tanks"][0]}, headers=h)).status_code == 200
    res = await client.patch(f"{BASE}/tanks/{ctx['tanks'][0]}", json={"active": False}, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "tank_in_open_shift"
    # Un modèle de tour dont l'occurrence est ouverte ne se désactive pas.
    rows = [{"rowNumber": i + 1, "id": s["id"], "shiftNumber": s["shiftNumber"], "name": s["name"], "startTime": s["startTime"], "endTime": s["endTime"], "active": s["name"] != "Matin"} for i, s in enumerate(ctx["shifts"])]
    res = await client.post(f"{BASE}/shift-definitions/bulk", json={"stationId": ctx["station"], "rows": rows}, headers=h)
    assert res.status_code == 422 and "shift_has_open_occurrence" in {d["code"] for d in res.json()["error"]["details"]}

    # Tour clos : plus aucun blocage.
    await _close_report(report)
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"tankId": ctx["tanks"][1]}, headers=h)).status_code == 200
    assert (await client.patch(f"{BASE}/pumps/{pump}", json={"active": False}, headers=h)).status_code == 200


async def test_inactive_pump_has_no_line_and_is_not_required(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    assert (await client.patch(f"{BASE}/pumps/{ctx['pumps'][1]}", json={"active": False}, headers=h)).status_code == 200
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    res = await _open(client, h, ctx, occurrence)
    assert res.status_code == 201 and [l["pumpNumber"] for l in res.json()["pumpLines"]] == [1, 3]


async def test_station_without_active_pump_or_tank_cannot_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, h, ctx["station"])
    body = _body(context, ctx, occurrence)
    for pump in ctx["pumps"]:
        await client.patch(f"{BASE}/pumps/{pump}", json={"active": False}, headers=h)
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=h)
    assert res.status_code == 422 and res.json()["error"]["code"] == "no_active_pump"
    assert "no_active_pump" in {b["code"] for b in (await _context(client, h, ctx["station"]))["blockers"]}


# ---------------------------------------------------------------- corrections et ajout de pompe

async def test_correct_initial_line_and_add_pump_while_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    report = (await _open(client, h, ctx, occurrence)).json()
    line = report["pumpLines"][0]

    res = await client.patch(f"{BASE}/shift-reports/{report['id']}/pump-lines/{line['id']}/opening", json={"openingIndex": "abc"}, headers=h)
    assert res.status_code == 422 and res.json()["error"]["code"] == "shift_opening_invalid"
    res = await client.patch(f"{BASE}/shift-reports/{report['id']}/pump-lines/{line['id']}/opening", json={"openingIndex": "2222,25"}, headers=h)
    assert res.status_code == 200, res.text
    assert Decimal(next(l for l in res.json()["pumpLines"] if l["id"] == line["id"])["openingIndex"]) == Decimal("2222.25")

    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        entry = (await db.execute(select(AuditLog).where(AuditLog.entityId == uuid.UUID(line["id"])))).scalars().first()
    assert entry is not None and entry.action == "zyloLiquid.shiftReport.correctOpening"

    # Ajout explicite d'une pompe créée après l'ouverture : ligne « initial », jamais automatique.
    new_pump = (await _post(client, h, "/pumps", {"stationId": ctx["station"], "tankId": ctx["tanks"][1], "pumpNumber": 9}))["id"]
    assert len((await client.get(f"{BASE}/shift-reports/{report['id']}", headers=h)).json()["pumpLines"]) == 3
    res = await client.post(f"{BASE}/shift-reports/{report['id']}/pump-lines", json={"pumpId": new_pump}, headers=h)
    assert res.status_code == 422 and ("opening_index_missing" in {d["code"] for d in res.json()["error"]["details"]})
    res = await client.post(f"{BASE}/shift-reports/{report['id']}/pump-lines", json={"pumpId": new_pump, "openingIndex": "77.10"}, headers=h)
    assert res.status_code == 201, res.text
    added = next(l for l in res.json()["pumpLines"] if l["pumpId"] == new_pump)
    assert added["addedDuringShift"] is True and added["openingSource"] == "initial"
    again = await client.post(f"{BASE}/shift-reports/{report['id']}/pump-lines", json={"pumpId": new_pump, "openingIndex": "77.10"}, headers=h)
    assert again.status_code == 422 and "pump_line_duplicate" in {d["code"] for d in again.json()["error"]["details"]}

    # Après la fermeture : aucune correction.
    await _close_report(report)
    res = await client.patch(f"{BASE}/shift-reports/{report['id']}/pump-lines/{line['id']}/opening", json={"openingIndex": "5"}, headers=h)
    assert res.status_code == 409 and res.json()["error"]["code"] == "shift_not_open"


async def test_carried_line_is_not_correctable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    p1, p2, p3 = ctx["pumps"]
    await _open_then_close_first(client, h, ctx, {p1: "10.00", p2: "20.00", p3: "30.00"}, {ctx["tanks"][0]: "1.00", ctx["tanks"][1]: "2.00"})
    second = await _live_occurrence(ctx, 1, rt=ctx["rt2"])
    report = (await _open(client, h, ctx, second)).json()
    line = next(l for l in report["pumpLines"] if l["pumpNumber"] == 1)
    res = await client.patch(f"{BASE}/shift-reports/{report['id']}/pump-lines/{line['id']}/opening", json={"openingIndex": "11.00"}, headers=h)
    assert res.status_code == 422 and res.json()["error"]["code"] == "line_not_correctable"


# ---------------------------------------------------------------- droits et portée

async def test_permissions_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    owner = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, owner, zylo_liquid_organization)
    other = await _ctx(client, owner, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, owner, ctx["station"])
    body = _body(context, ctx, occurrence)

    attendant, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_pump_attendant", ctx["station"])
    assert (await client.get(f"{BASE}/shift-opening/context?stationId={ctx['station']}", headers=attendant)).status_code == 403
    assert (await client.post(f"{BASE}/shift-opening", json=body, headers=attendant)).status_code == 403

    lead, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_team_lead", ctx["station"])
    assert (await client.get(f"{BASE}/shift-opening/context?stationId={ctx['station']}", headers=lead)).status_code == 200
    assert (await client.post(f"{BASE}/shift-opening", json=body, headers=lead)).status_code == 403

    # Portée station : un RT d'une AUTRE station ne voit ni n'ouvre celle-ci.
    rt_other, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_shift_manager", other["station"])
    assert (await client.get(f"{BASE}/shift-opening/context?stationId={ctx['station']}", headers=rt_other)).status_code == 403
    assert (await client.post(f"{BASE}/shift-opening", json=body, headers=rt_other)).status_code == 403

    # Le gérant (administrateur de station) ouvre le tour : openedBy = lui, responsable = celui du planning.
    manager, manager_id = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_station_admin", ctx["station"])
    res = await client.post(f"{BASE}/shift-opening", json=body, headers=manager)
    assert res.status_code == 201, res.text
    assert res.json()["openedByUserId"] == manager_id and res.json()["responsibleUserId"] == ctx["rt1"]
    assert (await client.get(f"{BASE}/shift-reports/current?stationId={ctx['station']}", headers=lead)).status_code == 200
    assert (await client.get(f"{BASE}/shift-reports/{res.json()['id']}", headers=rt_other)).status_code == 403


async def test_shift_manager_role_can_open_and_manager_owns_all_rt_permissions(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    owner = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, owner, zylo_liquid_organization)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, owner, ctx["station"])
    rt, rt_id = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    res = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, occurrence), headers=rt)
    assert res.status_code == 201, res.text

    from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES

    roles = {code: set(perms) for code, _name, perms in DEFAULT_ROLES}
    assert roles["zylo_liquid_shift_manager"] <= roles["zylo_liquid_station_admin"]
    assert {"zyloLiquid.shiftReport.read", "zyloLiquid.shiftReport.manage"} <= roles["zylo_liquid_shift_manager"]
    assert "zyloLiquid.shiftReport.read" in roles["zylo_liquid_team_lead"] and "zyloLiquid.shiftReport.manage" not in roles["zylo_liquid_team_lead"]
    assert not ({"zyloLiquid.shiftReport.read", "zyloLiquid.shiftReport.manage"} & roles["zylo_liquid_pump_attendant"])
