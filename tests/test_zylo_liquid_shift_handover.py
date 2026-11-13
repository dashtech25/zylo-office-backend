"""Scénario B2 (passation entre responsables de tour) : passation ancrée au tour SORTANT, lignes
typées (consigne, anomalie en cours, information), enregistrement en lot tout-ou-rien avec erreurs
par cellule, case « rien à signaler » explicite, prise de connaissance non bloquante du tour
entrant, anomalies en cours au niveau STATION réglées par une action séparée, état de la station
calculé (« non disponible » faute de source, jamais inventé), fenêtre d'écriture du RT, verrou
optimiste, correction après lecture, droits (ni chef d'équipe, ni pompiste, ni caissier) et portée station."""

import uuid
from datetime import date, datetime, timedelta

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


async def _insert_occurrence(station_id: str, shift_id: str, day: date, starts_at: datetime, ends_at: datetime, name: str, rt_user_id: str | None = None) -> str:
    from app.modules.zylo_liquid.models import ShiftAssignment, ShiftOccurrence

    async with AsyncSessionLocal() as db:
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station_id), shiftDefinitionId=uuid.UUID(shift_id), shiftDate=day, shiftNumber=1, name=name,
            startTime=f"{starts_at:%H:%M}", endTime=f"{ends_at:%H:%M}", startsAt=starts_at, endsAt=ends_at, status="planned",
        )
        db.add(occurrence)
        await db.flush()
        if rt_user_id:
            db.add(ShiftAssignment(occurrenceId=occurrence.id, userId=uuid.UUID(rt_user_id), shiftRole="shift_manager"))
        await db.commit()
        return str(occurrence.id)


async def _set_status(occurrence_id: str, status: str) -> None:
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(occurrence_id)).values(status=status))
        await db.commit()


async def _ctx(client: AsyncClient, h: dict, organization: dict, with_previous: bool = True) -> dict:
    """Station (2 pompes, 1 cuve) + tour « Journée » 24 h planifié AUJOURD'HUI (en cours : le RT peut écrire sa
    passation) ; `previous` = tour d'il y a 2 jours (06:00-14:00) posé en base, hors fenêtre du RT."""
    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station B2{suffix}", "code": f"H{suffix}"}))["id"]
    product = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SU{suffix}"}))["id"]
    tank = (await _post(client, h, "/tanks", {
        "stationId": station, "fuelProductId": product, "tankNumber": 1, "displayName": "Cuve 1", "capacityLiters": 20000,
        "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
    }))["id"]
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": [{"rowNumber": i, "tankId": tank, "pumpNumber": i} for i in (1, 2)]}))["data"]]
    shift = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [{"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"}]}))["data"][0]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "firstName": "RT", "lastName": f"N{suffix}", "email": f"b2-rt-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles["zylo_liquid_shift_manager"]},
    ]}))["data"]
    rt = staff[0]["staff"]["userId"]
    today = date.today()
    res = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": station, "from": today.isoformat(), "to": today.isoformat(),
        "occurrences": [{"date": today.isoformat(), "shiftDefinitionId": shift["id"], "assignments": [{"userId": rt, "shiftRole": "shift_manager"}]}],
    })
    assert res.status_code == 200, res.text
    current = res.json()["planning"]["occurrences"][0]["id"]
    previous = None
    if with_previous:
        start = datetime.combine(today - timedelta(days=2), datetime.min.time()) + timedelta(hours=6)
        previous = await _insert_occurrence(station, shift["id"], today - timedelta(days=2), start, start + timedelta(hours=8), "Matin", rt)
    return {"station": station, "pumps": pumps, "tank": tank, "shift": shift, "roles": roles, "rt": rt, "current": current, "previous": previous}


async def _context(client, headers, occurrence_id):
    return await client.get(f"{BASE}/shift-handover/context?occurrenceId={occurrence_id}", headers=headers)


async def _put(client, headers, occurrence_id, items, nothing=False, version=None):
    body = {"occurrenceId": occurrence_id, "nothingToReport": nothing, "items": items}
    if version is not None:
        body["version"] = version
    return await client.put(f"{BASE}/shift-handover/bulk", json=body, headers=headers)


