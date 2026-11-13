"""Scénario D5 (calcul de la caisse A à H et du NOTA) : formules pures (PC-02, PC-03, PC-06), jeu de test SOCADA exact
(A 8 628 627,72 ; B 7 655 624 ; C 973 003,72 ; dépenses 247 125 ; D 600 000 ; E 1 325 878,72 ; F 1 329 000 ; H +3 121,28 ; NOTA
+3 121,25, écart 0,03 dans la tolérance), « non disponible » plutôt qu'un zéro inventé, enregistrement tout-ou-rien avec erreurs
par cellule `cash_summary_invalid`, verrou optimiste, règle PC-03 avec motif, propositions `Payment` (un paiement ne compte qu'une
fois), audit, événement et droits (chef d'équipe sans accès).

Le tour, D1 et D3 sont posés comme dans les tests D3 ; les cumuls des rubriques 2 à 7 (D4) sont fournis par un adaptateur
remplacé (`_d5_d4_totals`) pour les tests de formule, et par les VRAIES rubriques D4 dans le test d'intégration final."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal

from app.shared import events
from tests.test_zylo_liquid_cash_collection import _ctx, _headers, _line, _post, _pump, _put as _put_cash, _scoped_user
from app.modules.zylo_liquid.exploitation.alg_caisse import CASH_FORMULA_VERSION, CASH_SUMMARY_SAVED_EVENT, cash_gap_nature, compute_cash_summary, compute_nota_difference
from app.modules.zylo_liquid.exploitation import caisse_calcul as caisse_calcul

BASE = "/api/v1/zylo-liquid"
D = Decimal

# --- Jeu SOCADA du 16/08/2026 ---
SOCADA_RUBRICS = {2: D("65500"), 3: D("0"), 4: D("181625"), 5: D("6611151"), 6: D("0"), 7: D("1044473")}
SOCADA_P_B = D("8381502.72")
# Écarts par pompiste (NOTA) et remises : Σ remis = 1 329 000, Σ écarts = +3 121,25.
VARIANCES = [D("730.32"), D("2617.80"), D("358.61"), D("-757.20"), D("303.68"), D("-131.96")]
REMITTED = [D("221000"), D("221500"), D("221500"), D("221500"), D("221750"), D("221750")]
SALES = [D("1400000")] * 5 + [D("1381502.72")]  # Σ = 8 381 502,72 (CUMUL P.B.)


def _fake_d4(values: dict):
    async def fake(db, report):
        return {n: values.get(n) for n in range(2, 8)}

    return fake


async def _socada(client, h, organization, monkeypatch, rubrics=None, with_d3=True) -> dict:
    """Tour SOCADA : D1 (6 pompes à prix 1, Σ = 8 381 502,72), D3 (6 pompistes, Σ remis 1 329 000) et rubriques 2 à 7 simulées."""
    monkeypatch.setattr(caisse_calcul, "_d5_d4_totals", _fake_d4(SOCADA_RUBRICS if rubrics is None else rubrics))
    ctx = await _ctx(client, h, organization, [_pump(str(s), price="1") for s in SALES])
    if with_d3:
        lines = []
        for i in range(6):
            theoretical = REMITTED[i] - VARIANCES[i]
            lines.append(_line(ctx, i, str(REMITTED[i]), credit=str(SALES[i] - theoretical)))
        res = await _put_cash(client, h, ctx, lines)
        assert res.status_code == 200, res.text
        assert D(res.json()["summary"]["notaSum"]) == D("3121.25")
    return ctx


def _url(ctx, suffix="cash-summary"):
    return f"{BASE}/shift-reports/{ctx['report']}/{suffix}"


def _expense(label="Carburant du groupe", amount="20 000,00", receipt="Reçu n° 77", note=None):
    return {"label": label, "amount": amount, "receiptReference": receipt, "note": note}


def _settlement(amount="600000", mode="cash", reference="PM SCT", label="SCT", account=None, payment=None):
    return {"commercialAccountId": account, "payerLabel": None if account else label, "amount": amount, "mode": mode, "reference": reference, "paymentId": payment}


def _body(version=0, expenses=None, settlements=None, deduct=True, note=None, **extra):
    return {"inputsVersion": version, "deductRetainedSales": deduct, "deductRetainedSalesNote": note, "expenses": expenses or [], "settlements": settlements or [], **extra}


async def _save(client, h, ctx, **kwargs):
    return await client.put(_url(ctx, "cash-adjustments"), json=_body(**kwargs), headers=h)


def _line_of(view, letter):
    return next(l for l in view["lines"] if l["letter"] == letter)


# ---------------------------------------------------------------------------
# Formules pures
# ---------------------------------------------------------------------------


def _calc(**override):
    base = dict(
        products_a1=SOCADA_P_B, lubricants_a2=D("65500"), gas_a3=D("0"), shop_a4=D("181625"), credits_b5=D("6611151"), value_vouchers_b6=D("0"),
        electronic_b7=D("1044473"), deduct_retained_sales=True, manual_expenses=[], settlements=[D("600000")], handover_f=D("1329000"),
    )
    base.update(override)
    return compute_cash_summary(**base)


def test_socada_chain_from_a_to_h():
    r = _calc()
    assert r["A"] == D("8628627.72") and r["B"] == D("7655624") and r["C"] == D("973003.72")
    assert r["expensesTotal"] == D("247125") and r["D"] == D("600000")
    assert r["E"] == D("1325878.72") and r["F"] == D("1329000") and r["H"] == D("3121.28")
    assert cash_gap_nature(r["H"]) == "surplus" and CASH_FORMULA_VERSION == "c_minus_expenses_plus_d"


def test_printed_formula_e_equals_g_plus_c_does_not_match_the_real_report():
    """Non-régression PC-02 : E = G + C avec G = B donne E = A = 8 628 627,72, qui n'est PAS le 1 325 878,72 lu sur le rapport."""
    r = _calc()
    assert r["B"] + r["C"] == r["A"] == D("8628627.72") != r["E"]


