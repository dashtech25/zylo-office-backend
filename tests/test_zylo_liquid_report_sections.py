"""Scénario D4 (rubriques 2 à 7 du rapport de tour : lubrifiants, gaz, boutique, crédits clients, bons valeur, paiements électroniques) :
brouillon sauvegardable jusqu'à la signature, saisie en lot TOUT-OU-RIEN (par rubrique et entre rubriques), cumuls recalculés par le serveur
(chiffres SOCADA : lubrifiants 65 500, boutique 181 625, crédits 6 611 151, mobile 1 044 473), erreurs 422 `shift_report_sections_invalid` par
cellule, 409 de version, rature paraphée, ouverture reportée du rapport précédent, aucune `Sale` ni `Receivable` créée, audit, événement, droits.

Le tour ouvert et son rapport (lignes de pompe) sont posés directement en base : D4 est testé indépendamment des endpoints d'ouverture."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditLog
from app.core.database import AsyncSessionLocal

from app.shared import events
from app.shared.currency import Currency
from app.modules.zylo_liquid.exploitation.alg_rapport import compute_gas_line, compute_lubricant_line, compute_value_vouchers, parse_count
from app.modules.zylo_liquid.exploitation import rapport_rubriques as rapport_rubriques

BASE = "/api/v1/zylo-liquid"
D = Decimal


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _ctx(client: AsyncClient, h: dict, organization: dict, status: str = "opened") -> dict:
    """Station, 2 produits (Super sur la pompe 1, Gas-oil sur la pompe 2), tour ouvert depuis 3 h, 3 comptes clients (plaques, chauffeurs)."""
    from app.modules.zylo_liquid.models import CommercialAccount, Driver, ShiftOccurrence, ShiftReport, ShiftReportPumpLine, Vehicle

    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station D4{suffix}", "code": f"E{suffix}"}))["id"]
    products, tanks, pumps = [], [], []
    for k, name in enumerate(("Super", "Gas-oil")):
        product = (await _post(client, h, "/fuel-products", {"name": f"{name}{suffix}", "code": f"{name[:2].upper()}{suffix}"}))
        products.append(product)
        tanks.append((await _post(client, h, "/tanks", {
            "stationId": station, "fuelProductId": product["id"], "tankNumber": k + 1, "displayName": f"Cuve {k + 1}", "capacityLiters": 20000,
            "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        }))["id"])
    rows = [{"rowNumber": i + 1, "tankId": tanks[i], "pumpNumber": i + 1} for i in range(2)]
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": rows}))["data"]]
    shift = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"},
    ]}))["data"][0]
    now = datetime.now(timezone.utc)
    opened_at = now - timedelta(hours=3)
    async with AsyncSessionLocal() as db:
        from app.identity.models import User

        rt = (await db.execute(select(User).limit(1))).scalars().first()
        currency = Currency(code=uuid.uuid4().hex[:3].upper(), name="Test", symbol="T", decimalPlaces=0)
        db.add(currency)
        await db.flush()
        local = opened_at.astimezone().replace(tzinfo=None)
        occurrence = ShiftOccurrence(
            stationId=uuid.UUID(station), shiftDefinitionId=uuid.UUID(shift["id"]), shiftDate=date.today(), shiftNumber=1, name="Journée",
            startTime="00:00", endTime="00:00", startsAt=local, endsAt=local + timedelta(days=1), status=status, openedAt=opened_at, openedByUserId=rt.id,
        )
        db.add(occurrence)
        await db.flush()
        report = ShiftReport(
            stationId=uuid.UUID(station), occurrenceId=occurrence.id, shiftDate=occurrence.shiftDate, shiftNumber=1, shiftName="Journée", startTime="00:00", endTime="00:00",
            responsibleUserId=rt.id, openedByUserId=rt.id, openedAt=opened_at,
        )
        db.add(report)
        await db.flush()
        lines = []
        for number, (pump_id, tank_id, product) in enumerate(zip(pumps, tanks, products), start=1):
            line = ShiftReportPumpLine(
                reportId=report.id, pumpId=uuid.UUID(pump_id), pumpNumber=number, pumpName=f"Pompe {number}", tankId=uuid.UUID(tank_id), fuelProductName=product["name"],
                openingIndex=Decimal("1000.00"), openingSource="initial",
            )
            db.add(line)
            await db.flush()
            lines.append(str(line.id))
        organization_id = uuid.UUID(organization["id"])
        accounts = []
        for name in ("SCT", "SGMV", "CUB"):
            account = CommercialAccount(organizationId=organization_id, name=f"{name}{suffix}", currencyId=currency.id, creditLimit=Decimal("10000000"), active=True)
            db.add(account)
            await db.flush()
            vehicle = Vehicle(commercialAccountId=account.id, plateOrReference=f"LT {suffix} A")
            driver = Driver(commercialAccountId=account.id, name=f"Ngo {name}")
            db.add_all([vehicle, driver])
            await db.flush()
            accounts.append({"id": str(account.id), "name": account.name, "vehicle": str(vehicle.id), "plate": vehicle.plateOrReference, "driver": str(driver.id)})
        inactive = CommercialAccount(organizationId=organization_id, name=f"OFF{suffix}", currencyId=currency.id, creditLimit=Decimal("1000"), active=False)
        db.add(inactive)
        await db.commit()
        report_id, occurrence_id, inactive_id, currency_id = str(report.id), str(occurrence.id), str(inactive.id), str(currency.id)
    return {
        "station": station, "report": report_id, "occurrence": occurrence_id, "lines": lines, "products": [p["id"] for p in products], "product_names": [p["name"] for p in products],
        "accounts": accounts, "inactive": inactive_id, "currency": currency_id, "suffix": suffix, "opened_at": opened_at,
    }


def _url(ctx) -> str:
    return f"{BASE}/shift-reports/{ctx['report']}/report-sections"


async def _get(client, h, ctx):
    res = await client.get(_url(ctx), headers=h)
    assert res.status_code == 200, res.text
    return res.json()


async def _put(client, h, ctx, sections):
    return await client.put(_url(ctx), json={"sections": sections}, headers=h)


def _section(view, number):
    return next(s for s in view["sections"] if s["sectionNumber"] == number)


def _cells(res) -> set:
    return {d["cell"] for d in res.json()["error"]["details"]}


def _codes(res) -> list:
    return [d["code"] for d in res.json()["error"]["details"]]


def _plain(text: str) -> str:
    return text.replace(" ", " ").replace("\xa0", " ")


def _served() -> str:
    return f"{date.today().isoformat()}T09:30:00"


def _voucher(ctx, number, amount, account=0, pump=0, signed=True, **extra):
    acc = ctx["accounts"][account]
    body = {
        "voucherNumber": number, "commercialAccountId": acc["id"], "vehicleId": acc["vehicle"], "driverId": acc["driver"], "fuelProductId": ctx["products"][pump],
        "pumpLineId": ctx["lines"][pump], "quantityLiters": "100", "voucherAmount": amount, "servedAt": _served(), "signedConfirmed": signed,
    }
    body.update(extra)
    return body


def _lub(designation, opening, sold, price, entry=None, **extra):
    body = {"designation": designation, "openingQty": opening, "soldQty": sold, "unitPriceAmount": price}
    if entry is not None:
        body["entryQty"] = entry
    body.update(extra)
    return body


# SOCADA : 18 x 2 500 + 1 x 5 500 + 2 x 5 500 + 2 x 1 000 + 1 x 2 000 = 65 500 ; fermetures 946, 1, 56, 42, 38
_SOCADA_LUBS = [
    _lub("15W40 vrac", "964", "18", "2500"), _lub("BF DOT 4", "2", "1", "5500"), _lub("80W90", "58", "2", "5500"),
    _lub("Liq. Réf.", "44", "2", "1000"), _lub("Y22 EA", "39", "1", "2000"),
]
_SOCADA_CREDITS = ["951600", "1431190", "800000", "900000", "700000", "600000", "700000", "528361"]  # synthétiques, somme 6 611 151


def _socada_sections(ctx) -> dict:
    return {
        "2": {"version": 0, "status": "saved", "lines": _SOCADA_LUBS},
        "3": {"version": 0, "status": "ras", "rasNote": "Aucune vente de gaz"},
        "4": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [{"categoryCode": "total", "amount": "181625"}]},
        "5": {"version": 0, "status": "saved", "lines": [_voucher(ctx, f"0104{i}", amount, account=i % 3, pump=i % 2) for i, amount in enumerate(_SOCADA_CREDITS)]},
        "6": {"version": 0, "status": "ras"},
        "7": {"version": 0, "status": "saved", "detailMode": "summary", "orangeBalance": "2500000", "mtnBalance": "480000", "lines": [
            {"kind": "mobile", "operator": "orange_money", "amount": "1018973"}, {"kind": "mobile", "operator": "mtn_momo", "amount": "25500"},
        ]},
    }


# ---------------------------------------------------------------------------
# Algorithmes purs
# ---------------------------------------------------------------------------


def test_lubricant_line_closing_amount_and_stock_check():
    calc = compute_lubricant_line(D("964"), D("0"), D("18"), D("2500"))
    assert calc["closing"] == D("946") and calc["amount"] == D("45000.00") and not calc["exceedsStock"]
    assert compute_lubricant_line(D("19"), D("0"), D("20"), D("100"))["exceedsStock"]
    assert compute_lubricant_line(D("5"), D("0"), D("1"), None)["amount"] is None  # jamais un prix inventé


def test_gas_deposit_refund_is_negative_and_only_bottles_have_stock():
    assert compute_gas_line("bottle", 10, 0, 3, D("6000"))["amount"] == D("18000.00")
    assert compute_gas_line("bottle", 10, 0, 3, D("6000"))["closing"] == 7
    assert compute_gas_line("deposit", 0, 0, 2, D("15000"))["amount"] == D("30000.00")
    refund = compute_gas_line("deposit_refund", 0, 0, 1, D("15000"))
    assert refund["amount"] == D("-15000.00") and refund["closing"] is None


def test_value_vouchers_total_is_count_times_denomination_per_column():
    calc = compute_value_vouchers({(10000, "daily"): 2, (5000, "daily"): 1, (3000, "value"): 4})
    assert calc["dailyTotal"] == D("25000") and calc["valueTotal"] == D("12000") and calc["total"] == D("37000")


def test_parse_count_refuses_decimals_and_negatives():
    assert parse_count("3") == (3, None) and parse_count("3,0") == (3, None)
    assert parse_count("1,5")[1] == "not_integer" and parse_count("-1")[1] == "negative" and parse_count("x")[1] == "not_a_number"


# ---------------------------------------------------------------------------
# Chiffres SOCADA, enregistrement en lot
# ---------------------------------------------------------------------------


async def test_socada_figures_are_computed_by_the_server_in_one_all_or_nothing_save(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    before = await _get(client, h, ctx)
    assert all(s["status"] == "not_started" and s["version"] == 0 for s in before["sections"]) and before["totals"]["allSettled"] is False
    assert before["access"]["canManage"] is True and before["access"]["locked"] is False

    res = await _put(client, h, ctx, _socada_sections(ctx))
    assert res.status_code == 200, res.text
    view = res.json()
    totals = view["totals"]
    assert Decimal(totals["lubricants"]) == D("65500") and Decimal(totals["shop"]) == D("181625") and Decimal(totals["creditVouchers"]) == D("6611151")
    assert Decimal(totals["orangeMoney"]) == D("1018973") and Decimal(totals["mtnMomo"]) == D("25500") and Decimal(totals["mobileMoney"]) == D("1044473") and Decimal(totals["electronic"]) == D("1044473")
    assert Decimal(totals["gas"]) == 0 and Decimal(totals["valueVouchers"]) == 0 and totals["allSettled"] is True
    assert totals["statuses"] == {"2": "saved", "3": "ras", "4": "saved", "5": "saved", "6": "ras", "7": "saved"} and totals["versionsSum"] == 6
    assert totals["mobileSummaryMode"] is True and totals["shopSummaryMode"] is True and totals["creditVoucherCount"] == 8 and len(totals["unsignedVoucherNumbers"]) == 0
    lubs = {l["designation"]: l for l in _section(view, 2)["lubricantLines"]}
    assert [Decimal(lubs[n]["closingQty"]) for n in ("15W40 vrac", "BF DOT 4", "80W90", "Liq. Réf.", "Y22 EA")] == [D("946"), D("1"), D("56"), D("42"), D("38")]
    assert Decimal(_section(view, 7)["orangeBalance"]) == D("2500000") and Decimal(_section(view, 7)["mtnBalance"]) == D("480000")
    credits = _section(view, 5)
    assert Decimal(credits["totalAmount"]) == D("6611151") and sum(Decimal(c["amount"]) for c in credits["creditByClient"]) == D("6611151") and len(credits["creditByClient"]) == 3
    # Avertissements non bloquants : boutique sans détail, mobile en cumul, prix carburant absent, lubrifiants hors catalogue.
    codes = {w["code"] for w in view["warnings"]}
    assert {"shop_summary", "mobile_summary", "off_catalogue", "price_manual", "price_missing"} <= codes
    # Aucune Sale ni Receivable n'est créée par D4 (E7) ; saleId / receivableId restent nuls.
    from app.modules.zylo_liquid.models import Receivable, Sale, ShiftReportCreditVoucher

    async with AsyncSessionLocal() as db:
        assert (await db.scalar(select(func.count()).select_from(Sale).where(Sale.stationId == uuid.UUID(ctx["station"])))) == 0
        assert (await db.scalar(select(func.count()).select_from(Receivable).where(Receivable.commercialAccountId.in_([uuid.UUID(a["id"]) for a in ctx["accounts"]])))) == 0
        vouchers = (await db.execute(select(ShiftReportCreditVoucher).where(ShiftReportCreditVoucher.reportId == uuid.UUID(ctx["report"])))).scalars().all()
        assert len(vouchers) == 8 and all(v.saleId is None and v.receivableId is None for v in vouchers)


async def test_all_errors_come_back_at_once_and_nothing_is_written_in_any_section(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """9 bons dont 1 sans pompe + une rubrique 2 valide dans le même lot : aucun enregistrement, nulle part."""
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    vouchers = [_voucher(ctx, f"0200{i}", "100000", account=i % 3, pump=i % 2) for i in range(9)]
    vouchers[4]["pumpLineId"] = None
    res = await _put(client, h, ctx, {"2": {"version": 0, "status": "saved", "lines": _SOCADA_LUBS}, "5": {"version": 0, "status": "saved", "lines": vouchers}})
    assert res.status_code == 422 and res.json()["error"]["code"] == "shift_report_sections_invalid", res.text
    assert _cells(res) == {"r5:5:pumpLineId"}
    detail = res.json()["error"]["details"][0]
    assert detail["code"] == "pump_missing" and detail["section"] == 5 and detail["rowNumber"] == 5 and "caisse du pompiste" in detail["message"]
    after = await _get(client, h, ctx)
    assert all(s["status"] == "not_started" and s["version"] == 0 for s in after["sections"])


async def test_cell_errors_for_credit_vouchers_tell_how_to_fix(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    acc = ctx["accounts"]
    other_plate = acc[1]["vehicle"]
    lines = [
        _voucher(ctx, "01043", "100000"), _voucher(ctx, "01043", "200000"),  # doublon -> lignes 1 et 2
        {**_voucher(ctx, "01044", "100000"), "commercialAccountId": ctx["inactive"]},  # compte suspendu
        {**_voucher(ctx, "01045", "100000", pump=1), "fuelProductId": ctx["products"][0]},  # produit != pompe
        {**_voucher(ctx, "01046", "100000"), "vehicleId": other_plate},  # plaque d'un autre client
        {**_voucher(ctx, "01047", "100000"), "servedAt": f"{(date.today() - timedelta(days=3)).isoformat()}T09:00:00"},  # autre date
        {**_voucher(ctx, "", "100000")},  # numéro manquant
        {**_voucher(ctx, "01048", "0")},  # montant nul
        {**_voucher(ctx, "01049", "100000"), "commercialAccountId": None},  # client manquant
    ]
    res = await _put(client, h, ctx, {"5": {"version": 0, "status": "saved", "lines": lines}})
    assert res.status_code == 422, res.text
    by_cell = {d["cell"]: d for d in res.json()["error"]["details"]}
    assert by_cell["r5:1:voucherNumber"]["code"] == "voucher_number_duplicate" and by_cell["r5:2:voucherNumber"]["code"] == "voucher_number_duplicate"
    assert "apparaît deux fois (lignes 1 et 2)" in by_cell["r5:1:voucherNumber"]["message"]
    assert by_cell["r5:3:commercialAccountId"]["code"] == "account_inactive" and "suspendu" in by_cell["r5:3:commercialAccountId"]["message"]
    assert by_cell["r5:4:fuelProductId"]["code"] == "product_pump_mismatch" and "La pompe N° 2 vend du" in by_cell["r5:4:fuelProductId"]["message"]
    assert by_cell["r5:5:vehicleId"]["code"] == "vehicle_not_of_account"
    assert by_cell["r5:6:servedAt"]["code"] == "voucher_date_not_report_day" and "n'est pas la journée du rapport" in by_cell["r5:6:servedAt"]["message"]
    assert by_cell["r5:7:voucherNumber"]["code"] == "voucher_number_missing"
    assert by_cell["r5:8:voucherAmount"]["code"] == "voucher_amount_invalid"
    assert by_cell["r5:9:commercialAccountId"]["code"] == "account_required"


async def test_stock_ras_and_count_errors(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await _put(client, h, ctx, {
        "2": {"version": 0, "status": "saved", "lines": [_lub("Huile X", "19", "20", "2500"), _lub("Huile Y", None, "1", "100")]},
        "3": {"version": 0, "status": "ras", "lines": [{"sizeKg": "12.5", "lineKind": "bottle", "openingQty": "10", "soldQty": "1", "unitPriceAmount": "6000"}]},
        "6": {"version": 0, "status": "saved", "lines": [{"denomination": "5000", "voucherColumn": "daily", "count": "1,5"}]},
    })
    assert res.status_code == 422, res.text
    by_cell = {d["cell"]: d for d in res.json()["error"]["details"]}
    assert by_cell["r2:1:soldQty"]["code"] == "sold_exceeds_stock" and "(20,00) dépassent le stock disponible (19,00)" in _plain(by_cell["r2:1:soldQty"]["message"])
    assert by_cell["r2:2:openingQty"]["code"] == "opening_missing"
    assert by_cell["r3:0:status"]["code"] == "ras_with_lines" and "videz-les" in by_cell["r3:0:status"]["message"]
    assert by_cell["r6:1:count"]["code"] == "count_invalid" and "nombre entier de bons" in by_cell["r6:1:count"]["message"]
    empty = await _put(client, h, ctx, {"6": {"version": 0, "status": "saved", "lines": []}})
    assert empty.status_code == 422 and _codes(empty) == ["lines_missing"]
    unknown = await _put(client, h, ctx, {"9": {"version": 0, "status": "saved"}})
    assert unknown.status_code == 422 and _codes(unknown) == ["section_unknown"]


async def test_gas_value_vouchers_and_shop_detail_with_subtotals(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    res = await _put(client, h, ctx, {
        "3": {"version": 0, "status": "saved", "lines": [
            {"sizeKg": "12.5", "lineKind": "bottle", "openingQty": "10", "entryQty": "5", "soldQty": "3", "unitPriceAmount": "6000"},
            {"sizeKg": "12.5", "lineKind": "deposit", "soldQty": "2", "unitPriceAmount": "15000"},
            {"sizeKg": "12.5", "lineKind": "deposit_refund", "soldQty": "1", "unitPriceAmount": "15000"},
            {"sizeKg": "6", "lineKind": "bottle"},  # ligne vide de l'imprimé : non stockée
        ]},
        "4": {"version": 0, "status": "saved", "detailMode": "detailed", "lines": [{"categoryCode": "telecards", "amount": "10000"}, {"categoryCode": "soft_drinks", "amount": "25 500,50"}, {"categoryCode": "other", "amount": ""}]},
        "6": {"version": 0, "status": "saved", "lines": [
            {"denomination": "10000", "voucherColumn": "daily", "count": "2"}, {"denomination": "5000", "voucherColumn": "daily", "count": "1"},
            {"denomination": "3000", "voucherColumn": "value", "count": "4"}, {"denomination": "3000", "voucherColumn": "daily", "count": "0"},
        ]},
    })
    assert res.status_code == 200, res.text
    view = res.json()
    gas = _section(view, 3)
    assert Decimal(gas["totalAmount"]) == D("18000") + D("30000") - D("15000") and Decimal(gas["subtotals"]["size:12.5"]) == D("33000")
    bottle = next(l for l in gas["gasLines"] if l["lineKind"] == "bottle")
    assert bottle["openingQty"] == 10 and bottle["closingQty"] == 12 and len(gas["gasLines"]) == 3
    shop = _section(view, 4)
    assert Decimal(shop["totalAmount"]) == D("35500.50") and [l["categoryCode"] for l in shop["shopLines"]] == ["telecards", "soft_drinks"]
    vv = _section(view, 6)
    assert Decimal(vv["subtotals"]["daily"]) == D("25000") and Decimal(vv["subtotals"]["value"]) == D("12000") and Decimal(view["totals"]["valueVouchers"]) == D("37000")
    assert "value_vouchers_unassigned" in {w["code"] for w in view["warnings"]}


# ---------------------------------------------------------------------------
# Rubrique 7 : mode détail, origine, codes uniques
# ---------------------------------------------------------------------------


async def test_electronic_detail_mode_origin_pump_and_unique_codes(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    other = await _ctx(client, h, zylo_liquid_organization)
    ok = await _put(client, h, ctx, {"7": {"version": 0, "status": "saved", "detailMode": "detailed", "lines": [
        {"kind": "tomcard", "cardCount": "2", "ticketCount": "5", "amount": "20000"},
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "6a9f2", "amount": "15000", "origin": "pump", "pumpLineId": ctx["lines"][0]},
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "7B1", "amount": "5000", "origin": "shop"},
        {"kind": "mobile", "operator": "mtn_momo", "transactionCode": "6A9F2", "amount": "7000", "origin": "other"},
    ]}})
    assert ok.status_code == 200, ok.text
    elec = _section(ok.json(), 7)
    assert Decimal(elec["totalAmount"]) == D("47000") and Decimal(elec["subtotals"]["tomcard"]) == D("20000") and Decimal(elec["subtotals"]["orange_money"]) == D("20000")
    pay = {p["transactionCode"]: p for p in elec["electronicPayments"] if p["kind"] == "mobile" and p["operator"] == "orange_money"}
    assert pay["6A9F2"]["origin"] == "pump" and pay["6A9F2"]["pumpNumber"] == 1 and pay["7B1"]["pumpLineId"] is None  # code en majuscules, pompe seulement si origin = pump
    # Déductions D3 : seulement les paiements d'origine « pompe ».
    from app.modules.zylo_liquid import service

    async with AsyncSessionLocal() as db:
        assert await rapport_rubriques.get_electronic_payment_deductions_by_pump(db, uuid.UUID(ctx["report"])) == {uuid.UUID(ctx["lines"][0]): D("15000")}
    # Même code (même opérateur) sur un autre rapport de la MÊME station : refusé ; autre station : accepté.
    bad = await _put(client, h, ctx, {"7": {"version": 1, "status": "saved", "detailMode": "detailed", "lines": [
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "AAA", "amount": "1000", "origin": "pump"},  # pompe manquante
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "ZZ1", "amount": "1000", "origin": "shop"},
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "zz1", "amount": "1000", "origin": "shop"},  # doublon dans le lot
        {"kind": "mobile", "operator": "mtn_momo", "transactionCode": "", "amount": "1000", "origin": "other"},
        {"kind": "mobile", "operator": "mtn_momo", "transactionCode": "Q", "amount": "1000"},  # origine manquante
        {"kind": "tomcard", "cardCount": "0", "amount": "500"},
    ]}})
    assert bad.status_code == 422, bad.text
    by_cell = {d["cell"]: d["code"] for d in bad.json()["error"]["details"]}
    assert by_cell["r7:1:pumpLineId"] == "pump_missing" and by_cell["r7:2:transactionCode"] == "payment_code_duplicate" and by_cell["r7:3:transactionCode"] == "payment_code_duplicate"
    assert by_cell["r7:4:transactionCode"] == "payment_code_missing" and by_cell["r7:5:origin"] == "origin_missing" and by_cell["r7:6:cardCount"] == "card_count_missing"
    other_ok = await _put(client, h, other, {"7": {"version": 0, "status": "saved", "detailMode": "detailed", "lines": [
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "6A9F2", "amount": "1000", "origin": "shop"}]}})
    assert other_ok.status_code == 200, other_ok.text  # une autre station peut réutiliser le code
    # Code d'un rapport précédent de la même station : on simule en déplaçant la ligne sur un autre rapport (un seul tour ouvert par station).
    from app.modules.zylo_liquid.models import ShiftOccurrence, ShiftReport, ShiftReportElectronicPayment

    async with AsyncSessionLocal() as db:
        first = (await db.execute(select(ShiftReport).where(ShiftReport.id == uuid.UUID(ctx["report"])))).scalar_one()
        old_occ = ShiftOccurrence(
            stationId=first.stationId, shiftDefinitionId=(await db.get(ShiftOccurrence, first.occurrenceId)).shiftDefinitionId, shiftDate=date.today() - timedelta(days=1), shiftNumber=2,
            name="Soir", startTime="18:00", endTime="23:00", startsAt=datetime.now() - timedelta(days=1, hours=6), endsAt=datetime.now() - timedelta(days=1), status="closed",
        )
        db.add(old_occ)
        await db.flush()
        old_report = ShiftReport(
            stationId=first.stationId, occurrenceId=old_occ.id, shiftDate=old_occ.shiftDate, shiftNumber=2, shiftName="Soir", startTime="18:00", endTime="23:00",
            responsibleUserId=first.responsibleUserId, openedByUserId=first.openedByUserId, openedAt=first.openedAt - timedelta(days=1),
        )
        db.add(old_report)
        await db.flush()
        db.add(ShiftReportElectronicPayment(
            reportId=old_report.id, stationId=first.stationId, lineNumber=1, lineKey="orange_money:OLD1", kind="mobile", operator="orange_money", amount=D("100"), transactionCode="OLD1", origin="shop",
        ))
        await db.commit()
    again = await _put(client, h, ctx, {"7": {"version": 1, "status": "saved", "detailMode": "detailed", "lines": [
        {"kind": "mobile", "operator": "orange_money", "transactionCode": "old1", "amount": "1000", "origin": "shop"}]}})
    assert again.status_code == 422 and _codes(again) == ["payment_code_duplicate"]
    assert "rapport du" in again.json()["error"]["details"][0]["message"] and "tour Soir" in again.json()["error"]["details"][0]["message"]


# ---------------------------------------------------------------------------
# Version, rature, brouillon, verrou
# ---------------------------------------------------------------------------


async def test_stale_version_is_a_409_with_the_author_name_and_keeps_data(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    first = await _put(client, h, ctx, {"4": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [{"amount": "1000"}]}})
    assert first.status_code == 200 and _section(first.json(), 4)["version"] == 1
    stale = await _put(client, h, ctx, {"4": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [{"amount": "2000"}]}})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "shift_report_sections_version_changed"
    assert "La rubrique 4 a été modifiée par Test User à" in stale.json()["error"]["message"]
    assert Decimal(_section(await _get(client, h, ctx), 4)["totalAmount"]) == D("1000")


async def test_rature_is_required_to_change_a_saved_value_and_keeps_the_old_one(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    lines = [_voucher(ctx, "0300", "100000", signed=False)]
    first = await _put(client, h, ctx, {"5": {"version": 0, "status": "saved", "lines": lines}})
    assert first.status_code == 200 and first.json()["totals"]["unsignedVoucherNumbers"] == ["0300"]
    # Ajouter une ligne ne demande aucune rature ; modifier le montant ou la signature d'une ligne enregistrée, si.
    added = await _put(client, h, ctx, {"5": {"version": 1, "status": "saved", "lines": lines + [_voucher(ctx, "0301", "50000")]}})
    assert added.status_code == 200, added.text
    changed = [_voucher(ctx, "0300", "120000", signed=True), _voucher(ctx, "0301", "50000")]
    refused = await _put(client, h, ctx, {"5": {"version": 2, "status": "saved", "lines": changed}})
    assert refused.status_code == 422 and _cells(refused) == {"r5:0:rature"} and _codes(refused) == ["rature_reason_missing"]
    ghost = await _put(client, h, ctx, {"5": {"version": 2, "status": "saved", "lines": changed, "rature": {"reasonCode": "voucher_found", "initialedByUserId": str(uuid.uuid4())}}})
    assert ghost.status_code == 422 and _codes(ghost) == ["rature_initialed_by_unknown"]
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one().id
    other_note = await _put(client, h, ctx, {"5": {"version": 2, "status": "saved", "lines": changed, "rature": {"reasonCode": "other", "reasonNote": "court", "initialedByUserId": str(me)}}})
    assert other_note.status_code == 422 and _codes(other_note) == ["rature_note_missing"]
    ok = await _put(client, h, ctx, {"5": {"version": 2, "status": "saved", "lines": changed, "rature": {"reasonCode": "voucher_found", "reasonNote": "Bon retrouvé dans la sacoche", "initialedByUserId": str(me)}}})
    assert ok.status_code == 200, ok.text
    assert Decimal(_section(ok.json(), 5)["totalAmount"]) == D("170000") and ok.json()["totals"]["unsignedVoucherNumbers"] == []
    from app.modules.zylo_liquid.models import ShiftReportSectionCorrection

    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(ShiftReportSectionCorrection).where(ShiftReportSectionCorrection.reportId == uuid.UUID(ctx["report"])))).scalars().all()
    by_field = {r.field: r for r in rows}
    assert set(by_field) == {"voucherAmount", "signedConfirmed"} and by_field["voucherAmount"].oldValue == "100000" and by_field["voucherAmount"].newValue == "120000"
    assert by_field["signedConfirmed"].oldValue == "false" and by_field["signedConfirmed"].newValue == "true" and all(r.initialedByUserId == me and r.sectionVersion == 3 for r in rows)
    # Retirer une ligne enregistrée est aussi une rature (ancienne ligne conservée dans l'historique).
    removal = await _put(client, h, ctx, {"5": {"version": 3, "status": "saved", "lines": [changed[0]]}})
    assert removal.status_code == 422 and _codes(removal) == ["rature_reason_missing"]
    # Un brouillon sans changement de valeur existante (ajout seulement, ou renvoi identique) n'exige rien.
    same = await _put(client, h, ctx, {"5": {"version": 3, "status": "saved", "lines": changed}})
    assert same.status_code == 200 and _section(same.json(), 5)["version"] == 4


async def test_voucher_already_reported_by_e7_cannot_be_changed_or_removed(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    line = _voucher(ctx, "0400", "100000")
    assert (await _put(client, h, ctx, {"5": {"version": 0, "status": "saved", "lines": [line]}})).status_code == 200
    from app.identity.models import User
    from app.modules.zylo_liquid.models import Sale, ShiftReportCreditVoucher

    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one().id
        voucher = (await db.execute(select(ShiftReportCreditVoucher).where(ShiftReportCreditVoucher.reportId == uuid.UUID(ctx["report"])))).scalar_one()
        sale = Sale(
            stationId=uuid.UUID(ctx["station"]), authorUserId=me, eventAt=datetime.utcnow(), fuelProductId=voucher.fuelProductId, quantityLiters=D("100"), priceAmount=D("1000"),
            currencyId=uuid.UUID(ctx["currency"]), paymentMethod="credit", commercialAccountId=voucher.commercialAccountId,
        )
        db.add(sale)
        await db.flush()
        voucher.saleId = sale.id
        await db.commit()
    res = await _put(client, h, ctx, {"5": {"version": 1, "status": "saved", "lines": [{**line, "voucherAmount": "90000"}], "rature": {"reasonCode": "entry_error", "initialedByUserId": str(me)}}})
    assert res.status_code == 422 and _codes(res) == ["voucher_already_reported"]
    assert _section(await _get(client, h, ctx), 5)["creditVouchers"][0]["reportedToAccount"] is True


async def test_not_started_clears_a_saved_section_with_rature_and_ras_needs_empty_lines(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one().id
    assert (await _put(client, h, ctx, {"4": {"version": 0, "status": "saved", "detailMode": "summary", "lines": [{"amount": "500"}]}})).status_code == 200
    no_rature = await _put(client, h, ctx, {"4": {"version": 1, "status": "ras"}})
    assert no_rature.status_code == 422 and _codes(no_rature) == ["rature_reason_missing"]
    ras = await _put(client, h, ctx, {"4": {"version": 1, "status": "ras", "rasNote": "rien", "rature": {"reasonCode": "entry_error", "initialedByUserId": str(me)}}})
    assert ras.status_code == 200 and _section(ras.json(), 4)["status"] == "ras" and Decimal(_section(ras.json(), 4)["totalAmount"]) == 0
    reset = await _put(client, h, ctx, {"4": {"version": 2, "status": "not_started"}})
    assert reset.status_code == 200 and _section(reset.json(), 4)["status"] == "not_started" and reset.json()["totals"]["allSettled"] is False


async def test_locked_when_the_shift_is_not_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization, status="closed")
    view = await _get(client, h, ctx)
    assert view["access"]["locked"] is True and view["access"]["lockedCode"] == "report_not_open" and view["access"]["canManage"] is False
    res = await _put(client, h, ctx, {"4": {"version": 0, "status": "ras"}})
    assert res.status_code == 409 and res.json()["error"]["code"] == "report_not_open"


# ---------------------------------------------------------------------------
# Stocks reportés, catalogue, prix figé
# ---------------------------------------------------------------------------


async def test_opening_is_carried_from_the_previous_closed_report_and_a_gap_needs_a_reason(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid.models import (
        SellableProduct, SellableProductPrice, ShiftOccurrence, ShiftReport, ShiftReportGasLine, ShiftReportLubricantLine,
    )

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one().id
        first = await db.get(ShiftReport, uuid.UUID(ctx["report"]))
        occ = await db.get(ShiftOccurrence, first.occurrenceId)
        product = SellableProduct(organizationId=uuid.UUID(zylo_liquid_organization["id"]), stationId=uuid.UUID(ctx["station"]), name=f"Huile 5W30 {ctx['suffix']}", category="Lubrifiants", unitPriceAmount=D("9999"), currencyId=uuid.UUID(ctx["currency"]), stockQuantity=D("777"))
        db.add(product)
        await db.flush()
        db.add(SellableProductPrice(stationId=uuid.UUID(ctx["station"]), sellableProductId=product.id, currencyId=uuid.UUID(ctx["currency"]), priceAmount=D("3500"), effectiveFrom=datetime.utcnow() - timedelta(days=30), createdBy=me))
        old_occ = ShiftOccurrence(
            stationId=first.stationId, shiftDefinitionId=occ.shiftDefinitionId, shiftDate=date.today() - timedelta(days=1), shiftNumber=2, name="Soir", startTime="18:00", endTime="23:00",
            startsAt=datetime.now() - timedelta(days=1, hours=6), endsAt=datetime.now() - timedelta(days=1), status="closed",
        )
        db.add(old_occ)
        await db.flush()
        old = ShiftReport(
            stationId=first.stationId, occurrenceId=old_occ.id, shiftDate=old_occ.shiftDate, shiftNumber=2, shiftName="Soir", startTime="18:00", endTime="23:00",
            responsibleUserId=me, openedByUserId=me, openedAt=first.openedAt - timedelta(days=1),
        )
        db.add(old)
        await db.flush()
        db.add(ShiftReportLubricantLine(
            reportId=old.id, lineNumber=1, lineKey=f"p:{product.id}", sellableProductId=product.id, designation=product.name, openingQty=D("50"), openingSource="initial", entryQty=D("0"),
            soldQty=D("10"), closingQty=D("40"), unitPriceAmount=D("3500"), unitPriceSource="catalogue", amount=D("35000"),
        ))
        db.add(ShiftReportLubricantLine(
            reportId=old.id, lineNumber=2, lineKey="d:graisse", designation="Graisse", openingQty=D("8"), openingSource="initial", entryQty=D("0"), soldQty=D("3"), closingQty=D("5"),
            unitPriceAmount=D("1000"), unitPriceSource="manual", amount=D("3000"),
        ))
        db.add(ShiftReportGasLine(reportId=old.id, sizeKg=D("12.5"), lineKind="bottle", openingQty=20, openingSource="initial", entryQty=0, soldQty=4, closingQty=16, unitPriceAmount=D("6000"), amount=D("24000")))
        await db.commit()
        product_id = str(product.id)
    view = await _get(client, h, ctx)
    item = next(i for i in view["context"]["lubricantCatalogue"] if i["sellableProductId"] == product_id)
    assert Decimal(item["carriedOpeningQty"]) == D("40") and Decimal(item["resolvedPriceAmount"]) == D("3500") and Decimal(item["indicativeStockQty"]) == D("777")
    assert next(g for g in view["context"]["gasCarried"] if Decimal(g["sizeKg"]) == D("12.5"))["carriedOpeningQty"] == 16
    # Ouverture omise : reportée (catalogue + hors catalogue + gaz) ; prix catalogue figé, jamais celui du client ni le stock vif.
    res = await _put(client, h, ctx, {
        "2": {"version": 0, "status": "saved", "lines": [{"sellableProductId": product_id, "soldQty": "4", "unitPriceAmount": "1"}, {"designation": "Graisse", "soldQty": "1", "unitPriceAmount": "1000"}]},
        "3": {"version": 0, "status": "saved", "lines": [{"sizeKg": "12.5", "lineKind": "bottle", "entryQty": "2", "soldQty": "6", "unitPriceAmount": "6000"}]},
    })
    assert res.status_code == 200, res.text
    lubs = {l["designation"]: l for l in _section(res.json(), 2)["lubricantLines"]}
    cat = lubs[f"Huile 5W30 {ctx['suffix']}"]
    assert Decimal(cat["openingQty"]) == 40 and cat["openingSource"] == "carried" and Decimal(cat["closingQty"]) == 36 and Decimal(cat["unitPriceAmount"]) == D("3500") and Decimal(cat["amount"]) == D("14000") and cat["unitPriceSource"] == "catalogue"
    assert Decimal(lubs["Graisse"]["openingQty"]) == 5 and lubs["Graisse"]["openingSource"] == "carried"
    gas = _section(res.json(), 3)["gasLines"][0]
    assert gas["openingQty"] == 16 and gas["openingSource"] == "carried" and gas["closingQty"] == 12
    # Écart avec le report : motif de 10 caractères obligatoire.
    gap = await _put(client, h, ctx, {"2": {"version": 1, "status": "saved", "lines": [
        {"sellableProductId": product_id, "soldQty": "4", "openingQty": "38"}, {"designation": "Graisse", "soldQty": "1", "openingQty": "5", "unitPriceAmount": "1000"}]}})
    assert gap.status_code == 422 and _codes(gap) == ["opening_not_continuous"] and "diffère de la fermeture du tour précédent" in gap.json()["error"]["details"][0]["message"]
    from app.identity.models import User as _U

    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(_U).where(_U.email == registered_user["email"]))).scalar_one().id
    fixed = await _put(client, h, ctx, {"2": {"version": 1, "status": "saved", "lines": [
        {"sellableProductId": product_id, "soldQty": "4", "openingQty": "38", "openingNote": "Deux bidons cassés au dépôt"}, {"designation": "Graisse", "soldQty": "1", "unitPriceAmount": "1000"}],
        "rature": {"reasonCode": "count_error", "initialedByUserId": str(me)}}})
    assert fixed.status_code == 200, fixed.text
    assert next(l for l in _section(fixed.json(), 2)["lubricantLines"] if l["sellableProductId"] == product_id)["openingSource"] == "continuity_break"


# ---------------------------------------------------------------------------
# Contexte, fonctions publiques, audit, événement
# ---------------------------------------------------------------------------


async def test_context_credit_accounts_pumps_and_shop_suggestion(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.identity.models import User
    from app.modules.zylo_liquid.models import ProductSaleLine, ProductSaleTransaction, SellableProduct

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    async with AsyncSessionLocal() as db:
        me = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one().id
        product = SellableProduct(organizationId=uuid.UUID(zylo_liquid_organization["id"]), stationId=uuid.UUID(ctx["station"]), name="Coca", category="Boissons sans alcool", unitPriceAmount=D("500"), currencyId=uuid.UUID(ctx["currency"]))
        db.add(product)
        await db.flush()
        for amount in ("1500", "2500"):
            tx = ProductSaleTransaction(stationId=uuid.UUID(ctx["station"]), authorUserId=me, eventAt=datetime.utcnow(), currencyId=uuid.UUID(ctx["currency"]), paymentMethod="cash", totalAmount=D(amount), status="completed")
            db.add(tx)
            await db.flush()
            db.add(ProductSaleLine(transactionId=tx.id, sellableProductId=product.id, quantity=D("1"), unitPriceAmount=D(amount), lineTotalAmount=D(amount)))
        await db.commit()
    view = await _get(client, h, ctx)
    context = view["context"]
    names = {a["name"]: a for a in context["creditAccounts"]}
    assert f"OFF{ctx['suffix']}" not in names and len(names) >= 3  # comptes suspendus exclus ; noms, plaques, chauffeurs, reste disponible seulement
    mine = names[ctx["accounts"][0]["name"]]
    assert Decimal(mine["remainingCredit"]) == D("10000000") and mine["vehicles"][0]["plate"] == ctx["accounts"][0]["plate"] and mine["drivers"][0]["name"].startswith("Ngo")
    assert set(mine) == {"commercialAccountId", "name", "remainingCredit", "vehicles", "drivers"}
    assert [p["pumpNumber"] for p in context["pumps"]] == [1, 2] and context["pumps"][0]["unitPriceAmount"] is None  # prix carburant non disponible : jamais inventé
    shop = context["shopSuggestion"]
    assert shop["ticketCount"] == 2 and Decimal(shop["totalAmount"]) == D("4000") and shop["byCategory"] == [{"categoryCode": "soft_drinks", "categoryLabel": "Boissons sans alcool", "amount": "4000.00"}]
    assert [c["categoryCode"] for c in context["shopCategories"]][0] == "telecards" and len(context["shopCategories"]) == 11
    assert context["valueDenominations"] == [10000, 5000, 3000] and context["gasSizes"] == ["6.0", "12.5", "26.0", "35.0"]


async def test_public_functions_for_d3_d5_d6(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid import service

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    assert (await _put(client, h, ctx, _socada_sections(ctx))).status_code == 200
    async with AsyncSessionLocal() as db:
        totals = await rapport_rubriques.get_rubric_totals(db, uuid.UUID(ctx["report"]))
        by_pump = await rapport_rubriques.get_credit_voucher_deductions_by_pump(db, uuid.UUID(ctx["report"]))
        mobile_by_pump = await rapport_rubriques.get_electronic_payment_deductions_by_pump(db, uuid.UUID(ctx["report"]))
        credit_context = await rapport_rubriques.get_credit_context(db, uuid.UUID(ctx["report"]))
    assert totals.lubricants == D("65500") and totals.mobileMoney == D("1044473") and totals.versionsSum == 6 and totals.amountComplete is True
    assert sum(by_pump.values()) == D("6611151") and set(by_pump) == {uuid.UUID(l) for l in ctx["lines"]}
    assert mobile_by_pump == {}  # mode cumul : aucune pompe, rien à déduire par pompiste
    assert {a.name for a in credit_context} >= {a["name"] for a in ctx["accounts"]}


async def test_save_publishes_the_event_after_commit_and_writes_an_audit_entry(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    received: list[dict] = []

    async def handler(**payload):
        received.append(payload)

    events.subscribe("ShiftReportSectionsSaved", handler)
    try:
        res = await _put(client, h, ctx, {"3": {"version": 0, "status": "ras"}, "5": {"version": 0, "status": "saved", "lines": [_voucher(ctx, "0500", "100000", signed=False)]}})
        failed = await _put(client, h, ctx, {"6": {"version": 0, "status": "saved"}})
    finally:
        events._handlers["ShiftReportSectionsSaved"].remove(handler)
    assert res.status_code == 200 and failed.status_code == 422
    assert len(received) == 1 and [s["number"] for s in received[0]["sections"]] == [3, 5]  # rien publié en cas d'échec
    async with AsyncSessionLocal() as db:
        entry = (await db.execute(select(AuditLog).where(AuditLog.organizationId == uuid.UUID(zylo_liquid_organization["id"]), AuditLog.action == "zyloLiquid.reportSections.save"))).scalars().one()
    assert [s["number"] for s in entry.changes["sections"]] == [3, 5] and entry.changes["unsignedVouchers"] == ["0500"]


# ---------------------------------------------------------------------------
# Droits
# ---------------------------------------------------------------------------


async def _scoped_user(client: AsyncClient, owner_headers: dict, organization: dict, role_code: str, station_id: str) -> dict:
    from app.identity.models import OrganizationUser, User

    email = f"{role_code}-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "fullName": "Scoped Test"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})
    token = login.json()["accessToken"]
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
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"]}


async def test_team_lead_and_auditor_read_only_shift_manager_and_manager_write_pump_attendant_nothing(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    body = {"sections": {"3": {"version": 0, "status": "ras"}}}
    for code in ("zylo_liquid_team_lead", "zylo_liquid_auditor"):
        user = await _scoped_user(client, h, zylo_liquid_organization, code, ctx["station"])
        assert (await client.get(_url(ctx), headers=user)).status_code == 200, code
        assert (await client.put(_url(ctx), json=body, headers=user)).status_code == 403, code
    attendant = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_pump_attendant", ctx["station"])
    assert (await client.get(_url(ctx), headers=attendant)).status_code == 403
    rt = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    saved = await client.put(_url(ctx), json=body, headers=rt)
    assert saved.status_code == 200, saved.text
    assert saved.json()["access"]["canManage"] is True
    manager = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_station_admin", ctx["station"])
    again = await client.put(_url(ctx), json={"sections": {"3": {"version": 1, "status": "ras"}}}, headers=manager)
    assert again.status_code == 200, again.text
    # Un autre station : portée station respectée.
    other = await _ctx(client, h, zylo_liquid_organization)
    assert (await client.get(_url(other), headers=rt)).status_code == 403


def test_report_sections_default_role_matrix():
    from app.modules.zylo_liquid.permissions import REPORT_SECTIONS_MANAGE, REPORT_SECTIONS_READ
    from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES

    by_code = {code: set(perms) for code, _name, perms in DEFAULT_ROLES}
    assert REPORT_SECTIONS_READ == "zyloLiquid.reportSections.read" and REPORT_SECTIONS_MANAGE == "zyloLiquid.reportSections.manage"
    for writer in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        assert {REPORT_SECTIONS_READ, REPORT_SECTIONS_MANAGE} <= by_code[writer], writer
    assert by_code["zylo_liquid_shift_manager"] & {REPORT_SECTIONS_READ, REPORT_SECTIONS_MANAGE} <= by_code["zylo_liquid_station_admin"]  # gérant ⊇ RT
    for reader in ("zylo_liquid_team_lead", "zylo_liquid_auditor"):
        assert REPORT_SECTIONS_READ in by_code[reader] and REPORT_SECTIONS_MANAGE not in by_code[reader], reader
    assert not by_code["zylo_liquid_pump_attendant"] & {REPORT_SECTIONS_READ, REPORT_SECTIONS_MANAGE}