def _item(key, kind="info", category="other", description="Camion Gas-oil attendu vers 16:00, jauger avant et après.", importance="normal", **extra):
    return {"itemKey": key, "kind": kind, "category": category, "description": description, "importance": importance, **extra}


def _echo(items: list[dict]) -> list[dict]:
    """Corps d'envoi issu de la réponse : les lignes enregistrées telles quelles."""
    return [
        {"itemKey": i["itemKey"], "kind": i["kind"], "category": i["category"], "pumpId": i["pumpId"], "tankId": i["tankId"], "description": i["description"], "importance": i["importance"]}
        for i in items
    ]


def _codes(res) -> set:
    return {(d["rowNumber"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


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


async def test_first_shift_has_no_previous_and_state_is_never_invented(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, with_previous=False)
    res = await _context(client, h, ctx["current"])
    assert res.status_code == 200, res.text
    body = res.json()
    # Premier tour de la station : « aucune passation à recevoir », rien d'inventé.
    assert body["previous"] is None and body["openIssues"] == []
    assert body["receiptAccess"]["canReceive"] is False and body["receiptAccess"]["blockedCode"] == "no_handover"
    # Partie B vide virtuelle : version 0, aucune signature, aucune ligne.
    out = body["outgoing"]
    assert out["handoverId"] is None and out["version"] == 0 and out["signature"] is None and out["items"] == [] and out["nothingToReport"] is False
    assert out["access"]["canWrite"] is True
    # État calculé : sources réelles disponibles, sources absentes « non disponible » avec la raison, jamais une valeur plausible.
    state = body["state"]
    assert state["pumps"]["available"] is True and state["pumps"]["data"]["total"] == 2 and state["pumps"]["data"]["active"] == 2
    assert state["pumpFaults"]["available"] is False and "C10" in state["pumpFaults"]["reason"] and state["pumpFaults"]["data"] is None
    assert state["closingIndexes"]["available"] is False and "D1" in state["closingIndexes"]["reason"]
    assert state["tanks"]["available"] is True and state["tanks"]["data"][0]["manualGauging"] is None and state["tanks"]["data"][0]["atg"] is None
    assert state["tanks"]["data"][0]["atgUnavailableReason"]
    assert state["prices"]["available"] is True and state["prices"]["data"][0]["priceAmount"] is None and state["prices"]["data"][0]["unavailableReason"]
    assert state["expectedDeliveries"]["available"] is True and state["expectedDeliveries"]["data"] == []
    assert state["alerts"]["available"] is True and state["alerts"]["data"]["unacknowledgedCount"] == 0
    assert state["attendance"]["available"] is False and state["incidents"]["available"] is False  # aucun tour précédent
    assert state["computedAt"]


async def test_bulk_save_signature_previous_context_and_receipt(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    # Le gérant (direction ici) écrit la passation du tour « Matin » d'il y a 2 jours (hors fenêtre du RT) : consigne + anomalie + information.
    items = [
        _item("a", kind="open_issue", category="pump", pumpId=ctx["pumps"][0], description="Compteur qui saute depuis 09:10, pompe arrêtée", importance="high"),
        _item("b", kind="instruction", category="price_credit", description="Super passe à 850 à partir de 18:00"),
        _item("c", kind="info", category="delivery", description="Camion Gas-oil attendu vers 16:00, jauger avant et après"),
    ]
    saved = await _put(client, h, ctx["previous"], items, version=0)
    assert saved.status_code == 200, saved.text
    out = saved.json()["outgoing"]
    assert out["version"] == 1 and out["handoverId"] and out["signature"]["firstSignedAt"] == out["signature"]["lastSignedAt"]
    assert [i["kind"] for i in out["items"]] == ["open_issue", "instruction", "info"]
    issue = out["items"][0]
    assert issue["status"] == "open" and issue["pumpNumber"] == 1 and issue["pumpInactive"] is False and issue["authorRole"] == "station_admin"
    assert out["items"][1]["status"] is None and out["items"][2]["status"] is None
    handover_id = out["handoverId"]

    # Le tour suivant (aujourd'hui) reçoit : tour précédent, sa passation, anomalie en cours (niveau station), état calculé.
    ctx_res = await _context(client, h, ctx["current"])
    assert ctx_res.status_code == 200, ctx_res.text
    body = ctx_res.json()
    previous = body["previous"]
    assert previous["occurrenceId"] == ctx["previous"] and previous["shiftName"] == "Matin" and previous["isFallback"] is False
    assert [i["kind"] for i in previous["handover"]["items"]][0] == "open_issue"  # importante d'abord
    assert previous["handover"]["receipt"]["receivedAt"] is None
    assert [i["itemId"] for i in body["openIssues"]] == [issue["itemId"]] and body["openIssues"][0]["originShiftName"] == "Matin"
    assert body["receiptAccess"]["canReceive"] is True and body["receiptAccess"]["receivingOccurrenceId"] == ctx["current"]

    # Prise de connaissance NON bloquante : la partie B du tour entrant reste écrivable avant comme après.
    assert (await _put(client, h, ctx["current"], [], nothing=True)).status_code == 200
    # Sans tour entrant : refusé avec le message qui dit quoi faire.
    none_res = await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={}, headers=h)
    assert none_res.status_code == 422 and none_res.json()["error"]["code"] == "no_following_shift" and "B3" in none_res.json()["error"]["message"]
    # Un tour qui n'est pas postérieur à la passation : refusé.
    wrong = await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["previous"]}, headers=h)
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "receiving_occurrence_invalid"
    rt_headers, rt_user = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    received = await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=rt_headers)
    assert received.status_code == 200, received.text
    receipt = received.json()["handover"]["receipt"]
    assert receipt["receivedByUserId"] == rt_user and receipt["receivedAt"] and receipt["receivingOccurrenceId"] == ctx["current"]
    # Une seule prise de connaissance (sans complément) : 409.
    again = await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=rt_headers)
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_received"
    after = (await _context(client, rt_headers, ctx["current"])).json()
    assert after["receiptAccess"]["canReceive"] is False and after["receiptAccess"]["blockedCode"] == "already_received"

    # Complément après prise de connaissance : nouvelle ligne marquée « complément », relecture possible.
    current = (await _context(client, h, ctx["previous"])).json()["outgoing"]
    with_complement = _echo(current["items"]) + [_item("n", kind="instruction", category="safety", description="Extincteur à vérifier avant la nuit")]
    for existing in with_complement[:-1]:
        existing["changeReason"] = None
    saved2 = await _put(client, h, ctx["previous"], with_complement, version=current["version"])
    assert saved2.status_code == 200, saved2.text
    added = [i for i in saved2.json()["outgoing"]["items"] if i["description"].startswith("Extincteur")][0]
    assert added["addedAfterReceipt"] is True and saved2.json()["outgoing"]["access"]["requiresChangeReason"] is True
    assert any(w["code"] == "complement_after_receipt" for w in saved2.json()["warnings"])
    reread = await _context(client, rt_headers, ctx["current"])
    assert reread.json()["receiptAccess"]["canReceive"] is True
    relu = await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=rt_headers)
    assert relu.status_code == 200 and relu.json()["handover"]["complementsAfterReceipt"] == 1

    # Pastilles de la grille : écrite / reçue, nombre d'anomalies en cours de la station.
    today = date.today().isoformat()
    summary = (await client.get(f"{BASE}/shift-handover/summary?stationId={ctx['station']}&from={(date.today() - timedelta(days=3)).isoformat()}&to={today}", headers=h)).json()
    assert summary["openIssuesCount"] == 1
    by_occ = {o["occurrenceId"]: o for o in summary["occurrences"]}
    assert by_occ[ctx["previous"]]["written"] is True and by_occ[ctx["previous"]]["received"] is True
    assert by_occ[ctx["current"]]["written"] is True and by_occ[ctx["current"]]["received"] is False

    # Audit de chaque écriture (enregistrement, prise de connaissance).
    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        actions = set((await db.execute(select(AuditLog.action).where(AuditLog.scopeResourceId == uuid.UUID(ctx["station"])))).scalars().all())
    assert {"zyloLiquid.shiftHandover.save", "zyloLiquid.shiftHandover.receive"} <= actions