def test_retained_sales_rule_off_changes_e_and_h():
    r = _calc(deduct_retained_sales=False)
    assert r["expensesTotal"] == D("0") and r["E"] == D("1573003.72") and r["H"] == D("-244003.72")


def test_manual_expenses_are_added_to_the_computed_ones():
    r = _calc(manual_expenses=[D("20000")])
    assert r["expensesTotal"] == D("267125") and r["E"] == D("1305878.72") and r["H"] == D("23121.28")


def test_missing_rubric_makes_the_dependent_values_unavailable_never_zero():
    r = _calc(gas_a3=None)
    assert r["A"] is None and r["C"] is None and r["E"] is None and r["H"] is None
    assert r["B"] == D("7655624") and r["missing"]["A"] == ["rubric3"]
    no_handover = _calc(handover_f=None)
    assert no_handover["F"] is None and no_handover["H"] is None and no_handover["E"] == D("1325878.72")
    off_missing = _calc(lubricants_a2=None, deduct_retained_sales=False, products_a1=D("1"), gas_a3=D(0), shop_a4=D(0))
    assert off_missing["A"] is None  # la rubrique 2 manque toujours pour A, même sans déduction


def test_nota_tolerance_boundary_is_inclusive_and_never_adjusted():
    h = D("3121.28")
    assert compute_nota_difference(D("3121.25"), h) == {"difference": D("-0.03"), "withinTolerance": True}
    assert compute_nota_difference(D("3122.28"), h)["withinTolerance"] is True  # différence 1,00 : acceptée
    assert compute_nota_difference(D("3122.29"), h)["withinTolerance"] is False  # 1,01 : refusée
    assert compute_nota_difference(D("3100.00"), h)["withinTolerance"] is False
    assert compute_nota_difference(None, h) == {"difference": None, "withinTolerance": None}


# ---------------------------------------------------------------------------
# SOCADA de bout en bout
# ---------------------------------------------------------------------------


