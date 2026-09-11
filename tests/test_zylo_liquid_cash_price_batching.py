"""Régression pour la résolution de prix/devise batchée introduite dans
l'audit performance du 2026-09-11 (`_build_cash_price_contexts`,
`_CashPriceContext`, `_price_at_or_before`) : `get_network_cash_summary`
doit produire EXACTEMENT le même résultat qu'avant l'optimisation — prix
propre à la station, repli sur le prix réseau par défaut filtré par devise,
et découpage correct d'une vente à cheval sur un changement de prix — la
différence est uniquement le nombre de requêtes SQL, jamais le résultat.
Aucun test de caisse n'existait avant cet audit (trou de couverture
identifié en Phase 1)."""

import uuid
from datetime import datetime

from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.modules.zylo_liquid.models import HolykellDeviceRegistry, TankMeasurement
from app.shared.currency import Currency
from tests.conftest import register_holykell_sensor


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_currency() -> tuple[str, str]:
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        for _ in range(10):
            code = uuid.uuid4().hex[:3].upper()
            currency = Currency(code=code, name=code, symbol=code, decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            return str(currency.id), currency.code
    raise AssertionError("impossible d'allouer un code devise unique")


async def _create_tank(
    client: AsyncClient, headers: dict, organization_id: str, station_code: str, fuel_product_id: str, currency_override_id: str
) -> tuple[str, str, int]:
    st_res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": f"Station {station_code}", "code": station_code, "currencyOverrideId": currency_override_id},
        headers=headers,
    )
    assert st_res.status_code == 201, st_res.text
    station_id = st_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 40000,
            "tankHeightMm": 2000,
            "fuelProductId": fuel_product_id,
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    assert tank_res.status_code == 201, tank_res.text
    tank_id = tank_res.json()["id"]
    await client.put(
        f"/api/v1/zylo-liquid/tanks/{tank_id}/calibration-points",
        json={"points": [{"heightMm": 0, "volumeLiters": 0}, {"heightMm": 2000, "volumeLiters": 40000}]},
        headers=headers,
    )
    serial = f"XM_CASH_{uuid.uuid4().hex[:6]}"
    sensor_id = await register_holykell_sensor(organization_id, serial, "product_level")
    map_res = await client.post(
        "/api/v1/zylo-liquid/tank-sensor-mappings",
        json={"tankId": tank_id, "hkSerialNumber": serial, "measurementType": "product_level"},
        headers=headers,
    )
    assert map_res.status_code == 201, map_res.text
    return station_id, tank_id, sensor_id


async def _seed_measurements(sensor_id: int, points: list[tuple[datetime, float]]) -> None:
    async with AsyncSessionLocal() as db:
        for measured_at, height_mm in points:
            db.add(
                TankMeasurement(
                    hkSensorId=sensor_id,
                    hkDeviceSerial="XM_CASH",
                    hkUnit="mm",
                    measuredAt=measured_at,
                    rawValue=height_mm,
                    insertedAt=datetime.utcnow(),
                    isCorrection=False,
                )
            )
        # `hkLastStatus`/`lastValue` du registre n'entrent pas dans le calcul
        # de caisse (qui relit `TankMeasurement`, jamais le registre), mais
        # un registre "not_configured" ferait sortir la cuve du réseau actif
        # plus tôt dans la chaîne — on le renseigne pour rester réaliste.
        await db.execute(
            update(HolykellDeviceRegistry)
            .where(HolykellDeviceRegistry.hkSensorId == sensor_id)
            .values(lastValue=points[-1][1], lastValueAt=points[-1][0], hkLastStatus=1)
        )
        await db.commit()


