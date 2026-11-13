"""Scénario D2 (jaugeage des cuves à la fermeture du tour) : hauteur lue en cm -> litres par la table de jaugeage de la
cuve, stock réel, stock théorique (ouverture + reçu - ventes - sorties nettes, D1), écart de stock (réel - théorique),
réception déclarée, comparaison télémétrie sans fusion, enregistrement tout-ou-rien en une transaction, ratures
(nouvelle déclaration liée), verrou optimiste, droits et portée station. Chiffres réels SOCADA du 16/08/2026."""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.database import AsyncSessionLocal
from app.core.field_crypto import chiffrer
from tests.test_zylo_liquid_shift_opening import BASE, _body, _context, _ctx, _headers, _live_occurrence, _now, _open, _scoped_user


# Tables de jaugeage de TEST (points fictifs, jamais ceux de SOCADA qui ne sont pas fournis), calées pour reproduire les
# chiffres du rapport du 16/08/2026 et les conversions du cahier du 22/07/2026.
SUPER_TABLE = [(0, 0), (1500, 12841), (1955, 17652), (2500, 19000)]  # 150 cm -> 12 841 L ; 195,5 cm -> 17 652 L ; haut. table 250 cm
GASOIL_TABLE = [(0, 0), (1430, 11571), (2000, 20000)]  # 143 cm -> 11 571 L ; table jusqu'à 200 cm


async def _put_table(client, h, tank_id, points):
    res = await client.put(f"{BASE}/tanks/{tank_id}/calibration-points", json={"points": [{"heightMm": a, "volumeLiters": b} for a, b in points]}, headers=h)
    assert res.status_code in (200, 201), res.text


async def _setup(client, h, organization, tables: bool = True, super_opening: str = "14487", gasoil_opening: str = "20108"):
    """Station (Super cuve 1 20 000 L, Gas-oil cuve 2 30 000 L), tour ouvert avec les stocks d'ouverture SOCADA."""
    ctx = await _ctx(client, h, organization)
    if tables:
        await _put_table(client, h, ctx["tanks"][0], SUPER_TABLE)
        await _put_table(client, h, ctx["tanks"][1], GASOIL_TABLE)
    occurrence = await _live_occurrence(ctx, rt=ctx["rt1"])
    context = await _context(client, h, ctx["station"])
    tank_lines = [{"tankId": ctx["tanks"][0], "openingStockLiters": super_opening}, {"tankId": ctx["tanks"][1], "openingStockLiters": gasoil_opening}]
    res = await client.post(f"{BASE}/shift-opening", json=_body(context, ctx, occurrence, tankLines=tank_lines), headers=h)
    assert res.status_code == 201, res.text
    ctx["report"] = res.json()
    ctx["reportId"] = res.json()["id"]
    return ctx


async def _set_sales(report_id: str, pump_sales: dict[str, str], closing_version: int = 1):
    """Simule D1 (index de fermeture enregistrés) : litres vendus par pompe et version de la fermeture."""
    from app.modules.zylo_liquid.models import ShiftReport, ShiftReportPumpLine

    async with AsyncSessionLocal() as db:
        for pump_id, sold in pump_sales.items():
            await db.execute(update(ShiftReportPumpLine).where(ShiftReportPumpLine.reportId == uuid.UUID(report_id), ShiftReportPumpLine.pumpId == uuid.UUID(pump_id)).values(soldLiters=Decimal(sold)))
        await db.execute(update(ShiftReport).where(ShiftReport.id == uuid.UUID(report_id)).values(closingVersion=closing_version, closingPhase="ready_to_close"))
        await db.commit()


async def _socada_sales(ctx):
    # Super (pompes 1+2) : 1 633,77 L ; Gas-oil (pompe 3) : 8 465,14 L.
    await _set_sales(ctx["reportId"], {ctx["pumps"][0]: "1000.00", ctx["pumps"][1]: "633.77", ctx["pumps"][2]: "8465.14"})