async def test_socada_cash_summary_end_to_end(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    before = await client.get(_url(ctx), headers=h)
    assert before.status_code == 200, before.text
    v = before.json()
    assert v["inputsVersion"] == 0 and v["access"]["canManage"] is True and v["access"]["locked"] is False and v["formulaVersion"] == "c_minus_expenses_plus_d"
    assert D(v["totals"]["A"]) == D("8628627.72") and D(v["totals"]["B"]) == D("7655624.00") and D(v["totals"]["C"]) == D("973003.72")
    assert D(v["totals"]["expensesTotal"]) == D("247125") and D(v["totals"]["F"]) == D("1329000")
    assert D(v["totals"]["D"]) == D("0")  # aucun règlement saisi : D vaut 0 mais le RT n'a rien confirmé (E, H provisoires de ce fait)
    assert [e["origin"] for e in v["expenses"]] == ["computed", "computed"] and D(v["expenses"][0]["amount"]) == D("65500")

    res = await _save(client, h, ctx, settlements=[_settlement()])
    assert res.status_code == 200, res.text
    v = res.json()
    t = v["totals"]
    assert v["inputsVersion"] == 1
    assert D(t["A"]) == D("8628627.72") and D(t["B"]) == D("7655624") and D(t["C"]) == D("973003.72") and D(t["expensesTotal"]) == D("247125")
    assert D(t["D"]) == D("600000") and D(t["E"]) == D("1325878.72") and D(t["F"]) == D("1329000") and D(t["H"]) == D("3121.28") and t["cashGapNature"] == "surplus"
    assert [c["label"] for c in _line_of(v, "A")["components"]] == ["Produits blancs", "Lubrifiants", "Gaz", "Boutique"]
    assert _line_of(v, "E")["formula"] == "C − dépenses diverses + D" and _line_of(v, "F")["state"] == "from_d3" and _line_of(v, "D")["state"] == "entered"
    nota = v["nota"]
    assert nota["state"] == "calculated" and D(nota["notaSum"]) == D("3121.25") and D(nota["notaTotal"]) == D("3121.25")
    assert D(nota["gapH"]) == D("3121.28") and D(nota["difference"]) == D("-0.03") and nota["withinTolerance"] is True and D(nota["toleranceAmount"]) == D("1.00")
    assert [l["fullName"].split()[0] for l in nota["lines"]] == ["Djouka", "Gombang", "Djoukovo", "Ella", "Wenpiep", "Fotie"]
    assert D(nota["lines"][3]["varianceAmount"]) == D("-757.20") and v["complete"] is True
    assert {a["code"] for a in v["assumptions"]} >= {"formulaE", "formulaB", "retainedSalesRule", "settlementsSource", "handoverSource", "notaRule", "notaTolerance", "rounding"}
    assert v["settlements"][0]["payerName"] == "SCT" and v["settlements"][0]["modeLabel"] == "Espèces" and v["settlements"][0]["reference"] == "PM SCT"

    # Fonction publique pour D6 : même calcul, aucune persistance.
    async with AsyncSessionLocal() as db:
        pub = await caisse_calcul.get_shift_cash_summary(db, uuid.UUID(ctx["report"]))
    assert pub.totals.H == D("3121.28") and pub.nota.withinTolerance is True and pub.access.canManage is False


async def test_client_values_for_computed_fields_are_ignored(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    res = await _save(client, h, ctx, settlements=[_settlement()], A="1", E="2", totals={"H": "999"}, notaSum="5")
    assert res.status_code == 200, res.text
    assert D(res.json()["totals"]["E"]) == D("1325878.72") and D(res.json()["totals"]["H"]) == D("3121.28")


async def test_nota_out_of_tolerance_is_flagged_and_never_adjusted(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    res = await _save(client, h, ctx, settlements=[_settlement("599000")])
    nota = res.json()["nota"]
    assert D(res.json()["totals"]["H"]) == D("4121.28") and D(nota["notaTotal"]) == D("3121.25")  # le NOTA n'a pas bougé
    assert nota["withinTolerance"] is False and D(nota["difference"]) == D("-1000.03")
    assert "ne correspond pas à l'écart de caisse" in nota["message"] and "+3 121,25" in nota["message"].replace(" ", " ").replace("\xa0", " ")


async def test_rule_pc03_off_needs_a_note_then_changes_e_and_h(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    bad = await _save(client, h, ctx, settlements=[_settlement()], deduct=False, note="court")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "cash_summary_invalid"
    assert [(d["rowKey"], d["field"], d["code"]) for d in bad.json()["error"]["details"]] == [("rule", "deductRetainedSalesNote", "retained_note_missing")]
    ok = await _save(client, h, ctx, settlements=[_settlement()], deduct=False, note="La boutique a sa propre caisse")
    assert ok.status_code == 200, ok.text
    v = ok.json()
    assert D(v["totals"]["E"]) == D("1573003.72") and D(v["totals"]["H"]) == D("-244003.72") and v["deductRetainedSales"] is False
    assert [e["origin"] for e in v["expenses"]] == [] and v["nota"]["withinTolerance"] is False
    assert any("désactivée" in w for w in v["warnings"])
    async with AsyncSessionLocal() as db:
        entry = (await db.execute(select(AuditLog).where(AuditLog.action == "zyloLiquid.cashSummary.record", AuditLog.entityId == uuid.UUID(ctx["report"])))).scalars().one()
    assert entry.changes["deductRetainedSales"] is False and entry.changes["deductRetainedSalesNote"] == "La boutique a sa propre caisse" and entry.changes["H"] == "-244003.72"


# ---------------------------------------------------------------------------
# Données manquantes : « non disponible », jamais un zéro
# ---------------------------------------------------------------------------


async def test_missing_rubric_and_missing_d3_are_unavailable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    rubrics = {k: v for k, v in SOCADA_RUBRICS.items() if k != 3}  # rubrique 3 non commencée
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch, rubrics=rubrics, with_d3=False)
    v = (await client.get(_url(ctx), headers=h)).json()
    t = v["totals"]
    assert t["A"] is None and t["C"] is None and t["E"] is None and t["H"] is None and t["F"] is None and v["complete"] is False
    assert D(t["B"]) == D("7655624")
    a = _line_of(v, "A")
    assert a["state"] == "unavailable" and a["provisional"] is True and "Rubrique 3 (gaz)" in a["message"]
    assert "Le comptage des pompistes (D3) n'est pas fait" in _line_of(v, "F")["message"]
    assert v["nota"]["state"] == "unavailable" and v["nota"]["message"] == "Aucun comptage par pompiste : le NOTA ne peut pas être établi." and v["nota"]["notaSum"] is None
    # L'enregistrement des dépenses et règlements reste possible.
    assert (await _save(client, h, ctx, settlements=[_settlement()])).status_code == 200


# ---------------------------------------------------------------------------
# Tout-ou-rien, erreurs par cellule, version
# ---------------------------------------------------------------------------


async def test_all_or_nothing_with_cell_errors_in_french(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    res = await _save(
        client, h, ctx,
        expenses=[_expense(receipt=None), _expense(label=" ", amount="0"), _expense(amount="abc")],
        settlements=[_settlement(), _settlement(label=None, reference=" ", mode="virement", amount="-3"), _settlement(account=str(uuid.uuid4()))],
    )
    assert res.status_code == 422 and res.json()["error"]["code"] == "cash_summary_invalid", res.text
    details = res.json()["error"]["details"]
    got = {(d["key"], d["code"]) for d in details}
    assert ("cash:expense:1:receiptReference", "receipt_missing") in got
    assert ("cash:expense:2:label", "label_missing") in got and ("cash:expense:2:amount", "amount_invalid") in got
    assert ("cash:expense:3:amount", "amount_invalid") in got
    assert ("cash:settlement:2:payerLabel", "payer_missing") in got and ("cash:settlement:2:reference", "reference_missing") in got
    assert ("cash:settlement:2:mode", "mode_invalid") in got and ("cash:settlement:2:amount", "amount_invalid") in got
    assert ("cash:settlement:3:commercialAccountId", "account_not_found") in got
    messages = {d["code"]: d["message"] for d in details}
    assert messages["receipt_missing"] == "Indiquez le n° du reçu ou précisez pourquoi il n'y en a pas (note)."
    assert messages["payer_missing"] == "Choisissez le client ou saisissez de qui vient ce règlement."
    assert "cellule(s) à corriger : rien n'a été enregistré" in res.json()["error"]["message"]
    # Rien d'écrit, même la ligne valide.
    after = (await client.get(_url(ctx), headers=h)).json()
    assert after["inputsVersion"] == 0 and after["settlements"] == [] and D(after["totals"]["D"]) == D("0")


async def test_expense_without_receipt_is_accepted_with_a_note_and_counted(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    res = await _save(client, h, ctx, expenses=[_expense(receipt=None, note="Pas de reçu : réparation au marché")], settlements=[_settlement()])
    assert res.status_code == 200, res.text
    v = res.json()
    assert D(v["totals"]["expensesTotal"]) == D("267125") and D(v["totals"]["E"]) == D("1305878.72") and D(v["totals"]["H"]) == D("23121.28")
    assert [e["origin"] for e in v["expenses"]] == ["computed", "computed", "manual"] and v["expenses"][2]["note"].startswith("Pas de reçu")


async def test_stale_version_gives_409_and_report_must_be_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    assert (await _save(client, h, ctx, settlements=[_settlement()])).status_code == 200
    stale = await _save(client, h, ctx, version=0, settlements=[_settlement("1")])
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "cash_inputs_version_changed"
    assert stale.json()["error"]["message"].startswith("Ces montants ont été modifiés par ") and "Rechargez" in stale.json()["error"]["message"]
    fresh = await _save(client, h, ctx, version=1, settlements=[_settlement("700000")])
    assert fresh.status_code == 200 and fresh.json()["inputsVersion"] == 2 and D(fresh.json()["totals"]["D"]) == D("700000")
    # Tour plus ouvert : lecture seule.
    from app.modules.zylo_liquid.models import ShiftOccurrence, ShiftReport

    async with AsyncSessionLocal() as db:
        report = await db.get(ShiftReport, uuid.UUID(ctx["report"]))
        (await db.get(ShiftOccurrence, report.occurrenceId)).status = "closed"
        await db.commit()
    locked = await _save(client, h, ctx, version=2, settlements=[_settlement()])
    assert locked.status_code == 409 and locked.json()["error"]["code"] == "report_not_open"
    view = (await client.get(_url(ctx), headers=h)).json()
    assert view["access"]["locked"] is True and view["access"]["canManage"] is False and view["proposals"] == []


async def test_event_is_published_after_commit(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    received = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe(CASH_SUMMARY_SAVED_EVENT, handler)
    try:
        assert (await _save(client, h, ctx, settlements=[_settlement()])).status_code == 200
    finally:
        events._handlers[CASH_SUMMARY_SAVED_EVENT].remove(handler)
    assert len(received) == 1 and received[0]["H"] == "3121.28" and received[0]["E"] == "1325878.72" and received[0]["reportId"] == uuid.UUID(ctx["report"])


# ---------------------------------------------------------------------------
# Propositions depuis les Payment : un paiement ne compte qu'une fois
# ---------------------------------------------------------------------------


async def _make_payment(client, h, ctx, organization, paid_at) -> dict:
    """Vente à crédit de la station + créance + paiement posés en base (jamais créés ni modifiés par D5)."""
    from app.modules.zylo_liquid.models import CommercialAccount, Payment, Receivable, Sale
    from app.shared.currency import Currency

    suffix = uuid.uuid4().hex[:6]
    product = (await _post(client, h, "/fuel-products", {"name": f"GasoilD5{suffix}", "code": f"G{suffix}"}))["id"]
    async with AsyncSessionLocal() as db:
        currency = (await db.execute(select(Currency).limit(1))).scalars().first()
        if currency is None:
            currency = Currency(code="XAF", name="Franc CFA", symbol="F", decimalPlaces=0)
            db.add(currency)
            await db.flush()
        account = CommercialAccount(organizationId=uuid.UUID(organization["id"]), name=f"Client D5 {suffix}", currencyId=currency.id, creditLimit=1000000, active=True)
        db.add(account)
        await db.flush()
        sale = Sale(
            stationId=uuid.UUID(ctx["station"]), authorUserId=uuid.UUID(ctx["rt"]), eventAt=paid_at, fuelProductId=uuid.UUID(product), quantityLiters=100, priceAmount=1500,
            currencyId=currency.id, paymentMethod="credit", commercialAccountId=account.id,
        )
        db.add(sale)
        await db.flush()
        receivable = Receivable(commercialAccountId=account.id, saleId=sale.id, amount=150000, currencyId=currency.id, status="open")
        db.add(receivable)
        await db.flush()
        payment = Payment(receivableId=receivable.id, authorUserId=uuid.UUID(ctx["rt"]), paidAt=paid_at, amount=150000, currencyId=currency.id, method="cash")
        db.add(payment)
        await db.commit()
        return {"payment": str(payment.id), "account": str(account.id), "accountName": account.name}


async def test_payment_proposals_are_listed_accepted_and_counted_once(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    paid_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)  # dans la fenêtre du tour (ouvert depuis 3 h)
    pay = await _make_payment(client, h, ctx, zylo_liquid_organization, paid_at)
    view = (await client.get(_url(ctx), headers=h)).json()
    assert [p["paymentId"] for p in view["proposals"]] == [pay["payment"]] and D(view["proposals"][0]["amount"]) == D("150000") and view["proposals"][0]["accountName"] == pay["accountName"]
    assert any("proposé" in w for w in view["warnings"])  # D vaut 0 tant qu'aucun règlement n'est saisi : avertissement, jamais un 0 silencieux

    accepted = await _save(client, h, ctx, settlements=[_settlement("150000", reference="Paiement 09:12", account=pay["account"], payment=pay["payment"])])
    assert accepted.status_code == 200, accepted.text
    v = accepted.json()
    assert v["proposals"] == [] and v["settlements"][0]["origin"] == "payment" and v["settlements"][0]["payerName"] == pay["accountName"] and D(v["totals"]["D"]) == D("150000")

    # Même paiement ajouté deux fois dans le même envoi : refusé.
    twice = await _save(client, h, ctx, version=1, settlements=[_settlement("1", account=pay["account"], payment=pay["payment"]), _settlement("2", account=pay["account"], payment=pay["payment"])])
    assert twice.status_code == 422 and "payment_already_counted" in {d["code"] for d in twice.json()["error"]["details"]}

    # Repris par un AUTRE rapport : « déjà compté dans le rapport du … ».
    other = await _socada(client, h, zylo_liquid_organization, monkeypatch, with_d3=False)
    counted = await _save(client, h, other, settlements=[_settlement("1", payment=pay["payment"])])
    assert counted.status_code == 422
    detail = next(d for d in counted.json()["error"]["details"] if d["code"] == "payment_already_counted")
    assert detail["key"] == "cash:settlement:1:paymentId" and detail["message"].startswith("Ce paiement est déjà compté dans le rapport du ")
    # Un paiement inconnu de cette station est introuvable.
    unknown = await _save(client, h, other, settlements=[_settlement("1", payment=str(uuid.uuid4()))])
    assert unknown.status_code == 422 and "payment_not_found" in {d["code"] for d in unknown.json()["error"]["details"]}


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------


async def test_cash_summary_permissions_and_default_role_matrix(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, monkeypatch):
    from app.modules.zylo_liquid.permissions import CASH_SUMMARY_MANAGE, CASH_SUMMARY_READ
    from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES

    assert CASH_SUMMARY_READ == "zyloLiquid.cashSummary.read" and CASH_SUMMARY_MANAGE == "zyloLiquid.cashSummary.manage"
    by_code = {code: set(perms) for code, _name, perms in DEFAULT_ROLES}
    for writer in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        assert {CASH_SUMMARY_READ, CASH_SUMMARY_MANAGE} <= by_code[writer], writer
    assert by_code["zylo_liquid_shift_manager"] & {CASH_SUMMARY_READ, CASH_SUMMARY_MANAGE} <= by_code["zylo_liquid_station_admin"]  # gérant ⊇ RT
    assert CASH_SUMMARY_READ in by_code["zylo_liquid_auditor"] and CASH_SUMMARY_MANAGE not in by_code["zylo_liquid_auditor"]
    for none in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant"):
        assert not by_code[none] & {CASH_SUMMARY_READ, CASH_SUMMARY_MANAGE}, none

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _socada(client, h, zylo_liquid_organization, monkeypatch)
    manager = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])).items() if k != "_user"}
    assert (await _save(client, manager, ctx, settlements=[_settlement()])).status_code == 200
    assert (await client.get(_url(ctx), headers=manager)).json()["access"]["canManage"] is True
    auditor = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_auditor", ctx["station"])).items() if k != "_user"}
    read = await client.get(_url(ctx), headers=auditor)
    assert read.status_code == 200 and read.json()["access"]["canManage"] is False
    assert (await _save(client, auditor, ctx, version=1, settlements=[_settlement()])).status_code == 403
    for role in ("zylo_liquid_team_lead", "zylo_liquid_pump_attendant"):
        user = {k: v for k, v in (await _scoped_user(client, h, zylo_liquid_organization, role, ctx["station"])).items() if k != "_user"}
        assert (await client.get(_url(ctx), headers=user)).status_code == 403, role
        assert (await _save(client, user, ctx, version=1, settlements=[_settlement()])).status_code == 403, role


# ---------------------------------------------------------------------------
# Intégration avec les VRAIES rubriques D4 (aucun adaptateur remplacé)
# ---------------------------------------------------------------------------


async def test_cash_summary_reads_the_real_d4_rubrics(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Rubriques non commencées = « non disponible » (jamais 0) ; barrée « RAS » = vrai 0 ; cumuls lus via `get_rubric_totals`."""
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, [_pump(str(s), price="1") for s in SALES])
    sections_url = f"{BASE}/shift-reports/{ctx['report']}/report-sections"
    start = (await client.get(_url(ctx), headers=h)).json()
    assert start["totals"]["A"] is None and start["totals"]["B"] is None and start["totals"]["expensesTotal"] is None  # rien n'est inventé à 0
    assert "Rubrique 2 (lubrifiants)" in _line_of(start, "A")["message"]

    body = {"sections": {
        "2": {"version": 0, "status": "ras"}, "3": {"version": 0, "status": "ras"}, "5": {"version": 0, "status": "ras"}, "6": {"version": 0, "status": "ras"},
        "4": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [{"amount": "181625"}]},
        "7": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [
            {"kind": "mobile", "operator": "orange_money", "amount": "1018973"}, {"kind": "mobile", "operator": "mtn_momo", "amount": "25500"},
        ]},
    }}
    saved = await client.put(sections_url, json=body, headers=h)
    assert saved.status_code == 200, saved.text
    v = (await client.get(_url(ctx), headers=h)).json()
    t = v["totals"]
    assert D(t["A"]) == D("8563127.72") and D(t["B"]) == D("1044473") and D(t["C"]) == D("7518654.72")  # 8 381 502,72 + 0 + 0 + 181 625
    assert D(t["expensesTotal"]) == D("181625")  # lubrifiants barrés RAS = 0 + boutique 181 625
    assert t["F"] is None and t["H"] is None and v["nota"]["state"] == "unavailable"
    assert [c["value"] for c in _line_of(v, "A")["components"]] == ["8381502.72", "0.00", "0.00", "181625.00"]
