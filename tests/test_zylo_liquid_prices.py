import random
import string
import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency
from app.shared.geo import City, Country, Region


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


def _random_currency_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3))


async def _create_currency(code: str) -> str:
    async with AsyncSessionLocal() as db:
        currency = Currency(code=code, name=code, symbol=code, decimalPlaces=0)
        db.add(currency)
        await db.commit()
        await db.refresh(currency)
        return str(currency.id)


async def _create_city_with_currency(currency_code: str) -> str:
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        country = Country(isoCode2=suffix[:2].upper(), isoCode3=suffix[:3].upper(), name=f"Land {suffix}", currencyCode=currency_code)
        db.add(country)
        await db.flush()
        region = Region(countryId=country.id, name=f"Region {suffix}", code=f"R{suffix}")
        db.add(region)
        await db.flush()
        city = City(regionId=region.id, name=f"City {suffix}")
        db.add(city)
        await db.commit()
        await db.refresh(city)
        return str(city.id)


async def _create_station_and_product(client: AsyncClient, headers: dict, station_code: str, city_id: str | None = None) -> tuple[str, str]:
    payload = {"name": "Station Prix", "code": station_code}
    if city_id is not None:
        payload["cityId"] = city_id
    st_res = await client.post("/api/v1/zylo-liquid/stations", json=payload, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post(
        "/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {station_code}", "code": station_code[:10]}, headers=headers
    )
    return station_id, fp_res.json()["id"]


async def test_create_price_with_explicit_currency(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-01")
    currency_id = await _create_currency(_random_currency_code())

    res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={
            "stationId": station_id,
            "fuelProductId": fuel_product_id,
            "priceAmount": 730,
            "costAmount": 650,
            "currencyId": currency_id,
            "effectiveFrom": "2026-01-01T00:00:00",
            "changeReason": "Prix d'ouverture",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["priceAmount"] == 730
    assert body["currencyId"] == currency_id
    assert body["isFuture"] is False


async def test_create_price_resolves_default_currency_from_station_geography(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    code = _random_currency_code()
    currency_id = await _create_currency(code)
    city_id = await _create_city_with_currency(code)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-02", city_id=city_id)

    res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 800, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["currencyId"] == currency_id


async def test_create_price_without_city_and_without_currency_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-03")

    res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 800, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "station_currency_not_resolvable"


async def test_create_price_conflict_same_period(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-04")
    currency_id = await _create_currency(_random_currency_code())
    payload = {
        "stationId": station_id,
        "fuelProductId": fuel_product_id,
        "priceAmount": 730,
        "currencyId": currency_id,
        "effectiveFrom": "2026-01-01T00:00:00",
    }
    await client.post("/api/v1/zylo-liquid/prices", json=payload, headers=headers)
    res = await client.post("/api/v1/zylo-liquid/prices", json=payload, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "price_conflict_same_period"


async def test_create_price_future_date_is_flagged_not_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-05")
    currency_id = await _create_currency(_random_currency_code())

    res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 900, "currencyId": currency_id, "effectiveFrom": "2099-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 201  # accepté (prix planifié), jamais rejeté
    assert res.json()["isFuture"] is True


async def test_correct_price_cannot_change_period_station_or_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-06")
    currency_id = await _create_currency(_random_currency_code())
    create_res = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    price_id = create_res.json()["id"]

    patch_res = await client.patch(f"/api/v1/zylo-liquid/prices/{price_id}", json={"priceAmount": 750, "changeReason": "Correction erreur de saisie"}, headers=headers)
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["priceAmount"] == 750
    assert body["stationId"] == station_id  # inchangé
    assert body["effectiveFrom"] == "2026-01-01T00:00:00"  # inchangé


async def test_correct_price_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.patch("/api/v1/zylo-liquid/prices/00000000-0000-0000-0000-000000000000", json={"priceAmount": 100}, headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "price_history_not_found"


async def test_list_and_filter_prices(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    station_id, fuel_product_id = await _create_station_and_product(client, headers, "PRX-07")
    currency_id = await _create_currency(_random_currency_code())
    await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "priceAmount": 730, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )

    res = await client.get(f"/api/v1/zylo-liquid/prices?stationId={station_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 1


async def test_prices_without_permission_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.get("/api/v1/zylo-liquid/prices", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"