async def test_network_cash_summary_mixes_station_price_and_batched_network_default(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Station A a son propre prix, qui CHANGE au milieu de la période —
    exerce le découpage en sous-segments (`_price_at_or_before` sur les
    prix propres à la station, déjà chargés, zéro requête par frontière).
    Station B n'a aucun prix propre : elle retombe sur le prix réseau par
    défaut — exerce le repli batché (`price_context.default_prices` filtré
    par la devise de la station, résolue une seule fois pour tout le
    réseau via `_build_cash_price_contexts`) qui remplace l'ancien
    `_resolve_applicable_price` appelé à chaque frontière de segment.

    Note : le découpage en sous-segments ne réagit qu'aux changements de
    prix PROPRES à la station (`price_changes_in_range` dans
    `_compute_tank_cash`, jamais le prix réseau par défaut) — comportement
    déjà présent avant cet audit, inchangé ici. Un changement du seul prix
    réseau par défaut ne scinde donc pas une vente : elle est valorisée en
    bloc au prix applicable à la fin de la fenêtre."""
    headers = _headers(registered_user, zylo_liquid_organization)
    org_id = zylo_liquid_organization["id"]

    currency_id, currency_code = await _create_currency()

    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Produit Cash", "code": "CASHP"}, headers=headers)
    assert fp_res.status_code == 201, fp_res.text
    fuel_product_id = fp_res.json()["id"]

    station_a, tank_a, sensor_a = await _create_tank(client, headers, org_id, "CASH-A", fuel_product_id, currency_id)
    station_b, tank_b, sensor_b = await _create_tank(client, headers, org_id, "CASH-B", fuel_product_id, currency_id)

    # Station A : prix propre qui change au milieu de la période testée.
    price_a1_res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_a, "fuelProductId": fuel_product_id, "priceAmount": 400, "currencyId": currency_id, "effectiveFrom": "2025-01-01T00:00:00"},
        headers=headers,
    )
    assert price_a1_res.status_code == 201, price_a1_res.text
    price_a2_res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_a, "fuelProductId": fuel_product_id, "priceAmount": 450, "currencyId": currency_id, "effectiveFrom": "2026-01-10T12:00:00"},
        headers=headers,
    )
    assert price_a2_res.status_code == 201, price_a2_res.text

    # Station B : aucun prix propre -> repli sur le prix réseau par défaut,
    # constant sur la période (le découpage par changement de prix réseau
    # n'est pas dans le périmètre de ce test, voir docstring).
    default_price_res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"fuelProductId": fuel_product_id, "priceAmount": 500, "currencyId": currency_id, "effectiveFrom": "2025-01-01T00:00:00"},
        headers=headers,
    )
    assert default_price_res.status_code == 201, default_price_res.text

    period_start = datetime(2026, 1, 10, 0, 0, 0)
    mid_period = datetime(2026, 1, 10, 12, 0, 0)
    period_end = datetime(2026, 1, 11, 0, 0, 0)

    # Tank A : 1000mm -> 900mm -> 800mm, avec un changement de prix station
    # PILE à l'instant de la frontière (12h). `_price_at_or_before`/
    # `_resolve_applicable_price` utilisent tous deux une comparaison
    # inclusive (`effectiveFrom <= at`) — le sous-segment qui SE TERMINE à
    # cet instant capte donc déjà le nouveau prix (450), exactement comme le
    # sous-segment suivant : les deux segments (2000 L chacun) sont
    # valorisés à 450, soit 4000 L à 450 = 1 800 000. Ce comportement est
    # préexistant (comparaison inclusive déjà présente avant cet audit),
    # pas introduit par le passage en résolution batchée — seul le NOMBRE
    # de requêtes SQL change, jamais ce résultat.
    await _seed_measurements(sensor_a, [(period_start, 1000.0), (mid_period, 900.0), (period_end, 800.0)])

    # Tank B : 1000mm -> 800mm sur toute la période = 4000 L, au prix réseau
    # par défaut constant de 500 -> 2 000 000.
    await _seed_measurements(sensor_b, [(period_start, 1000.0), (period_end, 800.0)])

    res = await client.get(
        "/api/v1/zylo-liquid/cash/network-summary",
        params={"fromDate": period_start.isoformat(), "toDate": period_end.isoformat(), "mode": "calendar"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["volumeSoldLitersTotal"] == 8000

    assert len(body["currencyBlocks"]) == 1
    block = body["currencyBlocks"][0]
    assert block["currencyCode"] == currency_code
    assert block["volumeSoldLiters"] == 8000
    assert block["monetaryValue"] == 3_800_000  # 1 800 000 (A, 4000 L à 450) + 2 000 000 (B, défaut réseau) -- jamais mixed_currencies

    stations_by_id = {s["stationId"]: s for s in block["stations"]}
    assert stations_by_id[station_a]["volumeSoldLiters"] == 4000
    assert stations_by_id[station_a]["monetaryValue"] == 1_800_000
    assert stations_by_id[station_b]["volumeSoldLiters"] == 4000
    assert stations_by_id[station_b]["monetaryValue"] == 2_000_000
    assert stations_by_id[station_b]["monetaryValueNotCalculableReason"] is None

    assert len(body["productBlocks"]) == 1
    product = body["productBlocks"][0]
    assert product["volumeSoldLiters"] == 8000
    assert product["monetaryValue"] == 3_800_000
    assert product["monetaryValueNotCalculableReason"] is None

    station_lines_by_id = {s["stationId"]: s for s in body["stationLines"]}
    assert station_lines_by_id[station_a]["monetaryValue"] == 1_800_000
    assert station_lines_by_id[station_b]["monetaryValue"] == 2_000_000


async def test_network_cash_summary_without_any_price_reports_reason_not_zero(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Aucun prix (ni station, ni réseau) configuré pour ce produit : le
    volume reste calculable, la valeur monétaire doit être `None` avec une
    raison explicite — jamais un zéro silencieux, y compris via le chemin
    batché (`price_context.default_prices` vide -> `price_at is None`)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    org_id = zylo_liquid_organization["id"]

    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Produit Sans Prix", "code": "NOPRICE"}, headers=headers)
    assert fp_res.status_code == 201, fp_res.text
    fuel_product_id = fp_res.json()["id"]

    currency_id, _ = await _create_currency()
    station_id, tank_id, sensor_id = await _create_tank(client, headers, org_id, "CASH-C", fuel_product_id, currency_id)

    period_start = datetime(2026, 1, 10, 0, 0, 0)
    period_end = datetime(2026, 1, 11, 0, 0, 0)
    await _seed_measurements(sensor_id, [(period_start, 1000.0), (period_end, 800.0)])

    res = await client.get(
        "/api/v1/zylo-liquid/cash/network-summary",
        params={"fromDate": period_start.isoformat(), "toDate": period_end.isoformat(), "mode": "calendar"},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["currencyBlocks"] == []
    assert body["volumeSoldLitersTotal"] == 4000  # le volume reste connu même sans prix

    # Au niveau agrégé (produit/station), la raison précise du tank
    # ("no_applicable_price") est généralisée en "incomplete_pricing" par
    # `get_network_cash_summary` dès qu'au moins une contribution est non
    # calculable — comportement d'agrégation préexistant, inchangé ici.
    product = body["productBlocks"][0]
    assert product["volumeSoldLiters"] == 4000
    assert product["monetaryValue"] is None
    assert product["monetaryValueNotCalculableReason"] == "incomplete_pricing"

    station_line = next(s for s in body["stationLines"] if s["stationId"] == station_id)
    assert station_line["monetaryValue"] is None
    assert station_line["monetaryValueNotCalculableReason"] == "incomplete_pricing"


async def test_compute_tank_cash_batched_context_matches_unbatched(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    """Preuve directe d'équivalence, au niveau service plutôt qu'HTTP :
    `_compute_tank_cash(..., price_context=None)` (ancien chemin, une
    requête par frontière) et `_compute_tank_cash(..., price_context=<batché>)`
    (nouveau chemin) doivent renvoyer EXACTEMENT le même dict pour la même
    cuve, la même période, un changement de prix propre à la station ET un
    repli sur le prix réseau par défaut dans la même période."""
    headers = _headers(registered_user, zylo_liquid_organization)
    org_id = zylo_liquid_organization["id"]

    currency_id, _ = await _create_currency()
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Produit Equiv", "code": "EQUIVP"}, headers=headers)
    fuel_product_id = fp_res.json()["id"]

    # Cuve avec prix propre changeant en cours de période.
    station_id, tank_id, sensor_id = await _create_tank(client, headers, org_id, "CASH-EQ1", fuel_product_id, currency_id)
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 400, "currencyId": currency_id, "effectiveFrom": "2025-01-01T00:00:00"},
        headers=headers,
    )
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 450, "currencyId": currency_id, "effectiveFrom": "2026-01-10T06:00:00"},
        headers=headers,
    )

    # Deuxième cuve, autre station, sans prix propre -> repli réseau.
    station_id2, tank_id2, sensor_id2 = await _create_tank(client, headers, org_id, "CASH-EQ2", fuel_product_id, currency_id)
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"fuelProductId": fuel_product_id, "priceAmount": 500, "currencyId": currency_id, "effectiveFrom": "2025-01-01T00:00:00"},
        headers=headers,
    )

    period_start = datetime(2026, 1, 10, 0, 0, 0)
    period_end = datetime(2026, 1, 11, 0, 0, 0)
    await _seed_measurements(sensor_id, [(period_start, 1000.0), (datetime(2026, 1, 10, 6, 0, 0), 950.0), (period_end, 800.0)])
    await _seed_measurements(sensor_id2, [(period_start, 1000.0), (period_end, 700.0)])

    from app.core.database import AsyncSessionLocal as SessionLocal
    from app.modules.zylo_liquid.service import _build_cash_price_contexts, _compute_tank_cash
    from app.modules.zylo_liquid.models import Tank

    async with SessionLocal() as db:
        tank = await db.get(Tank, uuid.UUID(tank_id))
        tank2 = await db.get(Tank, uuid.UUID(tank_id2))

        unbatched = await _compute_tank_cash(db, tank, period_start, period_end, price_context=None)
        unbatched2 = await _compute_tank_cash(db, tank2, period_start, period_end, price_context=None)

        contexts = await _build_cash_price_contexts(db, [tank, tank2])
        batched = await _compute_tank_cash(db, tank, period_start, period_end, price_context=contexts[tank.id])
        batched2 = await _compute_tank_cash(db, tank2, period_start, period_end, price_context=contexts[tank2.id])

    for field in ("volumeSoldLiters", "volumeNotCalculableReason", "monetaryValue", "currencyCode", "monetaryValueNotCalculableReason", "confidence", "anomalyTypes"):
        assert unbatched[field] == batched[field], f"tank1.{field}: {unbatched[field]!r} != {batched[field]!r}"
        assert unbatched2[field] == batched2[field], f"tank2.{field}: {unbatched2[field]!r} != {batched2[field]!r}"

    # Les segments (traçabilité complète) doivent aussi être identiques —
    # même volumes/montants par sous-segment, pas seulement le total.
    assert len(unbatched["segments"]) == len(batched["segments"])
    for seg_old, seg_new in zip(unbatched["segments"], batched["segments"]):
        assert seg_old["volumeLiters"] == seg_new["volumeLiters"]
        assert seg_old["monetaryValue"] == seg_new["monetaryValue"]
        assert seg_old["currencyCode"] == seg_new["currencyCode"]
