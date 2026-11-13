"""Scénario D3 (comptage et remise de caisse par pompiste) : attribution des ventes (un titulaire, index de changement B5,
répartition MANUELLE tracée, jamais estimée), théorique = ventes - déductions, remis = recompté, écart signé = remis - théorique,
NOTA SOCADA (somme +3 121,25), écart de groupe tant qu'une pompe partagée n'est pas répartie, enregistrement tout-ou-rien avec
erreurs par cellule `cash_collection_invalid`, rature paraphée, verrou optimiste `cashVersion`, état « à recalculer » après un
changement de D1, audit, événement et droits (chef d'équipe sans accès).

Le tour ouvert, son rapport (fermeture D1 enregistrée), ses lignes de pompe (litres, prix, montant) et l'affectation sont posés
directement en base : D3 est testé indépendamment des endpoints d'ouverture, de fermeture et d'affectation."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal

from app.shared import events
from app.modules.zylo_liquid.exploitation.alg_caisse import attribute_pump_sales, compute_cash_line, parse_cash_amount, split_amount_with_remainder
from app.modules.zylo_liquid.exploitation import caisse_collecte as caisse_collecte

BASE = "/api/v1/zylo-liquid"
OPENING = Decimal("1000.00")
D = Decimal


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


def _pump(liters, price="840", holders=None, starts=(None,), exits=None):
    """`holders` : indices de pompistes ; par défaut, le pompiste de même rang que la pompe (renseigné dans `_ctx`)."""
    return {"liters": D(str(liters)), "price": None if price is None else D(str(price)), "holders": None if holders is None else list(holders), "starts": [None if x is None else D(str(x)) for x in starts], "exits": exits}


async def _ctx(client: AsyncClient, h: dict, organization: dict, pumps_cfg: list[dict], confirm: bool = True, phase: str = "ready_to_close", status: str = "opened") -> dict:
    """Station + pompes + personnel (1 RT, 1 CE, 6 pompistes) + tour ouvert depuis 3 h, D1 « enregistré » (`closingPhase`)."""
    from app.modules.zylo_liquid.models import ShiftOccurrence, ShiftPumpAssignment, ShiftPumpAssignmentSheet, ShiftReport, ShiftReportPumpLine

    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station D3{suffix}", "code": f"D{suffix}"}))["id"]
    product = (await _post(client, h, "/fuel-products", {"name": f"Super{suffix}", "code": f"SD{suffix}"}))["id"]
    tank = (await _post(client, h, "/tanks", {
        "stationId": station, "fuelProductId": product, "tankNumber": 1, "displayName": "Cuve 1", "capacityLiters": 20000,
        "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
    }))["id"]
    rows = [{"rowNumber": i + 1, "tankId": tank, "pumpNumber": i + 1} for i in range(len(pumps_cfg))]
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": rows}))["data"]]
    shift = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"},
    ]}))["data"][0]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}

    def row(n, code, first=None):
        return {"rowNumber": n, "firstName": first or f"P{n}", "lastName": f"N{suffix}", "email": f"d3-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    names = ["Djouka", "Gombang", "Djoukovo", "Ella", "Wenpiep", "Fotie"]
    staff_rows = [row(1, "zylo_liquid_shift_manager", "Rt"), row(2, "zylo_liquid_team_lead", "Chef")] + [row(3 + i, "zylo_liquid_pump_attendant", names[i]) for i in range(6)]
    staff = (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]
    ids = [s["staff"]["userId"] for s in staff]
    rt, ce, att = ids[0], ids[1], ids[2:]

    now = datetime.now(timezone.utc)
    opened_at = now - timedelta(hours=3)
    async with AsyncSessionLocal() as db:
        local = opened_at.astimezone().replace(tzinfo=None)
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station), shiftDefinitionId=uuid.UUID(shift["id"]), shiftDate=date.today(), shiftNumber=1, name="Journée",
            startTime="00:00", endTime="00:00", startsAt=local, endsAt=local + timedelta(days=1), status=status, openedAt=opened_at, openedByUserId=uuid.UUID(rt),
        )
        db.add(occurrence)
        await db.flush()
        report = ShiftReport(
            stationId=uuid.UUID(station), occurrenceId=occurrence.id, shiftDate=occurrence.shiftDate, shiftNumber=1, shiftName="Journée", startTime="00:00", endTime="00:00",
            responsibleUserId=uuid.UUID(rt), openedByUserId=uuid.UUID(rt), openedAt=opened_at, closingVersion=1, closingPhase=phase,
        )
        db.add(report)
        await db.flush()
        if confirm:
            db.add(ShiftPumpAssignmentSheet(reportId=report.id, stationId=uuid.UUID(station), version=1, confirmedAt=opened_at, confirmedByUserId=uuid.UUID(rt)))
        line_ids = []
        for number, (pump_id, cfg) in enumerate(zip(pumps, pumps_cfg), start=1):
            exits = cfg["exits"]
            sold = cfg["liters"]
            amount = None if cfg["price"] is None else (sold * cfg["price"]).quantize(D("0.01"), rounding=ROUND_HALF_UP)
            line = ShiftReportPumpLine(
                reportId=report.id, pumpId=uuid.UUID(pump_id), pumpNumber=number, pumpName=f"Pompe {number}", tankId=uuid.UUID(tank), fuelProductName="Super",
                openingIndex=OPENING, openingSource="initial", closingIndex=OPENING + sold + (exits or 0), exitsLiters=exits, soldLiters=sold,
                unitPriceAmount=cfg["price"], amount=amount,
            )
            db.add(line)
            await db.flush()
            line_ids.append(str(line.id))
            if confirm:
                holders = cfg["holders"] if cfg["holders"] is not None else [number - 1]
                for k, holder in enumerate(holders):
                    starts_at = opened_at + timedelta(minutes=30 * k)
                    ends_at = opened_at + timedelta(minutes=30 * (k + 1)) if k + 1 < len(holders) else None
                    db.add(ShiftPumpAssignment(
                        reportId=report.id, pumpLineId=line.id, pumpId=uuid.UUID(pump_id), userId=uuid.UUID(att[holder]), plannedUserId=uuid.UUID(att[holders[0]]),
                        startsAt=starts_at, endsAt=ends_at, kind="start" if k == 0 else "replacement", startIndex=OPENING if k == 0 else cfg["starts"][k],
                        recordedAt=opened_at, recordedByUserId=uuid.UUID(rt),
                    ))
        await db.commit()
        report_id = str(report.id)
    return {"station": station, "pumps": pumps, "lines": line_ids, "report": report_id, "rt": rt, "ce": ce, "att": att, "names": names, "opened_at": opened_at}


def _line(ctx, i, counted, recounted=None, credit=None, mobile=None, other=None, other_note=None, docs=True, note=None, rature=None):
    body = {
        "userId": ctx["att"][i], "attendantCountedAmount": counted, "managerRecountedAmount": counted if recounted is None else recounted,
        "creditVouchersAmount": credit, "mobilePaymentsAmount": mobile, "otherDeductionsAmount": other, "otherDeductionsNote": other_note,
        "documentsHandedOver": docs, "note": note,
    }
    if rature is not None:
        body["rature"] = rature
    return body


async def _get(client, h, ctx):
    res = await client.get(f"{BASE}/shift-reports/{ctx['report']}/closing-cash", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


async def _put(client, h, ctx, lines, version=0, pump_shares=None, confirmed=None):
    body = {"cashVersion": version, "lines": lines, "pumpShares": pump_shares or [], "confirmedNoDeductions": ctx["att"] if confirmed is None else confirmed}
    return await client.put(f"{BASE}/shift-reports/{ctx['report']}/closing-cash", json=body, headers=h)


def _codes(res) -> set:
    return {(d["rowKey"].split(":")[0] + ":" + d["rowKey"].split(":")[1][:0], d["field"], d["code"]) for d in res.json()["error"]["details"]}


def _plain(text: str) -> str:
    """Espaces insécables (milliers) ramenés à une espace simple pour comparer les messages."""
    return text.replace("\u202f", " ").replace("\xa0", " ")


def _detail_codes(res) -> list[str]:
    return [d["code"] for d in res.json()["error"]["details"]]


def _by_user(view, ctx, i):
    return next(l for l in view["lines"] if l["userId"] == ctx["att"][i])


def _six_pumps():
    return [_pump(liters) for liters in (100, 200, 300, 400, 500, 600)]  # 84 000, 168 000, 252 000, 336 000, 420 000, 504 000


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
        json={"userId": str(user_id), "roleId": role["id"], "resourceType": "station", "resourceId": station_id}, headers=owner_headers,
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"], "_user": str(user_id)}


# ---------------------------------------------------------------------------
# Algorithmes purs
# ---------------------------------------------------------------------------


def test_parse_cash_amount_normalizes_and_rejects():
    assert parse_cash_amount("303 950,32") == (D("303950.32"), None)
    assert parse_cash_amount(303950.32) == (D("303950.32"), None)
    assert parse_cash_amount("-1")[1] == "negative"
    assert parse_cash_amount("1,234")[1] == "too_many_decimals"
    assert parse_cash_amount("abc")[1] == "not_a_number"
    assert parse_cash_amount("1" + "0" * 12)[1] == "too_large"


def test_cash_line_formula_matches_the_field_example():
    """Cahier : 200 L x 840 = 168 000 - 40 000 (crédit) - 10 000 (mobile) = 118 000 ; remis 118 400 = +400, 117 700 = -300."""
    over = compute_cash_line(D("168000"), D("40000"), D("10000"), D(0), D("118400"), D("118400"))
    assert over["theoretical"] == D("118000") and over["variance"] == D("400") and over["varianceNature"] == "surplus"
    short = compute_cash_line(D("168000"), D("40000"), D("10000"), D(0), D("117700"), D("117700"))
    assert short["variance"] == D("-300") and short["varianceNature"] == "shortage"
    unknown = compute_cash_line(None, D(0), D(0), D(0), D("10"), D("10"))
    assert unknown["theoretical"] is None and unknown["variance"] is None and unknown["varianceNature"] is None


def test_remainder_goes_to_the_last_part_so_the_sum_is_exact():
    parts = split_amount_with_remainder(D("100.00"), [D(1), D(1), D(1)])
    assert parts == [D("33.33"), D("33.33"), D("33.34")] and sum(parts) == D("100.00")


def test_segment_index_attribution_and_no_estimate_without_index():
    a, b = uuid.uuid4(), uuid.uuid4()
    auto = attribute_pump_sales(liters=D("1000"), amount=D("1000.01"), unit_price=D("1.00001"), segments=[(a, D("1000")), (b, D("1300"))], closing_index=D("2000"), has_exits=False)
    assert auto["state"] == "segment_index" and auto["shares"][a][0] == D("300") and auto["shares"][b][0] == D("700")
    assert auto["shares"][a][1] + auto["shares"][b][1] == D("1000.01")
    # Relais sans index intermédiaire : AUCUNE attribution, jamais une moitié par défaut.
    none = attribute_pump_sales(liters=D("420.50"), amount=D("353220.00"), unit_price=D("840"), segments=[(a, D("1000")), (b, None)], closing_index=D("1420.50"), has_exits=False)
    assert none["state"] == "needs_manual" and none["shares"] == {}
    # Sorties de la pompe : l'index ne suffit plus, répartition manuelle exigée.
    exits = attribute_pump_sales(liters=D("990"), amount=D("990"), unit_price=D("1"), segments=[(a, D("1000")), (b, D("1300"))], closing_index=D("2000"), has_exits=True)
    assert exits["state"] == "needs_manual"
    manual = attribute_pump_sales(liters=D("420.50"), amount=D("353220.00"), unit_price=D("840"), segments=[(a, D("1000")), (b, None)], closing_index=D("1420.50"), has_exits=False, manual_shares={a: D("200"), b: D("220.50")})
    assert manual["state"] == "manual" and manual["shares"][a][0] == D("200") and sum(v[1] for v in manual["shares"].values()) == D("353220.00")
    wrong = attribute_pump_sales(liters=D("420.50"), amount=D("353220.00"), unit_price=D("840"), segments=[(a, D("1000")), (b, None)], closing_index=D("1420.50"), has_exits=False, manual_shares={a: D("200"), b: D("200")})
    assert wrong["state"] == "needs_manual" and wrong["problem"] == "manual_shares_stale"


# ---------------------------------------------------------------------------
# NOTA SOCADA et formule du terrain
# ---------------------------------------------------------------------------


async def test_socada_nota_sums_to_3121_25_and_f_is_the_sum_of_remittances(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, _six_pumps())
    before = await _get(client, h, ctx)
    assert before["cashVersion"] == 0 and before["access"]["canManage"] is True and before["access"]["locked"] is False
    assert [l["fullName"].split()[0] for l in before["lines"]] == ["Djouka", "Gombang", "Djoukovo", "Ella", "Wenpiep", "Fotie"]
    assert all(l["saved"] is False and l["theoreticalAmount"] is None for l in before["lines"])
    assert _by_user(before, ctx, 1)["salesValue"] == "168000.00" and _by_user(before, ctx, 1)["attributedLiters"] == "200.00"

    sales = [D(84000), D(168000), D(252000), D(336000), D(420000), D(504000)]
    variances = [D("730.32"), D("2617.8"), D("358.61"), D("-757.2"), D("303.68"), D("-131.96")]
    lines = [_line(ctx, i, str(sales[i] + variances[i])) for i in range(6)]
    res = await _put(client, h, ctx, lines)
    assert res.status_code == 200, res.text
    view = res.json()
    assert view["cashVersion"] == 1
    for i, variance in enumerate(variances):
        line = _by_user(view, ctx, i)
        assert D(line["theoreticalAmount"]) == sales[i] and D(line["varianceAmount"]) == variance and D(line["remittedAmount"]) == sales[i] + variance
        assert line["varianceNature"] == ("surplus" if variance > 0 else "shortage") and line["saved"] is True and line["deductionsSource"] == "manual"
    summary = view["summary"]
    assert D(summary["notaSum"]) == D("3121.25") and D(summary["notaTotal"]) == D("3121.25")
    assert D(summary["totalRemitted"]) == sum(sales) + D("3121.25") and D(summary["theoreticalSum"]) == sum(sales)
    assert summary["allRecorded"] is True and summary["linesRecorded"] == 6 and summary["hasUnresolvedPumps"] is False and summary["hasStaleLines"] is False
    assert [n["fullName"].split()[0] for n in summary["notaLines"]] == ["Djouka", "Gombang", "Djoukovo", "Ella", "Wenpiep", "Fotie"]
    # Fonctions publiques consommées par D5.
    from app.modules.zylo_liquid import service

    async with AsyncSessionLocal() as db:
        pub = await caisse_collecte.get_cash_summary(db, uuid.UUID(ctx["report"]))
        nota = await caisse_collecte.get_nota_lines(db, uuid.UUID(ctx["report"]))
    assert pub.notaSum == D("3121.25") and pub.totalRemitted == sum(sales) + D("3121.25") and len(nota) == 6 and nota[3].varianceAmount == D("-757.20")


async def test_field_example_with_credit_and_mobile_deductions(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(200), _pump(100)])
    # Sans déduction pour le 2e pompiste : confirmation nominative fournie ; le 1er porte crédit et mobile.
    lines = [_line(ctx, 0, "118400", credit="40 000", mobile=10000), _line(ctx, 1, "84000")]
    # Le tableau attend les 6 pompistes ? Non : seules les personnes ayant tenu une pompe (2 ici).
    res = await _put(client, h, ctx, lines, confirmed=[ctx["att"][1]])
    assert res.status_code == 200, res.text
    first = _by_user(res.json(), ctx, 0)
    assert D(first["theoreticalAmount"]) == D("118000") and D(first["varianceAmount"]) == D("400") and first["varianceNature"] == "surplus"
    assert D(first["creditVouchersAmount"]) == D("40000") and D(first["mobilePaymentsAmount"]) == D("10000")
    second = _by_user(res.json(), ctx, 1)
    assert D(second["varianceAmount"]) == D("0") and second["varianceNature"] == "balanced"


# ---------------------------------------------------------------------------
# Tout-ou-rien et erreurs par cellule
# ---------------------------------------------------------------------------


async def test_all_errors_come_back_at_once_and_nothing_is_written(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100), _pump(200), _pump(300), _pump(400)])
    lines = [
        _line(ctx, 0, "84000", recounted="83900"),  # comptages différents, pas d'observation
        _line(ctx, 1, "168000", credit="400 000"),  # déductions > ventes
        _line(ctx, 2, "252000", other="10 000"),  # autre déduction sans note
        # pompiste 3 oublié (cash_line_missing) ; un montant illisible pour le 4e plus bas
    ]
    lines.append(_line(ctx, 3, "abc"))
    res = await _put(client, h, ctx, lines)
    assert res.status_code == 422 and res.json()["error"]["code"] == "cash_collection_invalid", res.text
    details = res.json()["error"]["details"]
    got = {(d["rowKey"], d["field"], d["code"]) for d in details}
    assert (f"user:{ctx['att'][0]}", "note", "count_mismatch_note_missing") in got
    assert (f"user:{ctx['att'][1]}", "creditVouchersAmount", "deductions_exceed_sales") in got
    assert (f"user:{ctx['att'][2]}", "otherDeductionsNote", "other_deduction_note_missing") in got
    assert (f"user:{ctx['att'][3]}", "attendantCountedAmount", "amount_invalid") in got
    assert all(d["message"] and d["rowNumber"] is not None for d in details)
    mismatch = _plain(next(d for d in details if d["code"] == "count_mismatch_note_missing")["message"])
    assert "84 000,00" in mismatch and "83 900,00" in mismatch and "observation" in mismatch
    exceed = _plain(next(d for d in details if d["code"] == "deductions_exceed_sales")["message"])
    assert "400 000,00" in exceed and "168 000,00" in exceed and "Djoukovo" not in exceed
    # Rien n'a été écrit.
    assert (await _get(client, h, ctx))["cashVersion"] == 0
    async with AsyncSessionLocal() as db:
        from app.modules.zylo_liquid.models import ShiftReportCashLine

        assert (await db.execute(select(ShiftReportCashLine).where(ShiftReportCashLine.reportId == uuid.UUID(ctx["report"])))).scalars().all() == []


async def test_missing_unknown_duplicate_lines_and_missing_recount_and_confirmation(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100), _pump(200)])
    ghost = ctx["att"][5]  # n'a tenu aucune pompe
    lines = [_line(ctx, 0, "84000"), _line(ctx, 0, "84000"), {"userId": ghost, "attendantCountedAmount": "1", "managerRecountedAmount": "1"}]
    res = await _put(client, h, ctx, lines)
    assert res.status_code == 422
    codes = _detail_codes(res)
    assert "cash_line_duplicate" in codes and "cash_line_unknown" in codes and "cash_line_missing" in codes
    missing = next(d for d in res.json()["error"]["details"] if d["code"] == "cash_line_missing")
    assert "Saisissez la caisse de Gombang" in missing["message"] and "pompe N° 2" in missing["message"]
    # Recomptage absent + déductions vides sans confirmation nominative.
    bad = [{"userId": ctx["att"][0], "attendantCountedAmount": "84000"}, _line(ctx, 1, "168000")]
    res = await _put(client, h, ctx, bad, confirmed=[])
    got = {(d["rowKey"], d["code"]) for d in res.json()["error"]["details"]}
    assert (f"user:{ctx['att'][0]}", "recount_missing") in got and (f"user:{ctx['att'][1]}", "no_deduction_confirmation_missing") in got
    assert "Saisissez le montant recompté par vous pour Djouka" in next(d for d in res.json()["error"]["details"] if d["code"] == "recount_missing")["message"]


async def test_counts_differ_with_note_is_accepted_and_remitted_is_the_recount(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    res = await _put(client, h, ctx, [_line(ctx, 0, "84000", recounted="83900", note="Billet de 100 mal compté")])
    assert res.status_code == 200, res.text
    line = _by_user(res.json(), ctx, 0)
    assert D(line["remittedAmount"]) == D("83900") and line["countsMatch"] is False and D(line["varianceAmount"]) == D("-100")
    assert D(line["attendantCountedAmount"]) == D("84000") and D(line["managerRecountedAmount"]) == D("83900")


async def test_zero_remitted_with_positive_theoretical_is_accepted(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    res = await _put(client, h, ctx, [_line(ctx, 0, "0")])
    assert res.status_code == 200, res.text
    assert D(_by_user(res.json(), ctx, 0)["varianceAmount"]) == D("-84000")


# ---------------------------------------------------------------------------
# Relais : pompe partagée, répartition manuelle tracée, jamais estimée
# ---------------------------------------------------------------------------


async def test_shared_pump_without_index_is_not_computed_until_manually_shared(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    # Pompe 1 : Djouka puis Gombang SANS index intermédiaire ; pompe 2 : Djoukovo seul.
    cfg = [_pump("420.50", holders=(0, 1), starts=(None, None)), _pump(100, holders=(2,))]
    ctx = await _ctx(client, h, zylo_liquid_organization, cfg)
    view = await _get(client, h, ctx)
    a, b = _by_user(view, ctx, 0), _by_user(view, ctx, 1)
    assert a["salesState"] == "needs_share" and b["salesState"] == "needs_share" and a["salesValue"] is None and a["attributedLiters"] is None
    assert a["groupId"] == b["groupId"] == 1 and _by_user(view, ctx, 2)["groupId"] is None
    assert "Pompe N° 1 partagée" in a["salesMessage"]
    share = view["pumpShares"][0]
    assert share["needsShare"] is True and share["state"] == "needs_manual" and D(share["liters"]) == D("420.50") and all(hd["litersShare"] is None for hd in share["holders"])
    assert view["summary"]["hasUnresolvedPumps"] is True and any("Pompe N° 1 partagée" in w for w in view["warnings"])

    # Enregistrement permis (D16) : théorique et écart individuels « non calculés », écart de groupe exposé.
    pump1_value = (D("420.50") * D("840")).quantize(D("0.01"))
    group_variance = D("3348.12")
    group_remitted = pump1_value + group_variance
    lines = [_line(ctx, 0, "150000"), _line(ctx, 1, str(group_remitted - D("150000"))), _line(ctx, 2, "84000")]
    res = await _put(client, h, ctx, lines)
    assert res.status_code == 200, res.text
    view = res.json()
    a = _by_user(view, ctx, 0)
    assert a["theoreticalAmount"] is None and a["varianceAmount"] is None and a["varianceNature"] is None
    group = view["summary"]["groupVariances"][0]
    assert D(group["varianceAmount"]) == group_variance and D(group["theoreticalTotal"]) == pump1_value and set(group["userIds"]) == {ctx["att"][0], ctx["att"][1]}
    assert D(view["summary"]["notaSum"]) == D("0") and D(view["summary"]["groupVarianceSum"]) == group_variance and D(view["summary"]["notaTotal"]) == group_variance
    assert next(n for n in view["summary"]["notaLines"] if n["userId"] == ctx["att"][0])["calculated"] is False

    # Répartition manuelle : 200 + 200 ne fait pas 420,50 ; 200 + 220,50 est acceptée et tracée.
    pump_line_id = ctx["lines"][0]
    bad = await _put(client, h, ctx, lines, version=1, pump_shares=[{"pumpLineId": pump_line_id, "reason": "Répartition estimée par le chef d'équipe", "shares": [
        {"userId": ctx["att"][0], "litersShare": "200"}, {"userId": ctx["att"][1], "litersShare": "200"}]}])
    assert bad.status_code == 422 and "pump_share_sum_mismatch" in _detail_codes(bad)
    assert "ne font pas les 420,50 L de la Pompe N° 1" in _plain(next(d for d in bad.json()["error"]["details"] if d["code"] == "pump_share_sum_mismatch")["message"])
    no_reason = await _put(client, h, ctx, lines, version=1, pump_shares=[{"pumpLineId": pump_line_id, "reason": "court", "shares": [
        {"userId": ctx["att"][0], "litersShare": "200"}, {"userId": ctx["att"][1], "litersShare": "220.50"}]}])
    assert "pump_share_reason_missing" in _detail_codes(no_reason)
    stranger = await _put(client, h, ctx, lines, version=1, pump_shares=[{"pumpLineId": pump_line_id, "reason": "Répartition estimée par le chef d'équipe", "shares": [
        {"userId": ctx["att"][4], "litersShare": "420.50"}]}])
    assert "pump_share_user_not_holder" in _detail_codes(stranger)
    ok = await _put(client, h, ctx, lines, version=1, pump_shares=[{"pumpLineId": pump_line_id, "reason": "Répartition estimée par le chef d'équipe", "shares": [
        {"userId": ctx["att"][0], "litersShare": "200"}, {"userId": ctx["att"][1], "litersShare": "220.50"}]}])
    assert ok.status_code == 200, ok.text
    view = ok.json()
    a, b = _by_user(view, ctx, 0), _by_user(view, ctx, 1)
    assert D(a["attributedLiters"]) == D("200") and D(b["attributedLiters"]) == D("220.50")
    assert D(a["salesValue"]) + D(b["salesValue"]) == pump1_value and D(a["salesValue"]) == D("168000.00")
    assert D(a["varianceAmount"]) + D(b["varianceAmount"]) == group_variance and a["groupId"] is None
    assert view["pumpShares"][0]["needsShare"] is False and view["pumpShares"][0]["reason"] == "Répartition estimée par le chef d'équipe"
    assert view["summary"]["hasUnresolvedPumps"] is False and D(view["summary"]["notaSum"]) == group_variance
    async with AsyncSessionLocal() as db:
        from app.modules.zylo_liquid.models import ShiftReportPumpShare

        rows = (await db.execute(select(ShiftReportPumpShare).where(ShiftReportPumpShare.reportId == uuid.UUID(ctx["report"])))).scalars().all()
        assert len(rows) == 2 and all(r.source == "manual" and r.declaredByUserId is not None and r.reason for r in rows)
        entry = (await db.execute(select(AuditLog).where(AuditLog.organizationId == uuid.UUID(zylo_liquid_organization["id"]), AuditLog.action == "zyloLiquid.cashCollection.record").order_by(AuditLog.createdAt.desc()))).scalars().first()
    assert entry.changes["manualPumpShares"][0]["parts"][1]["liters"] == "220.50" and entry.changes["manualPumpShares"][0]["reason"]


async def test_relay_with_intermediate_index_is_attributed_automatically(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    # Pompe de 1 000 L ; Djouka de 1 000 à 1 300, Gombang de 1 300 à 2 000.
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(1000, price="0.3333", holders=(0, 1), starts=(None, "1300"))])
    view = await _get(client, h, ctx)
    a, b = _by_user(view, ctx, 0), _by_user(view, ctx, 1)
    assert a["salesState"] == "calculated" and D(a["attributedLiters"]) == D("300") and D(b["attributedLiters"]) == D("700")
    assert D(a["salesValue"]) + D(b["salesValue"]) == D("333.30") and a["pumps"][0]["state"] == "segment_index" and a["pumps"][0]["shared"] is True
    assert view["pumpShares"][0]["needsShare"] is False
    # Une répartition manuelle n'est pas acceptée quand l'attribution est automatique (jamais deux sources).
    res = await _put(client, h, ctx, [_line(ctx, 0, "99.99"), _line(ctx, 1, "233.31")], pump_shares=[
        {"pumpLineId": ctx["lines"][0], "reason": "Répartition estimée par le chef d'équipe", "shares": [{"userId": ctx["att"][0], "litersShare": "500"}, {"userId": ctx["att"][1], "litersShare": "500"}]}])
    assert res.status_code == 422 and "pump_share_not_needed" in _detail_codes(res)
    ok = await _put(client, h, ctx, [_line(ctx, 0, "99.99"), _line(ctx, 1, "233.31")])
    assert ok.status_code == 200 and all(D(l["varianceAmount"]) == 0 for l in ok.json()["lines"])


async def test_pump_with_exits_needs_a_manual_share_even_with_indexes(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(990, price="1", holders=(0, 1), starts=(None, "1300"), exits=D("10"))])
    view = await _get(client, h, ctx)
    assert _by_user(view, ctx, 0)["salesState"] == "needs_share" and view["pumpShares"][0]["state"] == "needs_manual"


async def test_price_missing_gives_a_not_calculated_theoretical_not_an_invented_one(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100, price=None)])
    view = await _get(client, h, ctx)
    line = _by_user(view, ctx, 0)
    assert line["salesState"] == "price_missing" and line["salesValue"] is None and "Aucun prix en vigueur" in line["salesMessage"]
    res = await _put(client, h, ctx, [_line(ctx, 0, "5000")])
    assert res.status_code == 200 and _by_user(res.json(), ctx, 0)["theoreticalAmount"] is None and _by_user(res.json(), ctx, 0)["varianceAmount"] is None


async def test_team_lead_replacement_is_marked(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    from app.modules.zylo_liquid.models import ShiftPumpAssignment

    async with AsyncSessionLocal() as db:
        seg = (await db.execute(select(ShiftPumpAssignment).where(ShiftPumpAssignment.reportId == uuid.UUID(ctx["report"])))).scalars().one()
        seg.holderIsTeamLead = True
        await db.commit()
    assert _by_user(await _get(client, h, ctx), ctx, 0)["roleMarker"] == "team_lead"


# ---------------------------------------------------------------------------
# Rature, verrou optimiste, « à recalculer »
# ---------------------------------------------------------------------------


async def test_rature_is_required_to_change_a_saved_value_and_keeps_the_old_one(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    assert (await _put(client, h, ctx, [_line(ctx, 0, "84000")])).status_code == 200
    # Valeur inchangée : pas de rature.
    assert (await _put(client, h, ctx, [_line(ctx, 0, "84000", note="Relu")], version=1)).status_code == 200
    # Valeur changée sans rature : refus.
    res = await _put(client, h, ctx, [_line(ctx, 0, "84100", recounted="84100")], version=2)
    assert res.status_code == 422 and "rature_reason_missing" in _detail_codes(res)
    assert "motif de la correction" in next(d for d in res.json()["error"]["details"] if d["code"] == "rature_reason_missing")["message"]
    # « Autre » exige une précision ; un « paraphé par » inconnu est refusé.
    res = await _put(client, h, ctx, [_line(ctx, 0, "84100", rature={"reasonCode": "other", "initialedByUserId": ctx["att"][0]})], version=2)
    assert "rature_note_missing" in _detail_codes(res)
    res = await _put(client, h, ctx, [_line(ctx, 0, "84100", rature={"reasonCode": "count_error", "initialedByUserId": str(uuid.uuid4())})], version=2)
    assert "rature_initialed_by_unknown" in _detail_codes(res)
    ok = await _put(client, h, ctx, [_line(ctx, 0, "84100", rature={"reasonCode": "count_error", "initialedByUserId": ctx["att"][0]})], version=2)
    assert ok.status_code == 200, ok.text
    assert D(_by_user(ok.json(), ctx, 0)["varianceAmount"]) == D("100") and ok.json()["cashVersion"] == 3
    async with AsyncSessionLocal() as db:
        from app.modules.zylo_liquid.models import ShiftReportCashLineCorrection

        rows = (await db.execute(select(ShiftReportCashLineCorrection).where(ShiftReportCashLineCorrection.reportId == uuid.UUID(ctx["report"])))).scalars().all()
    assert {(r.field, D(str(r.oldValue)), D(str(r.newValue)), r.reasonCode) for r in rows} == {
        ("attendantCountedAmount", D("84000"), D("84100"), "count_error"), ("managerRecountedAmount", D("84000"), D("84100"), "count_error"),
    }
    assert all(r.initialedByUserId == uuid.UUID(ctx["att"][0]) and r.cashVersion == 3 for r in rows)


async def test_stale_cash_version_is_a_409_with_the_author_name(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    assert (await _put(client, h, ctx, [_line(ctx, 0, "84000")])).status_code == 200
    res = await _put(client, h, ctx, [_line(ctx, 0, "84000")], version=0)
    assert res.status_code == 409 and res.json()["error"]["code"] == "cash_version_changed"
    assert "La caisse a été modifiée par" in res.json()["error"]["message"] and "Rechargez" in res.json()["error"]["message"]


async def test_closing_version_change_marks_lines_to_recalculate_and_keeps_counts(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    assert (await _put(client, h, ctx, [_line(ctx, 0, "84000")])).status_code == 200
    from app.modules.zylo_liquid.models import ShiftReport, ShiftReportPumpLine

    async with AsyncSessionLocal() as db:
        report = await db.get(ShiftReport, uuid.UUID(ctx["report"]))
        report.closingVersion = 2
        line = await db.get(ShiftReportPumpLine, uuid.UUID(ctx["lines"][0]))
        line.soldLiters, line.amount, line.closingIndex = D("110"), D("92400.00"), OPENING + 110
        await db.commit()
    view = await _get(client, h, ctx)
    line = _by_user(view, ctx, 0)
    assert line["needsRecalculation"] is True and D(line["attendantCountedAmount"]) == D("84000") and D(line["currentSalesValue"]) == D("92400")
    assert D(line["theoreticalAmount"]) == D("84000") and view["summary"]["hasStaleLines"] is True and any("à recalculer" in w for w in view["warnings"])
    # Ré-enregistrer sans changer les valeurs ne demande pas de rature et recalcule.
    ok = await _put(client, h, ctx, [_line(ctx, 0, "84000")], version=1)
    assert ok.status_code == 200
    assert _by_user(ok.json(), ctx, 0)["needsRecalculation"] is False and D(_by_user(ok.json(), ctx, 0)["varianceAmount"]) == D("-8400")


# ---------------------------------------------------------------------------
# Verrous, événement, audit
# ---------------------------------------------------------------------------


async def test_locks_before_assignment_closing_and_when_the_shift_is_not_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)], confirm=False)
    view = await _get(client, h, ctx)
    assert view["access"]["locked"] is True and view["access"]["lockedCode"] == "assignment_not_confirmed" and view["access"]["canManage"] is False
    res = await _put(client, h, ctx, [_line(ctx, 0, "84000")])
    assert res.status_code == 409 and res.json()["error"]["code"] == "assignment_not_confirmed"
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)], phase="open")
    assert (await _get(client, h, ctx))["access"]["lockedCode"] == "closing_not_recorded"
    res = await _put(client, h, ctx, [_line(ctx, 0, "84000")])
    assert res.status_code == 409 and res.json()["error"]["code"] == "closing_not_recorded" and "section 1" in res.json()["error"]["message"]
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)], status="closed")
    assert (await _get(client, h, ctx))["access"]["lockedCode"] == "report_not_open"
    res = await _put(client, h, ctx, [_line(ctx, 0, "84000")])
    assert res.status_code == 409 and res.json()["error"]["code"] == "report_not_open"


async def test_recording_publishes_the_event_after_commit_and_writes_an_audit_entry(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100), _pump(200)])
    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("CashCollectionRecorded", handler)
    try:
        res = await _put(client, h, ctx, [_line(ctx, 0, "84100"), _line(ctx, 1, "167900")])
    finally:
        events._handlers["CashCollectionRecorded"].remove(handler)
    assert res.status_code == 200, res.text
    assert len(received) == 1 and received[0]["lines"] == 2 and received[0]["totalRemitted"] == "252000.00" and received[0]["notaSum"] == "0.00"
    async with AsyncSessionLocal() as db:
        entry = (await db.execute(select(AuditLog).where(AuditLog.organizationId == uuid.UUID(zylo_liquid_organization["id"]), AuditLog.action == "zyloLiquid.cashCollection.record"))).scalars().one()
    assert entry.changes["lines"] == 2 and entry.changes["totalRemitted"] == "252000.00" and len(entry.changes["rows"]) == 2


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------


async def test_team_lead_has_no_access_auditor_reads_only_and_shift_manager_writes(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(100)])
    url = f"{BASE}/shift-reports/{ctx['report']}/closing-cash"
    team_lead = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_team_lead", ctx["station"])
    assert (await client.get(url, headers={k: v for k, v in team_lead.items() if k != "_user"})).status_code == 403
    auditor = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_auditor", ctx["station"])).items() if k != "_user"}
    assert (await client.get(url, headers=auditor)).status_code == 200
    body = {"cashVersion": 0, "lines": [_line(ctx, 0, "84000")], "confirmedNoDeductions": [ctx["att"][0]]}
    assert (await client.put(url, json=body, headers=auditor)).status_code == 403
    manager = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])).items() if k != "_user"}
    saved = await client.put(url, json=body, headers=manager)
    assert saved.status_code == 200, saved.text
    assert saved.json()["access"]["canManage"] is True
    attendant = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_pump_attendant", ctx["station"])).items() if k != "_user"}
    assert (await client.get(url, headers=attendant)).status_code == 403


async def test_cash_collection_default_role_matrix():
    from app.modules.zylo_liquid.permissions import CASH_COLLECTION_MANAGE, CASH_COLLECTION_READ
    from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES

    by_code = {code: set(perms) for code, _name, perms in DEFAULT_ROLES}
    assert CASH_COLLECTION_READ == "zyloLiquid.cashCollection.read" and CASH_COLLECTION_MANAGE == "zyloLiquid.cashCollection.manage"
    for writer in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        assert {CASH_COLLECTION_READ, CASH_COLLECTION_MANAGE} <= by_code[writer], writer
    assert by_code["zylo_liquid_shift_manager"] & {CASH_COLLECTION_READ, CASH_COLLECTION_MANAGE} <= by_code["zylo_liquid_station_admin"]
    for reader in ("zylo_liquid_auditor", "zylo_liquid_cashier"):
        assert CASH_COLLECTION_READ in by_code[reader] and CASH_COLLECTION_MANAGE not in by_code[reader], reader
    for none in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant"):
        assert not by_code[none] & {CASH_COLLECTION_READ, CASH_COLLECTION_MANAGE}, none
