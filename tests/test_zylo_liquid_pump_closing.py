"""Scénario D1 (index de fermeture des pompes + volumes vendus) : saisie en lot tout-ou-rien avec erreurs par cellule en
français, litres vendus = (fermeture - ouverture) - sorties (retours en cuve = stock seulement), montant = litres x prix en
vigueur à l'ouverture (copié), jeux de test SOCADA, compteur remis à zéro / remplacé, rature paraphée (ancienne valeur
conservée), brouillon, verrou optimiste, tour non fermé par D1, audit, événements après commit, droits et portée station.

Le tour « ouvert » est posé directement en base (occurrence `opened` + rapport + lignes de pompe) : D1 ne dépend que du
modèle du rapport de B3, pas de son API d'ouverture."""

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal

from app.shared import events
from app.modules.zylo_liquid.exploitation.alg_pompes import PUMP_CLOSING_RECORDED_EVENT, PUMP_COUNTER_REPLACED_EVENT, closing_habit_warning, compute_line_amount, compute_product_amount, compute_sold_liters
from app.modules.zylo_liquid.exploitation import pumps_fermeture as pumps_fermeture

BASE = "/api/v1/zylo-liquid"

# Index d'ouverture par pompe : (numéro, produit, ouverture). Super = pompes 1-2, Gas-oil = 3-4, Pétrole (sans prix) = 5.
PUMPS = [
    (1, "Super", "1000.00"), (2, "Super", "2000.00"),
    (3, "Gas-oil", "5000.00"), (4, "Gas-oil", "7000.00"),
    (5, "Petrole", "50190.28"),
]


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _post(client, headers, path, body):
    res = await client.post(f"{BASE}{path}", json=body, headers=headers)
    assert res.status_code in (200, 201), res.text
    return res.json()


async def _scoped_user(client: AsyncClient, owner_headers: dict, organization: dict, role_code: str, station_id: str) -> dict:
    email = f"{role_code}-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!", "fullName": f"Scoped {role_code[-6:]}"})
    token = (await client.post("/api/v1/auth/login", json={"email": email, "password": "Password123!"})).json()["accessToken"]

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