async def _view(client, h, ctx):
    res = await client.get(f"{BASE}/shift-reports/{ctx['reportId']}/closing-gauging", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def _line(view, tank_id):
    return next(l for l in view["lines"] if l["tankId"] == tank_id)


def _entry(view, tank_id, height, **over):
    entry = {"tankLineId": _line(view, tank_id)["tankLineId"], "heightCm": height, "method": "dipstick"}
    entry.update(over)
    return entry


async def _save(client, h, ctx, view, entries, version=None):
    return await client.put(
        f"{BASE}/shift-reports/{ctx['reportId']}/closing-gauging", json={"gaugingVersion": view["gaugingVersion"] if version is None else version, "lines": entries}, headers=h
    )


async def _declarations(client, h, ctx):
    res = await client.get(f"{BASE}/manual-gauging-declarations?stationId={ctx['station']}&limit=100", headers=h)
    assert res.status_code == 200, res.text
    return res.json()["data"]


def _errors(res) -> set:
    return {(d["cell"], d["field"], d["code"]) for d in res.json()["error"]["details"]}


# ---------------------------------------------------------------- lecture

async def test_read_before_measure_shows_table_and_nothing_invented(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    assert view["gaugingVersion"] == 0 and view["closingRecorded"] is False and view["closingVersion"] is None
    assert any(w["code"] == "closing_not_recorded" for w in view["warnings"])
    super_line = _line(view, ctx["tanks"][0])
    assert Decimal(super_line["openingStockLiters"]) == Decimal("14487") and super_line["recorded"] is False and super_line["realStockLiters"] is None
    assert super_line["calibration"]["available"] is True and len(super_line["calibration"]["points"]) == 4 and Decimal(super_line["calibration"]["maxHeightMm"]) == 2500
    # Pas de D1 : ventes, théorique et écart « non calculés » (jamais un 0 plausible) ; aucune réception : mention explicite.
    assert super_line["soldLiters"] is None and super_line["theoreticalStockLiters"] is None and super_line["stockVarianceLiters"] is None
    assert super_line["receptionDeclared"] is False and Decimal(super_line["receivedLiters"]) == 0 and super_line["telemetry"]["status"] == "not_measured"
    assert {m["userId"] for m in view["eligibleMeasurers"]} >= {ctx["rt1"], ctx["lead"]} and all("email" not in m for m in view["eligibleMeasurers"])


# ---------------------------------------------------------------- chiffres SOCADA

async def test_socada_figures_theoretical_real_and_variance(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    await _socada_sales(ctx)
    view = await _view(client, h, ctx)
    assert view["closingRecorded"] is True and view["closingVersion"] == 1
    assert Decimal(_line(view, ctx["tanks"][0])["theoreticalStockLiters"]) == Decimal("12853.23")  # 14 487 + 0 - 1 633,77
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143,0")])
    assert res.status_code == 200, res.text
    out = res.json()
    super_line, gas_line = _line(out, ctx["tanks"][0]), _line(out, ctx["tanks"][1])
    assert Decimal(super_line["realStockLiters"]) == Decimal("12841.00") and super_line["realStockSource"] == "calibration_table"
    assert Decimal(super_line["theoreticalStockLiters"]) == Decimal("12853.23") and Decimal(super_line["stockVarianceLiters"]) == Decimal("-12.23")
    assert Decimal(gas_line["realStockLiters"]) == Decimal("11571.00")
    assert Decimal(gas_line["theoreticalStockLiters"]) == Decimal("11642.86") and Decimal(gas_line["stockVarianceLiters"]) == Decimal("-71.86")
    assert Decimal(super_line["gaugingHeightMm"]) == Decimal("1500") and super_line["recorded"] is True and super_line["needsRecalculation"] is False
    assert out["gaugingVersion"] == 1 and {t["fuelProductName"] for t in out["productTotals"]} == {super_line["fuelProductName"], gas_line["fuelProductName"]}
    # La mesure alimente aussi la liste existante des jaugeages manuels (une déclaration par cuve, hauteur en mm).
    declarations = await _declarations(client, h, ctx)
    assert sorted(Decimal(str(d["declaredHeightMm"])) for d in declarations) == [Decimal("1430"), Decimal("1500")]
    # Le stock réel de la ligne de cuve du rapport est celui de la mesure (source du tour suivant).
    report = (await client.get(f"{BASE}/shift-reports/{ctx['reportId']}", headers=h)).json()
    assert {Decimal(l["closingRealStockLiters"]) for l in report["tankLines"]} == {Decimal("12841.00"), Decimal("11571.00")}


async def test_cahier_conversion_and_variance_without_d1(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Cahier du 22/07/2026 : 195,5 cm -> 17 652 L ; sans D1, mesure enregistrée mais écart non calculé (bandeau)."""
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], 195.5), _entry(view, ctx["tanks"][1], "100")])
    assert res.status_code == 200, res.text
    super_line = _line(res.json(), ctx["tanks"][0])
    assert Decimal(super_line["realStockLiters"]) == Decimal("17652.00")
    assert super_line["theoreticalStockLiters"] is None and super_line["stockVarianceLiters"] is None and res.json()["closingRecorded"] is False
    # Interpolation linéaire entre deux points de la table (100 cm : 1000 mm sur 0 -> 1430 mm = 11 571) : 8 091,61 L.
    assert Decimal(_line(res.json(), ctx["tanks"][1])["realStockLiters"]) == Decimal("8091.61")


# ---------------------------------------------------------------- refus et tout-ou-rien

async def test_all_or_nothing_with_cell_errors_in_french(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    # Cuve 1 valide, cuve 2 : 212 cm au-delà de la table (jusqu'à 200 cm).
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "212")])
    assert res.status_code == 422 and res.json()["error"]["code"] == "tank_gauging_invalid", res.text
    assert _errors(res) == {(f"tank:{ctx['tanks'][1]}", "heightCm", "height_out_of_table")}
    message = res.json()["error"]["details"][0]["message"]
    assert "212 cm dépasse la table de jaugeage de la cuve 2 (jusqu'à 200 cm)" in message and "Configuration > Cuves" in message
    assert await _declarations(client, h, ctx) == []  # aucune déclaration créée, aucune ligne modifiée
    after = await _view(client, h, ctx)
    assert after["gaugingVersion"] == 0 and all(l["recorded"] is False and l["realStockLiters"] is None for l in after["lines"])


async def test_every_error_is_reported_at_once(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], None, measuredByUserId=str(uuid.uuid4())), _entry(view, ctx["tanks"][1], "abc")])
    assert res.status_code == 422
    assert _errors(res) == {
        (f"tank:{ctx['tanks'][0]}", "heightCm", "gauging_missing"), (f"tank:{ctx['tanks'][0]}", "measuredByUserId", "measured_by_invalid"),
        (f"tank:{ctx['tanks'][1]}", "heightCm", "height_invalid"),
    }
    # Une ligne par cuve, pas une de plus ni de moins.
    only_one = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150")])
    assert _errors(only_one) == {(f"tank:{ctx['tanks'][1]}", "tankLineId", "tank_line_missing")}
    duplicate = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "100")])
    assert ("tank_line_duplicate" in {c for _, _, c in _errors(duplicate)})
    unknown = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "100"), {"tankLineId": str(uuid.uuid4()), "heightCm": "10"}])
    assert "tank_line_unknown" in {c for _, _, c in _errors(unknown)}
    assert await _declarations(client, h, ctx) == []


async def test_height_exceeds_tank_and_stock_exceeds_capacity(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    # Table de la cuve 1 qui dépasse la capacité (20 000 L) et la hauteur physique (3 000 mm) pour provoquer les deux refus.
    await _put_table(client, h, ctx["tanks"][0], [(0, 0), (2500, 19000), (2900, 45000)])
    view = await _view(client, h, ctx)
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "290"), _entry(view, ctx["tanks"][1], "310")])
    assert _errors(res) == {(f"tank:{ctx['tanks'][0]}", "heightCm", "stock_exceeds_capacity"), (f"tank:{ctx['tanks'][1]}", "heightCm", "height_exceeds_tank")}
    messages = {d["code"]: d["message"] for d in res.json()["error"]["details"]}
    assert "dépasse la capacité de la cuve 1" in messages["stock_exceeds_capacity"] and "dépasse la hauteur de la cuve 2 (300 cm)" in messages["height_exceeds_tank"]


async def test_missing_table_needs_referenced_paper_liters_never_invented(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization, tables=False)
    view = await _view(client, h, ctx)
    assert _line(view, ctx["tanks"][0])["calibration"]["available"] is False
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "119,5"), _entry(view, ctx["tanks"][1], "100")])
    assert _errors(res) == {(f"tank:{ctx['tanks'][0]}", "paperTable", "calibration_table_missing"), (f"tank:{ctx['tanks'][1]}", "paperTable", "calibration_table_missing")}
    short = await _save(client, h, ctx, view, [
        _entry(view, ctx["tanks"][0], "119,5", paperTable={"liters": "5413", "reference": "ab"}), _entry(view, ctx["tanks"][1], "100", paperTable={"liters": "45000", "reference": "Table papier"})
    ])
    assert _errors(short) == {(f"tank:{ctx['tanks'][0]}", "paperTable", "paper_reference_missing"), (f"tank:{ctx['tanks'][1]}", "heightCm", "stock_exceeds_capacity")}
    ok = await _save(client, h, ctx, view, [
        _entry(view, ctx["tanks"][0], "119,5", paperTable={"liters": "5413", "reference": "Table papier cuve P"}), _entry(view, ctx["tanks"][1], "100", paperTable={"liters": "8000,50", "reference": "Table papier cuve 2"})
    ])
    assert ok.status_code == 200, ok.text
    line = _line(ok.json(), ctx["tanks"][0])
    assert Decimal(line["realStockLiters"]) == Decimal("5413.00") and line["realStockSource"] == "paper_table" and line["paperTableReference"] == "Table papier cuve P"
    assert Decimal(line["gaugingHeightMm"]) == Decimal("1195")
    assert any(w["code"] == "paper_table" for w in ok.json()["warnings"])
    # Une table existe : les litres papier sont refusés (le serveur convertit et fait foi).
    await _put_table(client, h, ctx["tanks"][0], SUPER_TABLE)
    view2 = await _view(client, h, ctx)
    refused = await _save(client, h, ctx, view2, [_entry(view2, ctx["tanks"][0], "150", paperTable={"liters": "1", "reference": "Table papier"}), _entry(view2, ctx["tanks"][1], "100", paperTable={"liters": "8000.5", "reference": "Table papier cuve 2"})])
    assert (f"tank:{ctx['tanks'][0]}", "paperTable", "paper_table_not_allowed") in _errors(refused)


async def test_gauging_time_rules(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    future = (_now() + timedelta(hours=2)).isoformat()  # sans fuseau = heure locale de la station
    before_opening = (_now() - timedelta(hours=3)).isoformat()
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150", gaugedAt=future), _entry(view, ctx["tanks"][1], "100", gaugedAt=before_opening)])
    assert _errors(res) == {(f"tank:{ctx['tanks'][0]}", "gaugedAt", "gauging_time_invalid"), (f"tank:{ctx['tanks'][1]}", "gaugedAt", "gauging_time_invalid")}
    assert "ni avant l'ouverture du tour" in res.json()["error"]["details"][0]["message"]


# ---------------------------------------------------------------- réception

async def test_declared_reception_is_added_to_received_and_theoretical(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    await _socada_sales(ctx)
    res = await client.post(f"{BASE}/delivery-declarations", json={
        "stationId": ctx["station"], "eventAt": datetime.now(timezone.utc).isoformat(), "lines": [{"tankId": ctx["tanks"][0], "volumeLiters": 4000}],
    }, headers=h)
    assert res.status_code == 201, res.text
    view = await _view(client, h, ctx)
    super_line, gas_line = _line(view, ctx["tanks"][0]), _line(view, ctx["tanks"][1])
    assert Decimal(super_line["receivedLiters"]) == Decimal("4000") and super_line["receptionDeclared"] is True and super_line["receptionCount"] == 1
    assert Decimal(super_line["theoreticalStockLiters"]) == Decimal("16853.23")  # 14 487 + 4 000 - 1 633,77
    assert gas_line["receptionDeclared"] is False and Decimal(gas_line["receivedLiters"]) == 0  # « aucune réception déclarée », jamais un 0 silencieux
    saved = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "195,5"), _entry(view, ctx["tanks"][1], "143")])
    assert Decimal(_line(saved.json(), ctx["tanks"][0])["stockVarianceLiters"]) == Decimal("798.77")  # 17 652 - 16 853,23 (excédent)


# ---------------------------------------------------------------- ratures, version, recalcul

async def test_rature_creates_linked_declaration_and_unchanged_resave_creates_none(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    first = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143")])
    assert first.status_code == 200, first.text
    v1 = first.json()
    gaugings = {d["id"] for d in await _declarations(client, h, ctx)}
    assert len(gaugings) == 2
    # Ré-enregistrement identique (hauteur, méthode, heure) : aucune nouvelle déclaration, version incrémentée.
    same = await _save(client, h, ctx, v1, [_entry(v1, ctx["tanks"][0], "150", gaugedAt=_line(v1, ctx["tanks"][0])["gaugedAt"]), _entry(v1, ctx["tanks"][1], "143", gaugedAt=_line(v1, ctx["tanks"][1])["gaugedAt"])])
    assert same.status_code == 200, same.text
    assert {d["id"] for d in await _declarations(client, h, ctx)} == gaugings and same.json()["gaugingVersion"] == 2
    # Modifier une mesure enregistrée sans rature : refus ; version périmée : 409.
    v2 = same.json()
    no_reason = await _save(client, h, ctx, v2, [_entry(v2, ctx["tanks"][0], "155"), _entry(v2, ctx["tanks"][1], "143", gaugedAt=_line(v2, ctx["tanks"][1])["gaugedAt"])])
    assert _errors(no_reason) == {(f"tank:{ctx['tanks'][0]}", "rature", "rature_reason_missing")}
    stale = await _save(client, h, ctx, v2, [_entry(v2, ctx["tanks"][0], "150"), _entry(v2, ctx["tanks"][1], "143")], version=0)
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "gauging_version_changed" and "Rechargez" in stale.json()["error"]["message"]
    rature = {"reasonCode": "other", "reasonNote": "court", "initialedByUserId": ctx["lead"]}
    short_note = await _save(client, h, ctx, v2, [_entry(v2, ctx["tanks"][0], "155", rature=rature), _entry(v2, ctx["tanks"][1], "143", gaugedAt=_line(v2, ctx["tanks"][1])["gaugedAt"])])
    assert _errors(short_note) == {(f"tank:{ctx['tanks'][0]}", "rature", "rature_note_missing")}
    ok = await _save(client, h, ctx, v2, [
        _entry(v2, ctx["tanks"][0], "155", rature={"reasonCode": "reading_error", "initialedByUserId": ctx["lead"]}),
        _entry(v2, ctx["tanks"][1], "143", gaugedAt=_line(v2, ctx["tanks"][1])["gaugedAt"]),
    ])
    assert ok.status_code == 200, ok.text
    line = _line(ok.json(), ctx["tanks"][0])
    assert len(line["history"]) == 2 and line["history"][0]["current"] is True and line["history"][1]["current"] is False
    assert Decimal(line["history"][0]["heightMm"]) == Decimal("1550") and Decimal(line["history"][1]["heightMm"]) == Decimal("1500")  # l'ancienne mesure est conservée
    assert "Erreur de lecture" in line["history"][0]["changeReason"] and line["lastCorrectionInitialedByUserId"] == ctx["lead"]
    assert len(await _declarations(client, h, ctx)) == 3
    from app.modules.zylo_liquid.models import ManualGaugingDeclaration

    async with AsyncSessionLocal() as db:
        new = await db.get(ManualGaugingDeclaration, uuid.UUID(line["gaugingDeclarationId"]))
        assert str(new.correctsDeclarationId) == line["history"][1]["declarationId"]


async def test_closing_change_marks_lines_to_recalculate(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    await _socada_sales(ctx)
    view = await _view(client, h, ctx)
    saved = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143")])
    assert all(l["needsRecalculation"] is False for l in saved.json()["lines"])
    # D1 corrigé après D2 (rature d'un index) : la version de fermeture change, les lignes passent « à recalculer ».
    await _set_sales(ctx["reportId"], {ctx["pumps"][0]: "1100.00"}, closing_version=2)
    stale = await _view(client, h, ctx)
    assert all(l["needsRecalculation"] is True for l in stale["lines"]) and any(w["code"] == "needs_recalculation" for w in stale["warnings"])
    assert Decimal(_line(stale, ctx["tanks"][0])["stockVarianceLiters"]) == Decimal("-12.23")  # chiffres figés jusqu'au ré-enregistrement
    again = await _save(client, h, ctx, stale, [_entry(stale, ctx["tanks"][0], "150", gaugedAt=_line(stale, ctx["tanks"][0])["gaugedAt"]), _entry(stale, ctx["tanks"][1], "143", gaugedAt=_line(stale, ctx["tanks"][1])["gaugedAt"])])
    assert again.status_code == 200, again.text
    line = _line(again.json(), ctx["tanks"][0])
    assert line["needsRecalculation"] is False and Decimal(line["soldLiters"]) == Decimal("1733.77") and Decimal(line["stockVarianceLiters"]) == Decimal("87.77")
    assert len(await _declarations(client, h, ctx)) == 2  # les hauteurs sont conservées, aucune nouvelle déclaration


async def test_non_sale_exits_net_of_returns(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid.models import ShiftReportPumpLine

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    await _socada_sales(ctx)
    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftReportPumpLine).where(ShiftReportPumpLine.reportId == uuid.UUID(ctx["reportId"]), ShiftReportPumpLine.pumpId == uuid.UUID(ctx["pumps"][0])).values(exitsLiters=Decimal("20"), tankReturnLiters=Decimal("15")))
        await db.commit()
    line = _line(await _view(client, h, ctx), ctx["tanks"][0])
    assert Decimal(line["nonSaleOutLiters"]) == Decimal("5.00") and Decimal(line["theoreticalStockLiters"]) == Decimal("12848.23")  # 14 487 - 1 633,77 - 5


# ---------------------------------------------------------------- télémétrie

async def test_telemetry_compare_is_displayed_never_merged(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid.models import HolykellAccount, HolykellDeviceRegistry, TankMeasurement, TankSensorMapping

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    async with AsyncSessionLocal() as db:
        account = HolykellAccount(organizationId=uuid.UUID(zylo_liquid_organization["id"]), holykellUsername="u", holykellPasswordChiffre=chiffrer("p"))
        db.add(account)
        await db.flush()
        registry = HolykellDeviceRegistry(
            holykellAccountId=account.id, hkGroupId=1, hkGroupName="G", hkDeviceId=1, hkSerialNumber=f"SN{suffix}",
            hkSensorId=int(uuid.uuid4().int % 900000) + 100000, hkSensorName="Level", syncFrom=datetime(2026, 1, 1), discoveredAt=datetime(2026, 1, 1),
        )
        db.add(registry)
        await db.flush()
        db.add(TankSensorMapping(tankId=uuid.UUID(ctx["tanks"][0]), hkSensorId=registry.hkSensorId, measurementType="product_level", active=True, validFrom=datetime(2026, 1, 1), createdAt=datetime(2026, 1, 1)))
        db.add(TankMeasurement(hkSensorId=registry.hkSensorId, hkDeviceSerial=registry.hkSerialNumber, measuredAt=now_naive - timedelta(minutes=2), rawValue=1494, insertedAt=now_naive))
        await db.commit()
    view = await _view(client, h, ctx)
    res = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143")])
    assert res.status_code == 200, res.text
    out = res.json()
    t1, t2 = _line(out, ctx["tanks"][0]), _line(out, ctx["tanks"][1])
    assert t1["telemetry"]["status"] == "matched" and Decimal(t1["telemetry"]["deltaMm"]) == Decimal("6") and Decimal(t1["telemetry"]["telemetryHeightMm"]) == Decimal("1494")
    assert Decimal(t1["telemetry"]["toleranceMm"]) == Decimal("10") and abs(t1["telemetry"]["offsetMinutes"]) <= 5 and t1["telemetry"]["telemetryLiters"] is not None
    # Le stock réel reste la mesure à la règle (12 841), jamais la valeur du capteur.
    assert Decimal(t1["realStockLiters"]) == Decimal("12841.00") and Decimal(t1["telemetry"]["telemetryLiters"]) != Decimal(t1["realStockLiters"])
    assert t2["telemetry"]["status"] == "not_comparable" and t2["telemetry"]["telemetryHeightMm"] is None  # pas de capteur : jamais une valeur par défaut
    # Rapprochement existant réutilisé : la déclaration porte son ReconciliationRecord.
    assert t1["telemetry"]["reconciliationId"] is not None


# ---------------------------------------------------------------- tour clos, report, droits

async def test_closed_shift_is_read_only_and_real_stock_is_carried_to_next_shift(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    from app.modules.zylo_liquid.models import ShiftOccurrence

    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h, zylo_liquid_organization)
    view = await _view(client, h, ctx)
    saved = await _save(client, h, ctx, view, [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143")])
    assert saved.status_code == 200, saved.text
    async with AsyncSessionLocal() as db:
        await db.execute(update(ShiftOccurrence).where(ShiftOccurrence.id == uuid.UUID(ctx["report"]["occurrenceId"])).values(status="closed"))
        await db.commit()
    again = await _save(client, h, ctx, saved.json(), [_entry(view, ctx["tanks"][0], "151", rature={"reasonCode": "wrong_dip", "initialedByUserId": ctx["lead"]}), _entry(view, ctx["tanks"][1], "143")])
    assert again.status_code == 409 and again.json()["error"]["code"] == "shift_not_open"
    # Le stock réel de fermeture devient l'ouverture du tour suivant (B3) : égalité exacte.
    await _live_occurrence(ctx, shift_index=1, rt=ctx["rt1"], starts_in=timedelta(minutes=-5))
    context = await _context(client, h, ctx["station"])
    carried = {t["tankId"]: Decimal(t["carriedStockLiters"]) for t in context["tanks"]}
    assert carried[ctx["tanks"][0]] == Decimal("12841.00") and carried[ctx["tanks"][1]] == Decimal("11571.00")


async def test_permissions_and_station_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    owner = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, owner, zylo_liquid_organization)
    other = await _ctx(client, owner, zylo_liquid_organization)
    view = await _view(client, owner, ctx)
    entries = [_entry(view, ctx["tanks"][0], "150"), _entry(view, ctx["tanks"][1], "143")]

    attendant, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_pump_attendant", ctx["station"])
    assert (await client.get(f"{BASE}/shift-reports/{ctx['reportId']}/closing-gauging", headers=attendant)).status_code == 403
    assert (await _save(client, attendant, ctx, view, entries)).status_code == 403

    lead, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_team_lead", ctx["station"])
    assert (await client.get(f"{BASE}/shift-reports/{ctx['reportId']}/closing-gauging", headers=lead)).status_code == 200  # le chef d'équipe lit
    assert (await _save(client, lead, ctx, view, entries)).status_code == 403  # il aide à la règle, il n'écrit pas

    rt_other, _ = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_shift_manager", other["station"])
    assert (await client.get(f"{BASE}/shift-reports/{ctx['reportId']}/closing-gauging", headers=rt_other)).status_code == 403
    assert (await _save(client, rt_other, ctx, view, entries)).status_code == 403

    rt, rt_id = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_shift_manager", ctx["station"])
    manager, manager_id = await _scoped_user(client, owner, zylo_liquid_organization, "zylo_liquid_station_admin", ctx["station"])
    assert (await _save(client, rt, ctx, view, entries)).status_code == 200  # le RT saisit
    v1 = await _view(client, manager, ctx)
    saved = await _save(client, manager, ctx, v1, [_entry(v1, ctx["tanks"][0], "150", gaugedAt=_line(v1, ctx["tanks"][0])["gaugedAt"]), _entry(v1, ctx["tanks"][1], "143", gaugedAt=_line(v1, ctx["tanks"][1])["gaugedAt"])])
    assert saved.status_code == 200, saved.text  # le gérant saisit « à la place » (tracé : auteur = lui)
    from app.audit.models import AuditLog

    async with AsyncSessionLocal() as db:
        events = (await db.execute(select(AuditLog).where(AuditLog.action == "zyloLiquid.tankGauging.save", AuditLog.entityId == uuid.UUID(ctx["reportId"])))).scalars().all()
    assert len(events) == 2 and {str(e.actorUserId) for e in events} == {rt_id, manager_id}


def test_default_role_matrix_for_tank_gauging():
    """RT et gérant écrivent (gérant ⊇ RT) ; chef d'équipe, caissier, auditeur lisent ; le pompiste n'a rien."""
    from app.modules.zylo_liquid.permissions import TANK_GAUGING_MANAGE, TANK_GAUGING_READ
    from app.modules.zylo_liquid.roles_seed import DEFAULT_ROLES

    by_code = {code: set(perms) for code, _name, perms in DEFAULT_ROLES}
    assert TANK_GAUGING_READ == "zyloLiquid.tankGauging.read" and TANK_GAUGING_MANAGE == "zyloLiquid.tankGauging.manage"
    for writer in ("zylo_liquid_shift_manager", "zylo_liquid_station_admin"):
        assert {TANK_GAUGING_READ, TANK_GAUGING_MANAGE} <= by_code[writer], writer
    assert by_code["zylo_liquid_shift_manager"] & {TANK_GAUGING_READ, TANK_GAUGING_MANAGE} <= by_code["zylo_liquid_station_admin"]
    for reader in ("zylo_liquid_team_lead", "zylo_liquid_cashier", "zylo_liquid_auditor"):
        assert TANK_GAUGING_READ in by_code[reader] and TANK_GAUGING_MANAGE not in by_code[reader], reader
    assert not by_code["zylo_liquid_pump_attendant"] & {TANK_GAUGING_READ, TANK_GAUGING_MANAGE}
