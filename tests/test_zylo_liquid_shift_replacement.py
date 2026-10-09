"""Scénario B5 (remplacement d'un pompiste absent et pauses en cours de tour) : chronologie de
segments par pompe (le prévu et l'affectation de départ ne sont jamais écrasés), pause sans
remplaçant refusée sauf « pompe fermée », éligibilité du remplaçant (ni RT, ni gérant, ni en pause,
ni parti), index au changement facultatif (litres seulement s'il est saisi), heure (futur, avant
l'ouverture, avant le segment en cours, ordre chronologique), enregistrement tout-ou-rien avec
erreurs par cellule `shift_replacement_invalid`, verrou optimiste, annulation du dernier mouvement
sans suppression, audit, événements de domaine, fonctions publiques pour D3 (répartition manuelle
et tracée de l'écart de caisse) et droits (le chef d'équipe lit, ne saisit pas) / portée station.

Le tour ouvert, son rapport, ses lignes de pompe et l'affectation de départ sont posés directement
en base (modèles B3/B4) : B5 est ainsi testé indépendamment des endpoints d'ouverture et de confirmation."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, update

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal
from app.shared import events
from app.modules.zylo_liquid.exploitation import caisse_collecte as caisse_collecte
from app.modules.zylo_liquid.exploitation import pumps_mouvements as shifts_mouvements

BASE = "/api/v1/zylo-liquid"
OPENING_INDEX = Decimal("1000.00")


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _ctx(client: AsyncClient, h: dict, organization: dict, confirm: bool = True, opened_ago: timedelta = timedelta(hours=3)) -> dict:
    """Station + 3 pompes + personnel (1 RT, 1 CE, 4 pompistes) + tour OUVERT depuis `opened_ago` avec affectation de
    départ confirmée : att[0] tient les pompes 1 et 2, att[1] la pompe 3, att[2] et att[3] sont libres (remplaçants)."""
    from app.modules.zylo_liquid.models import (
        ShiftOccurrence,
        ShiftPumpAssignment,
        ShiftPumpAssignmentSheet,
        ShiftReport,
        ShiftReportPumpLine,
    )

    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station B5{suffix}", "code": f"F{suffix}"}))["id"]
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
        return {"rowNumber": n, "firstName": f"P{n}", "lastName": f"N{suffix}", "email": f"b5-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    staff_rows = [row(1, "zylo_liquid_shift_manager"), row(2, "zylo_liquid_team_lead")] + [row(i, "zylo_liquid_pump_attendant") for i in (3, 4, 5, 6)]
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]
    ids = [s["staff"]["userId"] for s in staff]
    rt, ce, att = ids[0], ids[1], ids[2:]

    now = datetime.now(timezone.utc)
    opened_at = now - opened_ago
    holders = [att[0], att[0], att[1]]
    async with AsyncSessionLocal() as db:
        local = opened_at.astimezone().replace(tzinfo=None)
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station), shiftDefinitionId=uuid.UUID(shift["id"]), shiftDate=date.today(), shiftNumber=1, name="Journée",
            startTime="00:00", endTime="00:00", startsAt=local, endsAt=local + timedelta(days=1), status="opened", openedAt=opened_at, openedByUserId=uuid.UUID(rt),
        )
        db.add(occurrence)
        await db.flush()
        report = ShiftReport(
            stationId=uuid.UUID(station), occurrenceId=occurrence.id, shiftDate=occurrence.shiftDate, shiftNumber=1, shiftName="Journée", startTime="00:00", endTime="00:00",
            responsibleUserId=uuid.UUID(rt), openedByUserId=uuid.UUID(rt), openedAt=opened_at,
        )
        db.add(report)
        await db.flush()
        if confirm:
            db.add(ShiftPumpAssignmentSheet(reportId=report.id, stationId=uuid.UUID(station), version=1, confirmedAt=opened_at, confirmedByUserId=uuid.UUID(rt)))
        for number, (pump_id, holder) in enumerate(zip(pumps, holders), start=1):
            line = ShiftReportPumpLine(
                reportId=report.id, pumpId=uuid.UUID(pump_id), pumpNumber=number, pumpName=f"Pompe {number}", tankId=uuid.UUID(tank),
                fuelProductName="Super", openingIndex=OPENING_INDEX, openingSource="initial",
            )
            db.add(line)
            await db.flush()
            if confirm:
                db.add(ShiftPumpAssignment(
                    reportId=report.id, pumpLineId=line.id, pumpId=uuid.UUID(pump_id), userId=uuid.UUID(holder), plannedUserId=uuid.UUID(holder),
                    startsAt=opened_at, kind="start", startIndex=OPENING_INDEX, recordedAt=opened_at, recordedByUserId=uuid.UUID(rt),
                ))
        await db.commit()
        report_id, occurrence_id = str(report.id), str(occurrence.id)
    return {
        "station": station, "pumps": pumps, "report": report_id, "occurrence": occurrence_id, "opened_at": opened_at,
        "rt": rt, "ce": ce, "att": att, "roles": roles, "suffix": suffix,
    }


async def _state(client, h, ctx) -> dict:
    res = await client.get(f"{BASE}/shift-reports/{ctx['report']}/movements", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


async def _move(client, h, ctx, **body):
    return await client.post(f"{BASE}/shift-reports/{ctx['report']}/movements", json=body, headers=h)


def _pump(state: dict, number: int) -> dict:
    return next(p for p in state["pumps"] if p["pumpNumber"] == number)


def _codes(res) -> set:
    return {(d["rowKey"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def _break(client, h, ctx, subject, cover, pumps=(0, 1), **extra):
    rows = [{"pumpId": ctx["pumps"][i], "coverUserId": cover} for i in pumps]
    return await _move(client, h, ctx, kind="break_start", subjectUserId=subject, rows=rows, **extra)


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


async def _db_segments(report_id: str) -> list:
    from app.modules.zylo_liquid.models import ShiftPumpAssignment

    async with AsyncSessionLocal() as db:
        return list((await db.execute(select(ShiftPumpAssignment).where(ShiftPumpAssignment.reportId == uuid.UUID(report_id)).order_by(ShiftPumpAssignment.startsAt, ShiftPumpAssignment.createdAt))).scalars().all())


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------


async def test_state_before_confirmation_is_locked_and_empty(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, confirm=False)
    state = await _state(client, h, ctx)
    assert state["assignmentVersion"] == 0 and state["access"]["locked"] is True and state["access"]["lockedCode"] == "assignment_not_confirmed"
    assert state["access"]["canManage"] is False and state["movements"] == [] and state["openBreaks"] == []
    res = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2])
    assert res.status_code == 409 and res.json()["error"]["code"] == "assignment_not_confirmed"
    assert "Confirmez d'abord l'affectation de départ" in res.json()["error"]["message"]


async def test_state_lists_holders_and_eligible_covers_without_email(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    state = await _state(client, h, ctx)
    assert state["assignmentVersion"] == 1 and state["access"]["canManage"] is True and state["access"]["locked"] is False
    assert [p["pumpNumber"] for p in state["pumps"]] == [1, 2, 3]
    assert _pump(state, 1)["holder"]["userId"] == ctx["att"][0] and _pump(state, 3)["holder"]["userId"] == ctx["att"][1]
    assert _pump(state, 1)["kind"] == "start" and _pump(state, 1)["closed"] is False and len(_pump(state, 1)["timeline"]) == 1
    assert {h_["userId"]: len(h_["pumpIds"]) for h_ in state["holders"]} == {ctx["att"][0]: 2, ctx["att"][1]: 1}
    covers = {c["userId"]: c for c in state["eligibleCovers"]}
    # Pompistes actifs ET chef d'équipe (marqué) ; jamais le RT ; jamais l'e-mail.
    assert set(covers) == {*ctx["att"], ctx["ce"]} and ctx["rt"] not in covers
    assert covers[ctx["ce"]]["isTeamLead"] is True and covers[ctx["att"][0]]["heldPumpCount"] == 2 and covers[ctx["att"][2]]["heldPumpCount"] == 0
    assert all("email" not in c for c in state["eligibleCovers"])


# ---------------------------------------------------------------------------
# Pause et retour de pause
# ---------------------------------------------------------------------------


async def test_break_then_return_keeps_a_continuous_chronology_and_never_overwrites_the_start(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("ShiftPumpHolderChanged", handler)
    try:
        res = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2], note="Pause déjeuner")
    finally:
        events._handlers["ShiftPumpHolderChanged"].remove(handler)
    assert res.status_code == 201, res.text
    state = res.json()
    assert state["assignmentVersion"] == 2
    p1 = _pump(state, 1)
    assert p1["holder"]["userId"] == ctx["att"][2] and p1["kind"] == "break_cover" and p1["coversUser"]["userId"] == ctx["att"][0]
    assert _pump(state, 3)["holder"]["userId"] == ctx["att"][1]  # pompe non touchée
    # Le segment de départ est conservé (prévu = réel de départ), simplement fermé à l'heure exacte du changement.
    start, cover = p1["timeline"]
    assert start["kind"] == "start" and start["holder"]["userId"] == ctx["att"][0] and start["plannedUserId"] == ctx["att"][0]
    assert start["endsAt"] == cover["startsAt"] and cover["endsAt"] is None and cover["plannedUserId"] == ctx["att"][0]
    # Pause en cours : durée écoulée seulement.
    [brk] = state["openBreaks"]
    assert brk["subject"]["userId"] == ctx["att"][0] and [p["pumpNumber"] for p in brk["pumps"]] == [1, 2] and brk["elapsedMinutes"] >= 0
    assert brk["pumps"][0]["currentHolder"]["userId"] == ctx["att"][2]
    [mv] = state["movements"]
    assert mv["kind"] == "break_start" and mv["reason"] is None and mv["note"] == "Pause déjeuner" and mv["canCancel"] is True and len(mv["pumps"]) == 2
    assert len(received) == 1 and received[0]["kind"] == "break_start" and len(received[0]["changes"]) == 2

    # Retour de pause : les deux pompes sont rendues, la pause est terminée.
    back = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], rows=[{"pumpId": ctx["pumps"][0]}, {"pumpId": ctx["pumps"][1]}], assignmentVersion=2)
    assert back.status_code == 201, back.text
    final = back.json()
    assert final["openBreaks"] == [] and final["assignmentVersion"] == 3
    timeline = _pump(final, 1)["timeline"]
    assert [s["kind"] for s in timeline] == ["start", "break_cover", "break_return"]
    assert [s["holder"]["userId"] for s in timeline] == [ctx["att"][0], ctx["att"][2], ctx["att"][0]]
    # Aucun trou, aucun chevauchement : chaque fin = début du suivant ; un seul segment en cours.
    assert all(timeline[i]["endsAt"] == timeline[i + 1]["startsAt"] for i in range(2)) and timeline[-1]["endsAt"] is None
    assert final["movements"][0]["kind"] == "break_end" and final["movements"][0]["breakStartMovementId"] == brk["movementId"]
    # Le journal est tracé (audit) pour chaque mouvement.
    async with AsyncSessionLocal() as db:
        actions = (await db.execute(select(AuditLog.action).where(AuditLog.organizationId == uuid.UUID(zylo_liquid_organization["id"]), AuditLog.action.like("zyloLiquid.shiftReplacement.%")))).scalars().all()
    assert actions.count("zyloLiquid.shiftReplacement.record") >= 2


async def test_break_without_cover_is_refused_with_cell_errors_and_nothing_written(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    # Pompe 1 couverte, pompe 2 sans remplaçant : TOUT est refusé, rien n'est enregistré.
    res = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], rows=[
        {"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][2]}, {"pumpId": ctx["pumps"][1]},
    ])
    assert res.status_code == 422 and res.json()["error"]["code"] == "shift_replacement_invalid"
    assert (f"pump:{ctx['pumps'][1]}", "coverUserId", "break_without_cover") in _codes(res)
    message = next(d["message"] for d in res.json()["error"]["details"] if d["code"] == "break_without_cover")
    assert "Aucune pompe ne reste sans pompiste pendant une pause" in message and "Pompe N° 2" in message and "pompe fermée pendant la pause" in message
    # Ligne absente alors que la pompe est tenue par le pompiste en pause : même refus.
    missing = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], rows=[{"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][2]}])
    assert missing.status_code == 422 and (f"pump:{ctx['pumps'][1]}", "pumpId", "break_without_cover") in _codes(missing)
    state = await _state(client, h, ctx)
    assert state["movements"] == [] and state["assignmentVersion"] == 1 and _pump(state, 1)["holder"]["userId"] == ctx["att"][0]
    assert len(await _db_segments(ctx["report"])) == 3


async def test_closed_pump_during_break_needs_a_note_and_is_listed_as_unattended(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rows = [{"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][2]}, {"pumpId": ctx["pumps"][1], "closedForBreak": True}]
    no_note = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], rows=rows)
    assert no_note.status_code == 422 and (f"pump:{ctx['pumps'][1]}", "note", "note_required") in _codes(no_note)
    both = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], note="x", rows=[
        {"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][2]}, {"pumpId": ctx["pumps"][1], "coverUserId": ctx["att"][3], "closedForBreak": True},
    ])
    assert both.status_code == 422 and (f"pump:{ctx['pumps'][1]}", "coverUserId", "cover_and_closed") in _codes(both)

    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("PumpLeftUnattended", handler)
    try:
        ok = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], note="Pas de remplaçant disponible", rows=rows)
    finally:
        events._handlers["PumpLeftUnattended"].remove(handler)
    assert ok.status_code == 201, ok.text
    state = ok.json()
    p2 = _pump(state, 2)
    assert p2["holder"] is None and p2["closed"] is True and p2["closedDuringShift"] is True
    [unattended] = state["unattendedPumps"]
    assert unattended["pumpNumber"] == 2 and unattended["note"] == "Pas de remplaçant disponible"
    assert [e["pumpId"] for e in received] == [uuid.UUID(ctx["pumps"][1])]
    # Le retour de pause rend la pompe fermée à son pompiste.
    brk = state["openBreaks"][0]
    assert [p["closed"] for p in brk["pumps"]] == [False, True]
    back = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], rows=[{"pumpId": ctx["pumps"][0]}, {"pumpId": ctx["pumps"][1]}])
    assert back.status_code == 201 and back.json()["unattendedPumps"] == [] and _pump(back.json(), 2)["holder"]["userId"] == ctx["att"][0]


async def test_cover_eligibility_rules(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    pump_key = f"pump:{ctx['pumps'][0]}"
    # Le RT n'est ni pompiste ni chef d'équipe : refusé, avec la façon de corriger.
    rt = await _break(client, h, ctx, ctx["att"][0], ctx["rt"], pumps=(0,))
    assert rt.status_code == 422 and (pump_key, "coverUserId", "cover_not_eligible") in _codes(rt)
    assert "n'est ni pompiste ni chef d'équipe sur cette station" in next(d["message"] for d in rt.json()["error"]["details"] if d["code"] == "cover_not_eligible")
    # Le remplaçant ne peut pas être le remplacé.
    same = await _break(client, h, ctx, ctx["att"][1], ctx["att"][1], pumps=(2,))
    assert same.status_code == 422 and (f"pump:{ctx['pumps'][2]}", "coverUserId", "cover_same_as_subject") in _codes(same)
    # Personne inconnue de la station.
    ghost = await _break(client, h, ctx, ctx["att"][0], str(uuid.uuid4()), pumps=(0,))
    assert ghost.status_code == 422 and (pump_key, "coverUserId", "cover_not_eligible") in _codes(ghost)
    # Le chef d'équipe PEUT remplacer, le segment est marqué « chef d'équipe » (PC-52).
    lead = await _break(client, h, ctx, ctx["att"][1], ctx["ce"], pumps=(2,))
    assert lead.status_code == 201, lead.text
    p3 = _pump(lead.json(), 3)
    assert p3["holder"]["userId"] == ctx["ce"] and p3["holder"]["isTeamLead"] is True and p3["timeline"][-1]["holder"]["isTeamLead"] is True
    # Un pompiste en pause ne peut pas être remplaçant : message avec l'heure de début de pause.
    paused = await _break(client, h, ctx, ctx["att"][0], ctx["att"][1], pumps=(0,))
    assert paused.status_code == 422 and (pump_key, "coverUserId", "cover_unavailable") in _codes(paused)
    assert "est en pause depuis" in next(d["message"] for d in paused.json()["error"]["details"] if d["code"] == "cover_unavailable")
    # Le pompiste concerné doit tenir une pompe.
    idle = await _break(client, h, ctx, ctx["att"][2], ctx["att"][3], pumps=(0,))
    assert idle.status_code == 422 and ("movement", "subjectUserId", "subject_not_holder") in _codes(idle)
    assert "ne tient aucune pompe en ce moment" in next(d["message"] for d in idle.json()["error"]["details"] if d["code"] == "subject_not_holder")


async def test_remplacant_en_pause_fait_une_pause_et_retour_apres_changement_de_titulaire(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2])  # att2 couvre les pompes 1 et 2
    assert first.status_code == 201
    brk = first.json()["openBreaks"][0]
    # Le remplaçant att2 fait lui-même une pause : ses pompes (dont celles qu'il couvre) obtiennent un nouveau remplaçant.
    second = await _break(client, h, ctx, ctx["att"][2], ctx["att"][3])
    assert second.status_code == 201, second.text
    assert _pump(second.json(), 1)["holder"]["userId"] == ctx["att"][3]
    # Retour de la première pause : la pompe a changé de titulaire entre-temps ; on rend seulement la pompe 1 (retour partiel autorisé).
    back = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], rows=[{"pumpId": ctx["pumps"][0]}])
    assert back.status_code == 201, back.text
    state = back.json()
    assert _pump(state, 1)["holder"]["userId"] == ctx["att"][0] and _pump(state, 2)["holder"]["userId"] == ctx["att"][3]
    assert [b["subject"]["userId"] for b in state["openBreaks"]] == [ctx["att"][2]]
    # Pause déjà terminée : impossible de la terminer deux fois ; pompe étrangère à la pause refusée.
    again = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], rows=[{"pumpId": ctx["pumps"][0]}])
    assert again.status_code == 422 and ("movement", "breakStartMovementId", "break_not_open") in _codes(again)
    third = await _move(client, h, ctx, kind="break_end", breakStartMovementId=state["openBreaks"][0]["movementId"], rows=[{"pumpId": ctx["pumps"][2]}])
    assert third.status_code == 422 and (f"pump:{ctx['pumps'][2]}", "pumpId", "pump_not_in_break") in _codes(third)


# ---------------------------------------------------------------------------
# Remplacement et réaffectation
# ---------------------------------------------------------------------------


async def test_replacement_requires_a_reason_and_a_left_attendant_can_no_longer_cover(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rows = [{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][2]}]
    no_reason = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], rows=rows)
    assert no_reason.status_code == 422 and ("movement", "reason", "reason_required") in _codes(no_reason)
    assert "Choisissez le motif du remplacement" in no_reason.json()["error"]["details"][0]["message"]
    wrong_reason = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="rebalancing", rows=rows)
    assert wrong_reason.status_code == 422 and ("movement", "reason", "reason_invalid") in _codes(wrong_reason)
    other = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="other", rows=rows)
    assert other.status_code == 422 and ("movement", "note", "note_required") in _codes(other)

    ok = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="left_during_shift", note="Malaise", rows=rows)
    assert ok.status_code == 201, ok.text
    state = ok.json()
    p3 = _pump(state, 3)
    assert p3["holder"]["userId"] == ctx["att"][2] and p3["kind"] == "replacement" and p3["coversUser"]["userId"] == ctx["att"][1]
    assert p3["timeline"][0]["holder"]["userId"] == ctx["att"][1] and p3["timeline"][0]["kind"] == "start"
    assert state["movements"][0]["reason"] == "left_during_shift"
    # Parti en cours de tour : ni remplaçant ni titulaire dans ce tour, et plus aucune pompe à remplacer.
    covers = {c["userId"]: c for c in state["eligibleCovers"]}
    assert covers[ctx["att"][1]]["unavailable"] == "left"
    cannot = await _break(client, h, ctx, ctx["att"][0], ctx["att"][1], pumps=(0, 1))
    assert cannot.status_code == 422 and "a quitté le tour" in next(d["message"] for d in cannot.json()["error"]["details"] if d["code"] == "cover_unavailable")
    gone = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="absence_unforeseen", rows=rows)
    assert gone.status_code == 422 and ("movement", "subjectUserId", "subject_not_holder") in _codes(gone)


async def test_reassignment_late_arrival_moves_a_pump_to_the_arriving_attendant(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][3], reason="late_arrival", rows=[{"pumpId": ctx["pumps"][2]}])
    assert res.status_code == 201, res.text
    state = res.json()
    p3 = _pump(state, 3)
    assert p3["holder"]["userId"] == ctx["att"][3] and p3["kind"] == "reassignment" and p3["coversUser"] is None
    assert [s["holder"]["userId"] for s in p3["timeline"]] == [ctx["att"][1], ctx["att"][3]]
    assert state["movements"][0]["subject"]["userId"] == ctx["att"][3] and state["movements"][0]["reason"] == "late_arrival"
    # Déjà titulaire : refusé ; un remplaçant de ligne différent du nouveau titulaire : refusé ; pas de pompe fermée.
    again = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][3], reason="rebalancing", rows=[{"pumpId": ctx["pumps"][2]}])
    assert again.status_code == 422 and (f"pump:{ctx['pumps'][2]}", "pumpId", "pump_already_held") in _codes(again)
    mismatch = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][2], reason="rebalancing", rows=[{"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][3], "closedForBreak": True}])
    assert mismatch.status_code == 422
    assert {c for _k, _f, c in _codes(mismatch)} == {"reassign_holder_mismatch", "closed_not_allowed"}
    # Ne rien déplacer sans pompe choisie.
    empty = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][2], reason="rebalancing", rows=[])
    assert empty.status_code == 422 and ("movement", "rows", "rows_required") in _codes(empty)


# ---------------------------------------------------------------------------
# Heure et index au changement
# ---------------------------------------------------------------------------


async def test_time_rules(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    now = datetime.now(timezone.utc)
    future = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2], occurredAt=(now + timedelta(hours=1)).isoformat())
    assert future.status_code == 422 and ("movement", "occurredAt", "time_in_future") in _codes(future)
    assert "est dans le futur" in next(d["message"] for d in future.json()["error"]["details"] if d["code"] == "time_in_future")
    before_open = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2], occurredAt=(ctx["opened_at"] - timedelta(minutes=30)).isoformat())
    assert before_open.status_code == 422
    assert {c for _k, _f, c in _codes(before_open)} >= {"time_before_segment"}
    # Saisie après coup autorisée dans la limite du segment en cours : il y a une heure.
    past = (now - timedelta(hours=1)).isoformat()
    ok = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2], occurredAt=past)
    assert ok.status_code == 201, ok.text
    mv = ok.json()["movements"][0]
    assert mv["occurredAt"][:16] == (now - timedelta(hours=1)).astimezone(timezone.utc).isoformat()[:16] and mv["recordedAt"] > mv["occurredAt"]
    # Avant le début du segment en cours de la pompe (la couverture a commencé il y a 1 h) : refusé, message par pompe.
    earlier = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][2], reason="absence_unforeseen", occurredAt=(now - timedelta(hours=2)).isoformat(), rows=[
        {"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][3]}, {"pumpId": ctx["pumps"][1], "coverUserId": ctx["att"][3]},
    ])
    assert earlier.status_code == 422 and (f"pump:{ctx['pumps'][0]}", "occurredAt", "time_before_segment") in _codes(earlier)
    assert "l'heure du changement ne peut pas être avant" in next(d["message"] for d in earlier.json()["error"]["details"] if d["code"] == "time_before_segment")
    # Retour de pause avant le début de la pause : refusé.
    brk = ok.json()["openBreaks"][0]
    early_back = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], occurredAt=(now - timedelta(hours=1, minutes=10)).isoformat(), rows=[{"pumpId": ctx["pumps"][0]}])
    assert early_back.status_code == 422 and ("movement", "occurredAt", "time_before_break") in _codes(early_back)
    # Ordre chronologique global : un mouvement sur une AUTRE pompe daté avant le précédent est refusé.
    out_of_order = await _break(client, h, ctx, ctx["att"][1], ctx["att"][3], pumps=(2,), occurredAt=(now - timedelta(hours=2)).isoformat())
    assert out_of_order.status_code == 422 and ("movement", "occurredAt", "time_before_previous_movement") in _codes(out_of_order)


async def test_change_index_is_optional_validated_and_drives_liters(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid import service

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    low = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][1], rows=[{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][2], "changeIndex": "900.00"}])
    assert low.status_code == 422 and (f"pump:{ctx['pumps'][2]}", "changeIndex", "change_index_invalid") in _codes(low)
    assert "inférieur à l'index d'ouverture de la pompe (1 000,00)" in next(d["message"] for d in low.json()["error"]["details"] if d["code"] == "change_index_invalid")
    decimals = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][1], rows=[{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][2], "changeIndex": "1010.123"}])
    assert decimals.status_code == 422 and (f"pump:{ctx['pumps'][2]}", "changeIndex", "change_index_invalid") in _codes(decimals)
    # Sans index : la chronologie existe mais AUCUN litre n'est réparti (jamais de donnée inventée).
    no_index = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][1], rows=[{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][2]}])
    assert no_index.status_code == 201
    assert [s["liters"] for s in _pump(no_index.json(), 3)["timeline"]] == [None, None]
    brk = no_index.json()["openBreaks"][0]
    # Retour AVEC index : la couverture reçoit des litres seulement si l'index de DÉBUT du segment suivant ET le sien sont connus.
    back = await _move(client, h, ctx, kind="break_end", breakStartMovementId=brk["movementId"], rows=[{"pumpId": ctx["pumps"][2], "changeIndex": "1100.50"}])
    assert back.status_code == 201, back.text
    timeline = _pump(back.json(), 3)["timeline"]
    assert [s["startIndex"] for s in timeline] == ["1000.00", None, "1100.50"] and [s["liters"] for s in timeline] == [None, None, None]
    # Index inférieur au dernier index connu : refusé.
    lower = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][3], reason="rebalancing", rows=[{"pumpId": ctx["pumps"][2], "changeIndex": "1050.00"}])
    assert lower.status_code == 422 and "dernier index connu" in next(d["message"] for d in lower.json()["error"]["details"] if d["code"] == "change_index_invalid")
    # Réaffectation avec index, puis index de fermeture connu (D1) : litres par segment aux deux bouts.
    moved = await _move(client, h, ctx, kind="reassignment", subjectUserId=ctx["att"][3], reason="rebalancing", rows=[{"pumpId": ctx["pumps"][2], "changeIndex": "1200.00"}])
    assert moved.status_code == 201, moved.text
    from app.modules.zylo_liquid.models import ShiftReportPumpLine

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftReportPumpLine).where(ShiftReportPumpLine.reportId == uuid.UUID(ctx["report"]), ShiftReportPumpLine.pumpId == uuid.UUID(ctx["pumps"][2])).values(closingIndex=Decimal("1350.00")))
        await db.commit()
        rows = await shifts_mouvements.get_pump_segments_with_indexes(db, uuid.UUID(ctx["report"]), uuid.UUID(ctx["pumps"][2]))
    assert [r["liters"] for r in rows] == [None, None, Decimal("99.50"), Decimal("150.00")]
    # Au-delà de l'index de fermeture : refusé.
    state = await _state(client, h, ctx)
    assert [s["liters"] for s in _pump(state, 3)["timeline"]] == [None, None, "99.50", "150.00"]


# ---------------------------------------------------------------------------
# Concurrence, tour fermé, annulation
# ---------------------------------------------------------------------------


async def test_optimistic_lock_and_closed_shift(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = await _break(client, h, ctx, ctx["att"][0], ctx["att"][2], assignmentVersion=1)
    assert first.status_code == 201
    # Deuxième saisie préparée sur la version 1 (périmée) : 409, saisie à refaire, rien d'écrit.
    stale = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="absence_unforeseen", assignmentVersion=1, rows=[{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][3]}])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "movement_conflict"
    assert "Rechargez puis recommencez" in stale.json()["error"]["message"]
    assert (await _state(client, h, ctx))["assignmentVersion"] == 2
    # Tour fermé : lecture seule définitive.
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(ctx["occurrence"])).values(status="closed"))
        await db.commit()
    closed = await _move(client, h, ctx, kind="replacement", subjectUserId=ctx["att"][1], reason="absence_unforeseen", rows=[{"pumpId": ctx["pumps"][2], "coverUserId": ctx["att"][3]}])
    assert closed.status_code == 409 and closed.json()["error"]["code"] == "shift_not_open"
    state = await _state(client, h, ctx)
    assert state["access"]["locked"] is True and state["access"]["lockedCode"] == "shift_not_open" and state["movements"][0]["canCancel"] is False


async def test_cancel_last_movement_restores_state_without_deleting_anything(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = (await _break(client, h, ctx, ctx["att"][0], ctx["att"][2])).json()
    first_id = first["movements"][0]["id"]
    second = await _move(client, h, ctx, kind="break_end", breakStartMovementId=first["openBreaks"][0]["movementId"], rows=[{"pumpId": ctx["pumps"][0]}, {"pumpId": ctx["pumps"][1]}])
    assert second.status_code == 201
    second_id = second.json()["movements"][0]["id"]
    assert [m["canCancel"] for m in second.json()["movements"]] == [True, False]
    cancel_url = lambda mid: f"{BASE}/shift-reports/{ctx['report']}/movements/{mid}/cancel"
    # Seul le dernier mouvement peut être annulé.
    not_last = await client.post(cancel_url(first_id), json={"reason": "Erreur de saisie"}, headers=h)
    assert not_last.status_code == 422 and not_last.json()["error"]["code"] == "cancel_not_last"
    assert "Seul le dernier mouvement peut être annulé. Annulez d'abord celui de" in not_last.json()["error"]["message"]
    # Motif obligatoire.
    blank = await client.post(cancel_url(second_id), json={"reason": "   "}, headers=h)
    assert blank.status_code == 422 and ("movement", "reason", "cancel_reason_required") in _codes(blank)
    assert (await client.post(cancel_url(second_id), json={}, headers=h)).status_code == 422

    # Annuler le retour de pause rétablit la pause en cours (couvertures rouvertes).
    undone = await client.post(cancel_url(second_id), json={"reason": "Retour saisi par erreur"}, headers=h)
    assert undone.status_code == 200, undone.text
    state = undone.json()
    assert _pump(state, 1)["holder"]["userId"] == ctx["att"][2] and _pump(state, 1)["kind"] == "break_cover"
    assert [b["subject"]["userId"] for b in state["openBreaks"]] == [ctx["att"][0]] and state["assignmentVersion"] == 4
    assert [s["kind"] for s in _pump(state, 1)["timeline"]] == ["start", "break_cover"]  # le segment neutralisé sort de la chronologie
    cancelled = next(m for m in state["movements"] if m["id"] == second_id)
    assert cancelled["cancelled"] is True and cancelled["cancelReason"] == "Retour saisi par erreur" and cancelled["cancelledBy"]["userId"] is not None and cancelled["canCancel"] is False
    assert next(m for m in state["movements"] if m["id"] == first_id)["canCancel"] is True
    assert (await client.post(cancel_url(second_id), json={"reason": "encore"}, headers=h)).json()["error"]["code"] == "movement_already_cancelled"
    # Rien n'est supprimé en base : 3 segments de départ + 2 couvertures + 2 retours (neutralisés).
    segments = await _db_segments(ctx["report"])
    assert len(segments) == 7 and sum(1 for s in segments if s.cancelledAt is not None) == 2 and all(s.endsAt == s.startsAt for s in segments if s.cancelledAt is not None)
    # Puis annuler la pause : état de départ rétabli, l'affectation de départ intacte.
    undone2 = await client.post(cancel_url(first_id), json={"reason": "Pause jamais prise"}, headers=h)
    assert undone2.status_code == 200, undone2.text
    final = undone2.json()
    assert _pump(final, 1)["holder"]["userId"] == ctx["att"][0] and _pump(final, 1)["kind"] == "start" and final["openBreaks"] == [] and final["unattendedPumps"] == []
    start_segments = [s for s in await _db_segments(ctx["report"]) if s.kind == "start"]
    assert len(start_segments) == 3 and all(s.cancelledAt is None and s.endsAt is None and s.plannedUserId == s.userId for s in start_segments)
    # Une nouvelle saisie reste possible après annulation.
    assert (await _break(client, h, ctx, ctx["att"][0], ctx["att"][3])).status_code == 201
    async with AsyncSessionLocal() as db:
        actions = (await db.execute(select(AuditLog.action).where(AuditLog.organizationId == uuid.UUID(zylo_liquid_organization["id"]), AuditLog.action == "zyloLiquid.shiftReplacement.cancel"))).scalars().all()
    assert len(actions) >= 2


# ---------------------------------------------------------------------------
# Fonctions publiques (D3, D5, E6, D6)
# ---------------------------------------------------------------------------


async def test_public_functions_for_d3(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid import service
    from app.core.errors import AppError

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    report, p1, p2 = uuid.UUID(ctx["report"]), uuid.UUID(ctx["pumps"][0]), uuid.UUID(ctx["pumps"][1])
    started = datetime.now(timezone.utc)
    t_break = (started - timedelta(minutes=30)).isoformat()
    res = await _move(client, h, ctx, kind="break_start", subjectUserId=ctx["att"][0], occurredAt=t_break, note="Pompe 2 fermée", rows=[
        {"pumpId": ctx["pumps"][0], "coverUserId": ctx["ce"]}, {"pumpId": ctx["pumps"][1], "closedForBreak": True},
    ])
    assert res.status_code == 201, res.text
    async with AsyncSessionLocal() as db:
        org_id = uuid.UUID(zylo_liquid_organization["id"])
        # Chronologie et titulaire à un instant donné (au changement : le nouveau segment).
        timeline = await shifts_mouvements.get_pump_timeline(db, report, p1)
        assert [s.kind for s in timeline] == ["start", "break_cover"] and timeline[0].endsAt == timeline[1].startsAt
        assert (await shifts_mouvements.get_holder_at(db, report, p1, started - timedelta(hours=1))).userId == uuid.UUID(ctx["att"][0])
        assert (await shifts_mouvements.get_holder_at(db, report, p1, started)).userId == uuid.UUID(ctx["ce"])
        assert (await shifts_mouvements.get_holder_at(db, report, p1, timeline[1].startsAt)).kind == "break_cover"
        assert await shifts_mouvements.get_holder_at(db, report, p1, ctx["opened_at"] - timedelta(hours=1)) is None
        assert [b.subjectUserId for b in await shifts_mouvements.list_open_breaks(db, report)] == [uuid.UUID(ctx["att"][0])]
        assert [s.pumpId for s in await shifts_mouvements.list_unattended_pumps(db, report)] == [p2]
        # Deux personnes ont tenu la pompe 1 : écart NON attribuable automatiquement ; marqueur chef d'équipe ; pas de litres sans index.
        holders = {x["userId"]: x for x in await shifts_mouvements.get_pump_holders(db, org_id, report, p1)}
        assert set(holders) == {uuid.UUID(ctx["att"][0]), uuid.UUID(ctx["ce"])} and all(x["shared"] for x in holders.values())
        assert holders[uuid.UUID(ctx["ce"])]["isTeamLead"] is True and holders[uuid.UUID(ctx["ce"])]["liters"] is None and holders[uuid.UUID(ctx["ce"])]["lastEndsAt"] is None
        single = await shifts_mouvements.get_pump_holders(db, org_id, report, uuid.UUID(ctx["pumps"][2]))
        assert len(single) == 1 and single[0]["shared"] is False

        # Répartition MANUELLE de l'écart : jamais de clé inventée ; chaque part à une personne qui a tenu la pompe ; somme exacte ; motif.
        att0, ce, att3 = uuid.UUID(ctx["att"][0]), uuid.UUID(ctx["ce"]), uuid.UUID(ctx["att"][3])
        parts = await caisse_collecte.validate_cash_variance_split(db, report, p1, "-1500.00", [(att0, "-1000.00"), (ce, "-500.00")], "Constaté avec le RT")
        assert parts == [(att0, Decimal("-1000.00")), (ce, Decimal("-500.00"))]
        for bad_parts, total, reason, expected in [
            ([(att0, "-1000.00"), (ce, "-400.00")], "-1500.00", "ok", "split_sum_mismatch"),
            ([(att0, "-1000.00"), (att3, "-500.00")], "-1500.00", "ok", "split_user_not_holder"),
            ([(att0, "-1000.00"), (att0, "-500.00")], "-1500.00", "ok", "split_user_duplicate"),
            ([(att0, "-1500.005")], "-1500.00", "ok", "split_amount_invalid"),
            ([(att0, "-1500.00")], "-1500.00", " ", "split_reason_required"),
        ]:
            try:
                await caisse_collecte.validate_cash_variance_split(db, report, p1, total, bad_parts, reason)
            except AppError as exc:
                assert exc.status_code == 422 and exc.code == "variance_split_invalid" and expected in {d["code"] for d in exc.details}, (expected, exc.details)
            else:
                raise AssertionError(f"{expected} aurait dû être refusé")
        # Trace d'audit (qui, quoi, quel motif) dans la transaction de l'appelant.
        await caisse_collecte.trace_cash_variance_split(db, org_id, uuid.UUID(ctx["rt"]), report, p1, "-1500.00", [(att0, "-1000.00"), (ce, "-500.00")], "Constaté avec le RT")
        await db.commit()
        entry = (await db.execute(select(AuditLog).where(AuditLog.organizationId == org_id, AuditLog.action == "zyloLiquid.shiftReplacement.cashVarianceSplit"))).scalars().one()
        assert entry.changes["reason"] == "Constaté avec le RT" and len(entry.changes["parts"]) == 2 and entry.scopeResourceType == "station"


# ---------------------------------------------------------------------------
# Droits et portée station
# ---------------------------------------------------------------------------


async def test_permissions_team_lead_reads_but_does_not_write(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    org = zylo_liquid_organization
    url = f"{BASE}/shift-reports/{ctx['report']}/movements"
    body = {"kind": "break_start", "subjectUserId": ctx["att"][0], "rows": [{"pumpId": ctx["pumps"][0], "coverUserId": ctx["att"][2]}, {"pumpId": ctx["pumps"][1], "coverUserId": ctx["att"][2]}]}
    # Lecture : chef d'équipe, caissier, auditeur ; écriture refusée à tous les trois.
    for code in ("zylo_liquid_team_lead", "zylo_liquid_cashier", "zylo_liquid_auditor"):
        headers = await _scoped_user(client, h, org, code, ctx["station"])
        read = await client.get(url, headers=headers)
        assert read.status_code == 200, (code, read.text)
        assert read.json()["access"]["canManage"] is False
        write = await client.post(url, json=body, headers=headers)
        assert write.status_code == 403, (code, write.text)
    # Le pompiste n'a aucune des deux permissions (sa carte relève de B4).
    attendant = await _scoped_user(client, h, org, "zylo_liquid_pump_attendant", ctx["station"])
    assert (await client.get(url, headers=attendant)).status_code == 403
    assert (await client.post(url, json=body, headers=attendant)).status_code == 403
    # RT et gérant : lecture + écriture (annulation comprise).
    manager = await _scoped_user(client, h, org, "zylo_liquid_station_admin", ctx["station"])
    done = await client.post(url, json=body, headers=manager)
    assert done.status_code == 201, done.text
    assert done.json()["access"]["canManage"] is True
    rt = await _scoped_user(client, h, org, "zylo_liquid_shift_manager", ctx["station"])
    mid = done.json()["movements"][0]["id"]
    cancel = await client.post(f"{url}/{mid}/cancel", json={"reason": "Test"}, headers=rt)
    assert cancel.status_code == 200, cancel.text
    # Le chef d'équipe ne peut pas annuler non plus.
    lead = await _scoped_user(client, h, org, "zylo_liquid_team_lead", ctx["station"])
    assert (await client.post(f"{url}/{mid}/cancel", json={"reason": "Test"}, headers=lead)).status_code == 403


async def test_station_scope_is_enforced(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    other = await _ctx(client, h, zylo_liquid_organization)
    # RT scopé à l'AUTRE station : ni lecture ni écriture sur ce rapport.
    rt_other = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", other["station"])
    url = f"{BASE}/shift-reports/{ctx['report']}/movements"
    assert (await client.get(url, headers=rt_other)).status_code == 403
    res = await client.post(url, json={"kind": "reassignment", "subjectUserId": ctx["att"][2], "reason": "rebalancing", "rows": [{"pumpId": ctx["pumps"][2]}]}, headers=rt_other)
    assert res.status_code == 403
    # Rapport inconnu : 404 (jamais une fuite d'une autre organisation).
    assert (await client.get(f"{BASE}/shift-reports/{uuid.uuid4()}/movements", headers=h)).status_code == 404