async def _ctx(client: AsyncClient, h: dict, organization: dict) -> dict:
    suffix = uuid.uuid4().hex[:6]
    station = (await _post(client, h, "/stations", {"name": f"Station D1{suffix}", "code": f"E{suffix}"}))["id"]
    tanks: dict[str, str] = {}
    products: dict[str, str] = {}
    for number, name in enumerate(("Super", "Gas-oil", "Petrole"), start=1):
        product = (await _post(client, h, "/fuel-products", {"name": f"{name}{suffix}", "code": f"{name[:2].upper()}{suffix}"}))["id"]
        products[name] = product
        tanks[name] = (await _post(client, h, "/tanks", {
            "stationId": station, "fuelProductId": product, "tankNumber": number, "displayName": f"Cuve {number}", "capacityLiters": 20000,
            "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        }))["id"]
    rows = [{"rowNumber": i, "tankId": tanks[product], "pumpNumber": number} for i, (number, product, _o) in enumerate(PUMPS, start=1)]
    pumps = [p["id"] for p in (await _post(client, h, "/pumps/bulk", {"stationId": station, "rows": rows}))["data"]]
    shift = (await _post(client, h, "/shift-definitions/bulk", {"stationId": station, "rows": [
        {"rowNumber": 1, "shiftNumber": 1, "name": "Journée", "startTime": "00:00", "endTime": "00:00"},
    ]}))["data"][0]
    roles = {r["code"]: r["id"] for r in (await client.get(f"/api/v1/rbac/organizations/{organization['id']}/roles", headers=h)).json()}

    def row(n, code):
        return {"rowNumber": n, "firstName": f"P{n}", "lastName": f"N{suffix}", "email": f"d1-{n}-{uuid.uuid4().hex[:8]}@example.com", "roleId": roles[code]}

    staff_rows = [row(1, "zylo_liquid_shift_manager"), row(2, "zylo_liquid_team_lead"), row(3, "zylo_liquid_pump_attendant"), row(4, "zylo_liquid_pump_attendant")]
    ids = [s["staff"]["userId"] for s in (await _post(client, h, "/station-staff/bulk", {"stationId": station, "rows": staff_rows}))["data"]]
    today = date.today()
    res = await client.put(f"{BASE}/shift-planning/bulk", headers=h, json={
        "stationId": station, "from": today.isoformat(), "to": today.isoformat(),
        "occurrences": [{"date": today.isoformat(), "shiftDefinitionId": shift["id"], "assignments": [{"userId": ids[0], "shiftRole": "shift_manager"}]}],
    })
    assert res.status_code == 200, res.text
    occurrence = res.json()["planning"]["occurrences"][0]["id"]
    report = await _open_tour(station, occurrence, pumps, tanks, ids[0])
    await _set_prices(station, products, ids[0], {"Super": "840", "Gas-oil": "828"})
    return {"station": station, "report": report, "occurrence": occurrence, "rt": ids[0], "ce": ids[1], "att": ids[2:], "pumps": pumps, "organization": organization}


async def _open_tour(station: str, occurrence: str, pumps: list[str], tanks: dict[str, str], rt_user: str) -> str:
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
        for pump, (number, product, opening) in zip(pumps, PUMPS):
            db.add(ShiftReportPumpLine(
                reportId=report.id, pumpId=uuid.UUID(pump), pumpNumber=number, pumpName=f"Pompe {number}", tankId=uuid.UUID(tanks[product]),
                fuelProductName=product, openingIndex=Decimal(opening), openingSource="initial",
            ))
        await db.commit()
        return str(report.id)


async def _set_prices(station: str, products: dict[str, str], user: str, prices: dict[str, str]) -> None:
    from app.modules.zylo_liquid.models import PriceHistory
    from app.shared.currency import Currency

    async with AsyncSessionLocal() as db:
        currency = (await db.execute(select(Currency).limit(1))).scalar_one_or_none()
        if currency is None:
            currency = Currency(code="XAF", name="Franc CFA", symbol="FCFA", decimalPlaces=0)
            db.add(currency)
            await db.flush()
        for name, amount in prices.items():
            db.add(PriceHistory(
                stationId=uuid.UUID(station), fuelProductId=uuid.UUID(products[name]), currencyId=currency.id, priceAmount=Decimal(amount),
                effectiveFrom=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1), createdBy=uuid.UUID(user),
            ))
        await db.commit()


async def _get(client, headers, report_id):
    return await client.get(f"{BASE}/shift-reports/{report_id}/closing-indexes", headers=headers)


async def _put(client, headers, report_id, body):
    return await client.put(f"{BASE}/shift-reports/{report_id}/closing-indexes", json=body, headers=headers)


def _body(view: dict, closings: dict[int, dict | str], read_with: str, version: int | None = None, **extra) -> dict:
    """Corps d'envoi : une entrée par pompe ; `closings[numéro]` = index (chaîne) ou dict de champs ; absent = ligne vide."""
    lines = []
    for line in view["lines"]:
        spec = closings.get(line["pumpNumber"])
        entry = {"pumpLineId": line["pumpLineId"], "readWithUserId": read_with}
        if isinstance(spec, dict):
            entry.update(spec)
        elif spec is not None:
            entry["closingIndex"] = spec
        lines.append(entry)
    return {"closingVersion": view["closingVersion"] if version is None else version, "lines": lines, **extra}


def _ok_closings() -> dict[int, str]:
    # Super : 1000,00 + 633,77 ; Gas-oil : 5000,00 + 3465,14 ; Pétrole : 0,10 (index réels SOCADA 50 190,28 -> 50 190,38).
    return {1: "2000.00", 2: "2633.77", 3: "10000.00", 4: "10465.14", 5: "50190.38"}


def _cells(res) -> set:
    return {(d["cell"].split(":")[0], d["rowNumber"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


async def test_socada_totals_and_nothing_closed(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    assert view["closingVersion"] == 0 and view["closingPhase"] == "open" and view["recorded"] is False and view["editable"] is True
    assert [l["pumpNumber"] for l in view["lines"]] == [1, 2, 3, 4, 5] and all(l["closingIndex"] is None and l["soldLiters"] is None for l in view["lines"])
    # Prix en vigueur affichés avant la saisie ; le Pétrole n'a pas de prix : jamais inventé (avertissement rouge).
    assert Decimal(view["lines"][0]["unitPriceAmount"]) == 840 and view["lines"][4]["unitPriceAmount"] is None
    assert any(w["code"] == "price_missing" and w["severity"] == "red" and "Petrole" in w["message"] for w in view["warnings"])
    assert {p["userId"] for p in view["eligibleReaders"]} >= {ctx["ce"], *ctx["att"]} and all("email" not in p for p in view["eligibleReaders"])

    res = await _put(client, h, ctx["report"], _body(view, _ok_closings(), ctx["att"][0]))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["closingVersion"] == 1 and out["closingPhase"] == "ready_to_close" and out["recorded"] is True and out["status"] == "opened"
    by_number = {l["pumpNumber"]: l for l in out["lines"]}
    assert Decimal(by_number[1]["soldLiters"]) == Decimal("1000.00") and Decimal(by_number[2]["soldLiters"]) == Decimal("633.77")
    assert Decimal(by_number[2]["amount"]) == Decimal("532366.80") and by_number[5]["amount"] is None and by_number[5]["readWithUserId"] == ctx["att"][0]
    products = {p["fuelProductName"]: p for p in out["products"]}
    assert Decimal(products["Super"]["soldLiters"]) == Decimal("1633.77") and Decimal(products["Super"]["amount"]) == Decimal("1372366.80")
    assert Decimal(products["Gas-oil"]["soldLiters"]) == Decimal("8465.14") and Decimal(products["Gas-oil"]["amount"]) == Decimal("7009135.92")
    assert Decimal(products["Petrole"]["soldLiters"]) == Decimal("0.10") and products["Petrole"]["amount"] is None and products["Petrole"]["priceAvailable"] is False
    # CUMUL P.B. : litres de tous les produits, montant des seuls produits au prix connu (partiel, jamais caché).
    assert Decimal(out["summary"]["totalLiters"]) == Decimal("10099.01") and Decimal(out["summary"]["totalAmount"]) == Decimal("8381502.72") and out["summary"]["amountComplete"] is False
    assert any(w["code"] == "price_missing" and w["blocksClosing"] for w in out["warnings"])
    # Le tour reste ouvert (la fermeture est D7).
    from app.modules.zylo_liquid.models import ShiftOccurrence

    async with AsyncSessionLocal() as db:
        assert (await db.get(ShiftOccurrence, uuid.UUID(ctx["occurrence"]))).status == "opened"


def test_pure_algorithms_rounding_and_methods():
    D = Decimal
    # Le papier arrondit UNE fois par produit : la somme des lignes peut différer de quelques centimes, sans erreur.
    price = D("0.5555")
    lines = [compute_line_amount(D("0.01"), price) for _ in range(3)]
    assert sum(lines) == D("0.03") and compute_product_amount(D("0.03"), price) == D("0.02") and sum(lines) != D("0.02")
    assert compute_product_amount(D("1633.77"), D(840)) == D("1372366.80")
    # Sortie avec test : écart 20, sorties 20, retours 20 -> 0 litre vendu ; les retours n'interviennent jamais.
    assert compute_sold_liters(D("100"), D("120"), D("20")) == 0
    assert compute_sold_liters(D("100"), D("120"), None) == 20
    assert compute_sold_liters(D("999990.00"), D("10.00"), None, "rollover") == D("20.00")
    assert compute_sold_liters(D("1000.00"), D("60.00"), None, "replaced", D("1100.00"), D("10.00")) == D("150.00")
    assert compute_sold_liters(D("1"), None) is None
    # Plausibilité : sans historique d'au moins 3 tours, aucun avertissement (jamais de seuil inventé).
    assert closing_habit_warning(D("4320"), [D("500"), D("520")]) == (None, None)
    assert closing_habit_warning(D("4320"), [D("500")] * 3)[1] == "high"
    assert closing_habit_warning(D("520"), [D("500")] * 3)[1] is None


async def test_all_or_nothing_with_every_cell_error_in_french(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    body = _body(view, {
        1: "999.99",                                              # inférieure à l'ouverture sans événement compteur
        2: "2500.00",                                             # valide mais SANS « lu à deux » ci-dessous
        3: "10000.001",                                           # plus de 2 décimales
        4: {"closingIndex": "7020.00", "exitsLiters": "20"},      # sorties sans observation
        # pompe 5 : ligne vide (oubliée)
    }, ctx["att"][0])
    body["lines"][1]["readWithUserId"] = None
    res = await _put(client, h, ctx["report"], body)
    assert res.status_code == 422, res.text
    assert res.json()["error"]["code"] == "pump_closing_invalid"
    cells = _cells(res)
    assert ("pump", 1, "closingIndex", "closing_not_greater") in cells and ("pump", 2, "readWithUserId", "read_with_missing") in cells
    assert ("pump", 3, "closingIndex", "closing_invalid") in cells and ("pump", 4, "exitsNote", "exits_note_missing") in cells
    assert ("pump", 5, "closingIndex", "closing_missing") in cells
    messages = {d["code"]: d["message"] for d in res.json()["error"]["details"]}
    assert "doit être supérieur à l'ouverture (1 000,00)" in messages["closing_not_greater"].replace("\u202f", " ") and "Expliquez les 20 L sortis de la pompe N° 4" in messages["exits_note_missing"]
    assert "Saisissez l'index de fermeture de la pompe N° 5" in messages["closing_missing"] and "avec quel pompiste" in messages["read_with_missing"]
    # Rien n'a été écrit : version inchangée, aucune valeur.
    after = (await _get(client, h, ctx["report"])).json()
    assert after["closingVersion"] == 0 and after["closingPhase"] == "open" and all(l["closingIndex"] is None for l in after["lines"])
    # Pompe oubliée (ligne absente du lot) et pompe inconnue : tout est rapporté d'un coup.
    partial = _body(view, _ok_closings(), ctx["att"][0])
    dropped = partial["lines"].pop()
    partial["lines"].append({"pumpLineId": str(uuid.uuid4()), "closingIndex": "1.00"})
    res = await _put(client, h, ctx["report"], partial)
    assert res.status_code == 422 and {c[3] for c in _cells(res)} == {"pump_line_missing", "pump_line_unknown"}
    assert dropped["pumpLineId"] in {l["pumpLineId"] for l in view["lines"]}


async def test_exits_returns_zero_sale_and_counter_events(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    rw = ctx["att"][0]
    # Sorties/retours invalides.
    bad = _body(view, {
        1: {"closingIndex": "1020.00", "exitsLiters": "20", "tankReturnLiters": "25", "exitsNote": "Test de débit"},   # retours > sorties
        2: {"closingIndex": "2020.00", "exitsLiters": "30", "exitsNote": "Étalonnage"},                              # sorties > mouvement
        3: "5000.00",                                                                                                  # égalité non confirmée
        4: {"closingIndex": "8000.00", "counterEvent": "rollover", "counterEventNote": "court"},                       # note trop courte + fermeture >= ouverture
        5: {"closingIndex": "50190.38", "counterEvent": "replaced", "counterEventNote": "Compteur remplacé par le fournisseur"},  # index manquants
    }, rw)
    res = await _put(client, h, ctx["report"], bad)
    assert res.status_code == 422
    codes = {(c[1], c[3]) for c in _cells(res)}
    assert {(1, "tank_return_exceeds_exits"), (2, "exits_exceed_movement"), (3, "zero_sale_unconfirmed"), (4, "counter_event_note_missing"), (4, "rollover_closing_not_lower"), (5, "replaced_index_missing")} <= codes
    # Valide : test de 20 L remis en cuve (litres vendus 0), pompe à zéro confirmée, remise à zéro et compteur remplacé.
    ok = _body(view, {
        1: {"closingIndex": "1020.00", "exitsLiters": "20", "tankReturnLiters": "20", "exitsNote": "Test de débit remis en cuve"},
        2: "2010.50",
        3: "5000.00",
        4: {"closingIndex": "10.00", "counterEvent": "rollover", "counterEventNote": "Compteur repassé à zéro après 999 999,99"},
        5: {"closingIndex": "60.00", "counterEvent": "replaced", "counterEventNote": "Compteur remplacé par le fournisseur", "replacedOldFinalIndex": "50200.00", "replacedNewStartIndex": "10.00"},
    }, rw, confirmedZeroSale=[view["lines"][2]["pumpLineId"]])
    received: list[dict] = []
    replaced: list[dict] = []

    async def on_recorded(**payload):
        received.append(payload)

    async def on_replaced(**payload):
        replaced.append(payload)

    events.subscribe(PUMP_CLOSING_RECORDED_EVENT, on_recorded)
    events.subscribe(PUMP_COUNTER_REPLACED_EVENT, on_replaced)
    res = await _put(client, h, ctx["report"], ok)
    assert res.status_code == 200, res.text
    by = {l["pumpNumber"]: l for l in res.json()["lines"]}
    assert Decimal(by[1]["soldLiters"]) == 0 and by[1]["provisionalMethod"] is True and Decimal(by[1]["tankReturnLiters"]) == 20
    assert Decimal(by[2]["soldLiters"]) == Decimal("10.50") and Decimal(by[3]["soldLiters"]) == 0 and by[3]["zeroSaleConfirmed"] is True
    assert Decimal(by[4]["soldLiters"]) == Decimal("1000000") - Decimal("7000.00") + Decimal("10.00") and any(w["code"] == "counter_rollover" for w in by[4]["warnings"])
    assert Decimal(by[5]["soldLiters"]) == (Decimal("50200.00") - Decimal("50190.28")) + (Decimal("60.00") - Decimal("10.00")) and any(w["code"] == "counter_replaced" for w in by[5]["warnings"])
    assert received and received[-1]["pumpCount"] == 5 and str(received[-1]["reportId"]) == ctx["report"]
    assert len(replaced) == 1 and replaced[0]["pumpNumber"] == 5
    # D2 : sorties de cuve = litres vendus par cuve, hors vente = sorties - retours.
    from app.modules.zylo_liquid import service

    async with AsyncSessionLocal() as db:
        by_tank = await pumps_fermeture.get_sold_liters_by_tank(db, uuid.UUID(ctx["report"]))
        amounts = await pumps_fermeture.get_pump_value_amounts(db, uuid.UUID(ctx["report"]))
        _products, summary = await pumps_fermeture.get_pump_closing_summary(db, uuid.UUID(ctx["report"]))
        assert sum(v["soldLiters"] for v in by_tank.values()) == summary.totalLiters and all(v["nonSaleLiters"] == 0 for v in by_tank.values())
        assert len(amounts) == 5 and amounts[uuid.UUID(ctx["pumps"][1])]["amount"] == Decimal("8820.00")  # 10,50 L x 840


async def test_rature_keeps_old_value_and_requires_reason(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    rw = ctx["att"][0]
    first = (await _put(client, h, ctx["report"], _body(view, _ok_closings(), rw))).json()
    view = (await _get(client, h, ctx["report"])).json()
    changed = {**_ok_closings(), 2: "2643.77"}
    # Sans rature : refusé, rien n'est écrit.
    res = await _put(client, h, ctx["report"], _body(view, changed, rw))
    assert res.status_code == 422 and ("pump", 2, "rature", "rature_reason_missing") in _cells(res)
    assert (await _get(client, h, ctx["report"])).json()["closingVersion"] == first["closingVersion"]
    # « Autre » sans précision, puis paraphe invalide, puis valide.
    body = _body(view, changed, rw)
    body["lines"][1]["rature"] = {"reasonCode": "other", "initialedByUserId": rw}
    assert ("pump", 2, "rature", "rature_note_missing") in _cells(await _put(client, h, ctx["report"], body))
    body["lines"][1]["rature"] = {"reasonCode": "digits_swapped", "initialedByUserId": str(uuid.uuid4())}
    assert ("pump", 2, "rature", "rature_reason_missing") in _cells(await _put(client, h, ctx["report"], body))
    body["lines"][1]["rature"] = {"reasonCode": "digits_swapped", "initialedByUserId": rw}
    res = await _put(client, h, ctx["report"], body)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["closingVersion"] == first["closingVersion"] + 1
    line = next(l for l in out["lines"] if l["pumpNumber"] == 2)
    assert Decimal(line["closingIndex"]) == Decimal("2643.77") and Decimal(line["soldLiters"]) == Decimal("643.77")
    assert len(line["corrections"]) == 1
    correction = line["corrections"][0]
    assert correction["field"] == "closingIndex" and Decimal(correction["oldValue"]) == Decimal("2633.77") and Decimal(correction["newValue"]) == Decimal("2643.77")
    assert correction["reasonCode"] == "digits_swapped" and correction["reasonLabel"] == "Chiffres inversés" and correction["initialedByUserId"] == rw
    # Les lignes inchangées ne portent aucune rature.
    assert all(l["corrections"] == [] for l in out["lines"] if l["pumpNumber"] != 2)


async def test_draft_then_final_and_version_conflict(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    rw = ctx["att"][0]
    # Brouillon : lignes vides tolérées, le tour NE passe PAS en prêt-à-fermer ; une valeur mal formée reste refusée.
    draft = _body(view, {1: "1100.00", 2: "2200.00"}, rw, draft=True)
    res = await _put(client, h, ctx["report"], draft)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["closingVersion"] == 1 and out["closingPhase"] == "open" and out["recorded"] is False
    assert Decimal(out["lines"][0]["soldLiters"]) == 100 and out["lines"][2]["closingIndex"] is None
    bad_draft = _body(out, {1: "abc"}, rw, draft=True)
    assert (await _put(client, h, ctx["report"], bad_draft)).status_code == 422
    # Version périmée : 409, saisie conservée côté client ; même corps renvoyé = jamais de doublon.
    stale = await _put(client, h, ctx["report"], _body(out, _ok_closings(), rw, version=0))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "closing_version_changed" and "Rechargez le tableau" in stale.json()["error"]["message"]
    final = await _put(client, h, ctx["report"], _body(out, _ok_closings(), rw))
    assert final.status_code == 200 and final.json()["closingPhase"] == "ready_to_close" and final.json()["closingVersion"] == 2
    again = await _put(client, h, ctx["report"], _body(out, _ok_closings(), rw))
    assert again.status_code == 409
    # Après l'enregistrement, le brouillon n'est plus permis (toute modification passe par une rature).
    after = (await _get(client, h, ctx["report"])).json()
    assert (await _put(client, h, ctx["report"], _body(after, {1: "1100.00"}, rw, draft=True))).json()["error"]["code"] == "draft_after_recording"


async def test_price_frozen_audit_and_report_not_open(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _ctx(client, h, zylo_liquid_organization)
    view = (await _get(client, h, ctx["report"])).json()
    rw = ctx["att"][0]
    out = (await _put(client, h, ctx["report"], _body(view, _ok_closings(), rw))).json()
    line1 = out["lines"][0]
    assert Decimal(line1["unitPriceAmount"]) == 840 and line1["unitPriceEffectiveFrom"] is not None and line1["closingReadAt"] is not None and line1["closingRecordedByName"]
    # Le prix est COPIÉ : un nouveau prix ensuite n'altère pas le rapport.
    from app.modules.zylo_liquid.models import PriceHistory, ShiftOccurrence, Tank

    async with AsyncSessionLocal() as db:
        tank = (await db.execute(select(Tank).where(Tank.stationId == uuid.UUID(ctx["station"]), Tank.tankNumber == 1))).scalar_one()
        old = (await db.execute(select(PriceHistory).where(PriceHistory.stationId == uuid.UUID(ctx["station"]), PriceHistory.fuelProductId == tank.fuelProductId))).scalar_one()
        db.add(PriceHistory(stationId=old.stationId, fuelProductId=old.fuelProductId, currencyId=old.currencyId, priceAmount=Decimal("900"), effectiveFrom=datetime.now(timezone.utc).replace(tzinfo=None), createdBy=old.createdBy))
        await db.commit()
    reread = (await _get(client, h, ctx["report"])).json()
    assert Decimal(reread["lines"][0]["unitPriceAmount"]) == 840 and Decimal(reread["lines"][0]["amount"]) == Decimal("840000.00")
    assert any(w["code"] == "price_changed_during_shift" for w in reread["warnings"])
    # Audit.
    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        audit = (await db.execute(select(AuditLog).where(AuditLog.action == "zyloLiquid.pumpClosing.record").order_by(AuditLog.createdAt.desc()))).scalars().first()
        assert audit is not None and audit.changes["pumpCount"] == 5 and audit.changes["closingVersion"] == 1 and audit.changes["ratureCount"] == 0
        # Tour clos : plus modifiable ici.
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(ctx["occurrence"])).values(status="closed"))
        await db.commit()
    res = await _put(client, h, ctx["report"], _body(reread, _ok_closings(), rw))
    assert res.status_code == 409 and res.json()["error"]["code"] == "report_not_open"
    assert (await _get(client, h, ctx["report"])).json()["editable"] is False


async def test_permissions_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    org = zylo_liquid_organization
    ctx = await _ctx(client, h, org)
    view = (await _get(client, h, ctx["report"])).json()
    body = _body(view, _ok_closings(), ctx["att"][0])
    rt = await _scoped_user(client, h, org, "zylo_liquid_shift_manager", ctx["station"])
    admin = await _scoped_user(client, h, org, "zylo_liquid_station_admin", ctx["station"])
    ce = await _scoped_user(client, h, org, "zylo_liquid_team_lead", ctx["station"])
    cashier = await _scoped_user(client, h, org, "zylo_liquid_cashier", ctx["station"])
    auditor = await _scoped_user(client, h, org, "zylo_liquid_auditor", ctx["station"])
    attendant = await _scoped_user(client, h, org, "zylo_liquid_pump_attendant", ctx["station"])
    other = (await _post(client, h, "/stations", {"name": f"Autre {uuid.uuid4().hex[:5]}", "code": f"O{uuid.uuid4().hex[:5]}"}))["id"]
    other_rt = await _scoped_user(client, h, org, "zylo_liquid_shift_manager", other)
    # Lecture : RT, gérant, chef d'équipe, caissier, auditeur ; pas le pompiste ni un RT d'une autre station.
    for headers in (rt, admin, ce, cashier, auditor):
        assert (await _get(client, headers, ctx["report"])).status_code == 200
    for headers in (attendant, other_rt):
        assert (await _get(client, headers, ctx["report"])).status_code == 403
    # Écriture : RT et gérant seulement.
    for headers in (ce, cashier, auditor, attendant, other_rt):
        assert (await _put(client, headers, ctx["report"], body)).status_code == 403
    assert (await _put(client, rt, ctx["report"], body)).status_code == 200