async def test_no_written_handover_and_fallback_to_last_written(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    # Tour précédent sans passation écrite : rien n'est inventé, la prise de connaissance n'a rien à lire.
    body = (await _context(client, h, ctx["current"])).json()
    assert body["previous"]["shiftName"] == "Matin" and body["previous"]["handover"] is None and body["previous"]["isFallback"] is False
    assert body["receiptAccess"]["canReceive"] is False and body["receiptAccess"]["blockedCode"] == "no_handover"
    # Tour précédent « non tenu » (planifié, jamais ouvert, terminé) : on reprend la dernière passation ANTÉRIEURE, avec mention.
    today = date.today()
    older_start = datetime.combine(today - timedelta(days=4), datetime.min.time()) + timedelta(hours=14)
    older = await _insert_occurrence(ctx["station"], ctx["shift"]["id"], today - timedelta(days=4), older_start, older_start + timedelta(hours=8), "Soir")
    assert (await _put(client, h, older, [_item("x", description="Rien de particulier mais prix affiché à vérifier")])).status_code == 200
    fallback = (await _context(client, h, ctx["current"])).json()["previous"]
    assert fallback["occurrenceId"] == older and fallback["shiftName"] == "Soir" and fallback["isFallback"] is True and fallback["handover"]["occurrenceId"] == older


async def test_all_or_nothing_reports_every_cell(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    other = await _ctx(client, h, zylo_liquid_organization, with_previous=False)
    items = [
        _item("ok-1", description="Information correcte et complète"),
        _item("e2", kind="info", category="other", description="ab"),  # description_required
        _item("e3", kind="bogus", category="other"),  # kind_required
        _item("e4", category="nope"),  # category_required
        _item("e5", category="pump"),  # object_required
        _item("e6", category="pump", pumpId=other["pumps"][0]),  # pump_not_in_station
        _item("e7", category="other", pumpId=ctx["pumps"][0]),  # object_not_applicable
        _item("e8", description="x" * 1001),  # description_too_long
        _item("e9", importance="urgent"),  # importance_invalid
        _item("e10", category="tank"),  # object_required (cuve)
    ]
    res = await _put(client, h, ctx["previous"], items)
    assert res.status_code == 422
    error = res.json()["error"]
    assert error["code"] == "shift_handover_invalid" and "rien n'a été enregistré" in error["message"]
    assert _codes(res) == {
        (2, "description", "description_required"), (3, "kind", "kind_required"), (4, "category", "category_required"), (5, "pumpId", "object_required"),
        (6, "pumpId", "pump_not_in_station"), (7, "pumpId", "object_not_applicable"), (8, "description", "description_too_long"),
        (9, "importance", "importance_invalid"), (10, "tankId", "object_required"),
    }
    detail = error["details"][0]
    assert set(detail) == {"rowNumber", "itemKey", "field", "code", "message"} and detail["itemKey"] == items[detail["rowNumber"] - 1]["itemKey"]
    assert all(d["message"] for d in error["details"])
    # Rien d'écrit, même pour la ligne valide.
    after = (await _context(client, h, ctx["previous"])).json()["outgoing"]
    assert after["handoverId"] is None and after["items"] == [] and after["version"] == 0


async def test_empty_handover_needs_explicit_nothing_to_report(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    # Une passation vide sans la case explicite est refusée (un oubli n'est pas un « rien à signaler »).
    empty = await _put(client, h, ctx["current"], [])
    assert empty.status_code == 422 and ("handover_empty" in {d["code"] for d in empty.json()["error"]["details"]})
    # Des lignes ET la case cochée : conflit.
    conflict = await _put(client, h, ctx["current"], [_item("a", description="Une information utile")], nothing=True)
    assert conflict.status_code == 422 and (None, "nothingToReport", "nothing_to_report_conflict") in _codes(conflict)
    # Plus de 50 lignes.
    many = await _put(client, h, ctx["current"], [_item(f"k{i}", description=f"Information numéro {i}") for i in range(51)])
    assert many.status_code == 422 and "too_many_items" in {d["code"] for d in many.json()["error"]["details"]}
    # « Rien à signaler » explicite : enregistré avec zéro ligne.
    ok = await _put(client, h, ctx["current"], [], nothing=True)
    assert ok.status_code == 200 and ok.json()["outgoing"]["nothingToReport"] is True and ok.json()["outgoing"]["items"] == []
    # Aucune ligne n'est générée par le système : la passation du tour suivant ne reprend rien.
    assert (await _context(client, h, ctx["current"])).json()["openIssues"] == []


async def test_close_issue_is_immediate_atomic_and_idempotent_conflict(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    saved = await _put(client, h, ctx["previous"], [
        _item("a", kind="open_issue", category="customer", description="Client difficile : SGMV exige un reçu détaillé"),
        _item("b", kind="info", description="Information ponctuelle sans statut"),
    ])
    assert saved.status_code == 200, saved.text
    issue = next(i for i in saved.json()["outgoing"]["items"] if i["kind"] == "open_issue")
    info = next(i for i in saved.json()["outgoing"]["items"] if i["kind"] == "info")
    # Pas d'anomalie : seule une anomalie en cours se règle ; la résolution est obligatoire.
    assert (await client.post(f"{BASE}/shift-handover/items/{info['itemId']}/close", json={"resolution": "Réglé comme prévu"}, headers=h)).status_code == 422
    no_resolution = await client.post(f"{BASE}/shift-handover/items/{issue['itemId']}/close", json={"resolution": " "}, headers=h)
    assert no_resolution.status_code == 422 and no_resolution.json()["error"]["code"] == "resolution_required"
    assert (await _context(client, h, ctx["current"])).json()["openIssues"][0]["status"] == "open"
    # Réglée par le RT entrant (portée station) : disparaît de la liste en cours, garde auteur, heure et résolution.
    rt_headers, rt_user = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    closed = await client.post(f"{BASE}/shift-handover/items/{issue['itemId']}/close", json={"resolution": "Reçu détaillé remis au client"}, headers=rt_headers)
    assert closed.status_code == 200, closed.text
    item = closed.json()["item"]
    assert item["status"] == "closed" and item["closedByUserId"] == rt_user and item["resolution"] == "Reçu détaillé remis au client" and item["closedAt"]
    assert closed.json()["openIssuesCount"] == 0
    assert (await _context(client, h, ctx["current"])).json()["openIssues"] == []
    # La seconde personne reçoit 409 issue_already_closed, pas de réouverture.
    second = await client.post(f"{BASE}/shift-handover/items/{issue['itemId']}/close", json={"resolution": "Réglé aussi par moi"}, headers=h)
    assert second.status_code == 409 and second.json()["error"]["code"] == "issue_already_closed" and "vient d'être réglée" in second.json()["error"]["message"]
    # Une anomalie réglée ne se modifie plus et ne se supprime plus par le lot.
    current = (await _context(client, h, ctx["previous"])).json()["outgoing"]
    edited = _echo(current["items"])
    next(i for i in edited if i["itemKey"] == issue["itemKey"])["description"] = "Description modifiée après règlement"
    refused = await _put(client, h, ctx["previous"], edited, version=current["version"])
    assert refused.status_code == 422 and any(d["code"] == "issue_closed_locked" for d in refused.json()["error"]["details"])
    removed = await _put(client, h, ctx["previous"], [i for i in _echo(current["items"]) if i["itemKey"] != issue["itemKey"]], version=current["version"])
    assert removed.status_code == 422 and any(d["code"] == "item_locked_after_receipt" for d in removed.json()["error"]["details"])
    # Audit du règlement.
    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        actions = set((await db.execute(select(AuditLog.action).where(AuditLog.scopeResourceId == uuid.UUID(ctx["station"])))).scalars().all())
    assert "zyloLiquid.shiftHandover.closeIssue" in actions


async def test_optimistic_version_and_correction_after_receipt(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = await _put(client, h, ctx["previous"], [_item("a", description="Information à corriger plus tard")], version=0)
    assert first.status_code == 200
    stale = await _put(client, h, ctx["previous"], [_item("a", description="Autre version écrite")], version=0)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "handover_changed"
    current = first.json()["outgoing"]
    # Modification libre tant que la passation n'est pas lue (la clé d'une ligne enregistrée est son identifiant).
    edit = _echo(current["items"])
    edit[0]["description"] = "Information corrigée avant lecture"
    ok = await _put(client, h, ctx["previous"], edit, version=current["version"])
    assert ok.status_code == 200 and ok.json()["outgoing"]["items"][0]["description"] == "Information corrigée avant lecture"
    # Après prise de connaissance : modification sans raison refusée, avec raison acceptée ; suppression refusée.
    handover_id = ok.json()["outgoing"]["handoverId"]
    rt_headers, _uid = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    assert (await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=rt_headers)).status_code == 200
    version = ok.json()["outgoing"]["version"]
    edit2 = _echo(ok.json()["outgoing"]["items"])
    edit2[0]["description"] = "Information corrigée après lecture"
    no_reason = await _put(client, h, ctx["previous"], edit2, version=version)
    assert no_reason.status_code == 422 and (1, "changeReason", "change_reason_required") in _codes(no_reason)
    edit2[0]["changeReason"] = "Heure de livraison corrigée"
    with_reason = await _put(client, h, ctx["previous"], edit2, version=version)
    assert with_reason.status_code == 200, with_reason.text
    assert with_reason.json()["outgoing"]["items"][0]["changeReason"] == "Heure de livraison corrigée"
    deletion = await _put(client, h, ctx["previous"], [_item("n", kind="instruction", category="staff", description="Nouvelle consigne seule")], version=with_reason.json()["outgoing"]["version"])
    assert deletion.status_code == 422 and any(d["code"] == "item_locked_after_receipt" for d in deletion.json()["error"]["details"])


async def test_write_window_for_rt_vs_manager(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    rt_headers, _uid = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    # Tour en cours : le RT écrit.
    assert (await _put(client, rt_headers, ctx["current"], [_item("a")])).status_code == 200
    # Tour terminé depuis plus de 12 h : refusé au RT, permis au gérant.
    closed = await _put(client, rt_headers, ctx["previous"], [_item("a")])
    assert closed.status_code == 422 and closed.json()["error"]["code"] == "handover_window_closed" and "demandez au gérant" in closed.json()["error"]["message"]
    assert (await _context(client, rt_headers, ctx["previous"])).json()["outgoing"]["access"]["blockedCode"] == "handover_window_closed"
    assert (await _put(client, h, ctx["previous"], [_item("a")])).status_code == 200
    # Tour planifié pas encore commencé : refusé au RT (rien à transmettre), consigne anticipée permise au gérant.
    future = date.today() + timedelta(days=10)
    planned = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": ctx["station"], "from": future.isoformat(), "to": future.isoformat(),
        "occurrences": [{"date": future.isoformat(), "shiftDefinitionId": ctx["shift"]["id"], "assignments": [{"userId": ctx["rt"], "shiftRole": "shift_manager"}]}],
    })
    future_id = planned.json()["planning"]["occurrences"][0]["id"]
    not_started = await _put(client, rt_headers, future_id, [_item("a")])
    assert not_started.status_code == 422 and not_started.json()["error"]["code"] == "handover_not_started" and "pas encore commencé" in not_started.json()["error"]["message"]
    anticipated = await _put(client, h, future_id, [_item("a", kind="instruction", category="report_feedback", description="Consigne du gérant avant le tour")])
    assert anticipated.status_code == 200 and anticipated.json()["outgoing"]["items"][0]["authorRole"] == "station_admin"
    # Tour validé : verrouillé pour le RT ; le gérant ne peut qu'AJOUTER un complément.
    await _set_status(ctx["previous"], "validated")
    locked = await _put(client, rt_headers, ctx["previous"], [_item("a")])
    assert locked.status_code == 422 and locked.json()["error"]["code"] == "handover_locked"
    current = (await _context(client, h, ctx["previous"])).json()["outgoing"]
    assert current["lifecycleStatus"] == "locked"
    edited = _echo(current["items"])
    edited[0]["description"] = "Modification interdite d'une ligne existante"
    assert (await _put(client, h, ctx["previous"], edited, version=current["version"])).status_code == 422
    complement = await _put(client, h, ctx["previous"], _echo(current["items"]) + [_item("c", kind="instruction", category="other", description="Complément ajouté par le gérant")], version=current["version"])
    assert complement.status_code == 200, complement.text


async def test_permissions_roles_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    org = zylo_liquid_organization
    ctx = await _ctx(client, h, org)
    other = await _ctx(client, h, org)
    # Ni chef d'équipe, ni pompiste, ni caissier : aucun droit sur la passation (lecture, écriture, prise de connaissance, règlement).
    for code in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier"):
        headers, _uid = await _scoped_user(client, h, org, code, ctx["station"])
        assert (await _context(client, headers, ctx["current"])).status_code == 403, code
        assert (await _put(client, headers, ctx["current"], [_item("a")])).status_code == 403, code
    saved = await _put(client, h, ctx["previous"], [_item("a", kind="open_issue", category="other", description="Anomalie pour tester les droits")])
    handover_id = saved.json()["outgoing"]["handoverId"]
    item_id = saved.json()["outgoing"]["items"][0]["itemId"]
    other_saved = await _put(client, h, other["previous"], [_item("a", kind="open_issue", category="other", description="Anomalie d'une autre station")])
    other_handover = other_saved.json()["outgoing"]["handoverId"]
    other_item = other_saved.json()["outgoing"]["items"][0]["itemId"]
    # Auditeur : lecture seule.
    auditor, _uid = await _scoped_user(client, h, org, "zylo_liquid_auditor", ctx["station"])
    read = await _context(client, auditor, ctx["current"])
    assert read.status_code == 200 and read.json()["outgoing"]["access"]["canWrite"] is False and read.json()["receiptAccess"]["canReceive"] is False
    assert (await _put(client, auditor, ctx["current"], [_item("a")])).status_code == 403
    assert (await client.post(f"{BASE}/shift-handover/{handover_id}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=auditor)).status_code == 403
    assert (await client.post(f"{BASE}/shift-handover/items/{item_id}/close", json={"resolution": "Tentative sans droit"}, headers=auditor)).status_code == 403
    # RT et gérant : tout sur LEUR station, rien sur une autre (portée station, y compris les actions par identifiant).
    for code in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        headers, _uid = await _scoped_user(client, h, org, code, ctx["station"])
        mine = await _context(client, headers, ctx["current"])
        assert mine.status_code == 200 and mine.json()["outgoing"]["access"]["canWrite"] is True, code
        assert (await _context(client, headers, other["current"])).status_code == 403, code
        assert (await _put(client, headers, other["current"], [_item("a")])).status_code == 403, code
        assert (await client.post(f"{BASE}/shift-handover/{other_handover}/receive", json={"receivingOccurrenceId": other["current"]}, headers=headers)).status_code == 403, code
        assert (await client.post(f"{BASE}/shift-handover/items/{other_item}/close", json={"resolution": "Autre station"}, headers=headers)).status_code == 403, code
        assert (await client.get(f"{BASE}/shift-handover/summary?stationId={other['station']}&from={date.today()}&to={date.today()}", headers=headers)).status_code == 403, code
    # Les anomalies d'une station ne fuient pas dans une autre.
    assert [i["itemId"] for i in (await _context(client, h, other["current"])).json()["openIssues"]] == [other_item]
    # Droits des rôles : le gérant possède toutes les permissions du RT ; CE, pompiste, caissier aucune de la passation ; auditeur lecture seule.
    from app.rbac.service import get_role_permission_codes

    async with AsyncSessionLocal() as db:
        perms = {code: set(await get_role_permission_codes(db, uuid.UUID(ctx["roles"][code]))) for code in (
            "zylo_liquid_station_admin", "zylo_liquid_shift_manager", "zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier", "zylo_liquid_auditor")}
    handover = {"zyloLiquid.shiftHandover.read", "zyloLiquid.shiftHandover.manage"}
    assert perms["zylo_liquid_shift_manager"] <= perms["zylo_liquid_station_admin"]
    assert handover <= perms["zylo_liquid_shift_manager"] and handover <= perms["zylo_liquid_station_admin"]
    assert "zyloLiquid.shiftHandover.read" in perms["zylo_liquid_auditor"] and "zyloLiquid.shiftHandover.manage" not in perms["zylo_liquid_auditor"]
    for code in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant", "zylo_liquid_cashier"):
        assert not (handover & perms[code]), code
    # Tour ou passation inexistants : 404.
    assert (await _context(client, h, str(uuid.uuid4()))).status_code == 404
    assert (await client.post(f"{BASE}/shift-handover/{uuid.uuid4()}/receive", json={"receivingOccurrenceId": ctx["current"]}, headers=h)).status_code == 404
