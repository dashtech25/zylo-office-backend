"""Tests de la couche Commercial (processus-double-sources-verite, Phase 5
§5, Phase 7 §2-4, Bloc 3/4 de 08-plan-implementation.md) : compte client,
vente à crédit, blocage du dépassement de limite (décision explicite du
commanditaire, Phase 7 addendum point 2), paiement et écart de change réalisé
(Phase 5 §5.1)."""

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_currency(code_prefix: str) -> str:
    # `currency.code` est limité à 3 caractères (norme ISO 4217) et la base de
    # test est persistante entre les sessions : un code court déterministe
    # finit par entrer en collision. Code aléatoire + nouvelle tentative sur
    # violation d'unicité → tests idempotents, quel que soit le préfixe (le
    # préfixe n'a aucune valeur sémantique pour les assertions).
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        for _ in range(10):
            currency = Currency(code=uuid.uuid4().hex[:3].upper(), name="Test Currency", symbol="T", decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            return str(currency.id)
    raise AssertionError("impossible d'allouer un code devise unique")


async def _setup_station_and_product(client: AsyncClient, headers: dict, suffix: str) -> tuple[str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {suffix}", "code": f"P{suffix[:8]}"}, headers=headers)
    return st_res.json()["id"], fp_res.json()["id"]


async def test_create_commercial_account(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency("CA")
    res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts",
        json={"name": "Client Fleet Test", "currencyId": currency_id, "creditLimit": 1000000},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["active"] is True
    assert res.json()["creditLimit"] == 1000000


async def test_credit_sale_creates_receivable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("CS")
    account_res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Credit", "currencyId": currency_id, "creditLimit": 1000000}, headers=headers
    )
    account_id = account_res.json()["id"]

    sale_res = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={
            "stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id,
            "quantityLiters": 150, "priceAmount": 850, "currencyId": currency_id,
            "paymentMethod": "credit", "commercialAccountId": account_id,
        },
        headers=headers,
    )
    assert sale_res.status_code == 201, sale_res.text

    receivables_res = await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account_id}", headers=headers)
    assert receivables_res.status_code == 200
    assert receivables_res.json()["meta"]["total"] == 1
    receivable = receivables_res.json()["data"][0]
    assert receivable["amount"] == 150 * 850
    assert receivable["status"] == "open"


async def test_cash_sale_does_not_create_receivable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("CH")

    sale_res = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={
            "stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id,
            "quantityLiters": 50, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "cash",
        },
        headers=headers,
    )
    assert sale_res.status_code == 201, sale_res.text
    assert sale_res.json()["commercialAccountId"] is None


async def test_credit_sale_exceeding_limit_is_blocked(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Décision explicite du commanditaire (Phase 7 addendum point 2) :
    bloque la saisie, sans exception de rôle."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("CL")
    account_res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Limité", "currencyId": currency_id, "creditLimit": 10000}, headers=headers
    )
    account_id = account_res.json()["id"]

    res = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={
            "stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id,
            "quantityLiters": 100, "priceAmount": 850, "currencyId": currency_id,
            "paymentMethod": "credit", "commercialAccountId": account_id,
        },
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "credit_limit_exceeded"

    # Aucune créance ne doit avoir été créée pour cette tentative refusée.
    receivables_res = await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account_id}", headers=headers)
    assert receivables_res.json()["meta"]["total"] == 0


async def test_second_credit_sale_blocked_once_outstanding_reaches_limit(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("CO")
    account_res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Cumul", "currencyId": currency_id, "creditLimit": 20000}, headers=headers
    )
    account_id = account_res.json()["id"]

    first = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 20, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "credit", "commercialAccountId": account_id},
        headers=headers,
    )
    assert first.status_code == 201, first.text  # 16 000, sous la limite

    second = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T11:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 10, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "credit", "commercialAccountId": account_id},
        headers=headers,
    )
    assert second.status_code == 422  # 16 000 + 8 000 > 20 000
    assert second.json()["error"]["code"] == "credit_limit_exceeded"


async def test_payment_settles_receivable_same_currency(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("PS")
    account_res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Paiement", "currencyId": currency_id, "creditLimit": 100000}, headers=headers
    )
    account_id = account_res.json()["id"]
    await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 10, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "credit", "commercialAccountId": account_id},
        headers=headers,
    )
    receivable = (await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account_id}", headers=headers)).json()["data"][0]
    assert receivable["amount"] == 8000

    payment_res = await client.post(
        "/api/v1/zylo-liquid/payments",
        json={"receivableId": receivable["id"], "paidAt": "2026-02-05T09:00:00", "amount": 8000, "currencyId": currency_id},
        headers=headers,
    )
    assert payment_res.status_code == 201, payment_res.text

    updated = (await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account_id}", headers=headers)).json()["data"][0]
    assert updated["status"] == "settled"


async def test_payment_different_currency_requires_exchange_rate(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Phase 5 §5.1 : exchangeRateApplied obligatoire si la devise du
    paiement diffère de celle de la créance."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    receivable_currency_id = await _create_currency("RC")
    payment_currency_id = await _create_currency("PC")
    account_res = await client.post(
        "/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Devise", "currencyId": receivable_currency_id, "creditLimit": 100000}, headers=headers
    )
    account_id = account_res.json()["id"]
    await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 10, "priceAmount": 800, "currencyId": receivable_currency_id, "paymentMethod": "credit", "commercialAccountId": account_id},
        headers=headers,
    )
    receivable = (await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account_id}", headers=headers)).json()["data"][0]

    without_rate = await client.post(
        "/api/v1/zylo-liquid/payments",
        json={"receivableId": receivable["id"], "paidAt": "2026-02-05T09:00:00", "amount": 8000, "currencyId": payment_currency_id},
        headers=headers,
    )
    assert without_rate.status_code == 422
    assert without_rate.json()["error"]["code"] == "exchange_rate_required"

    with_rate = await client.post(
        "/api/v1/zylo-liquid/payments",
        json={"receivableId": receivable["id"], "paidAt": "2026-02-05T09:00:00", "amount": 8000, "currencyId": payment_currency_id, "exchangeRateApplied": 1.0},
        headers=headers,
    )
    assert with_rate.status_code == 201, with_rate.text
    assert with_rate.json()["exchangeRateApplied"] == 1.0


async def test_credit_sale_without_commercial_account_is_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    currency_id = await _create_currency("NC")
    res = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 10, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "credit"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "commercial_account_required"


async def test_pump_attendant_cannot_create_sale(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Phase 7 §4 : la qualification commerciale est réservée au
    gérant/caissier, jamais au pompiste."""
    owner_headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, owner_headers, suffix)
    currency_id = await _create_currency("PA")

    attendant_email = f"pompiste-com-{suffix}@example.com"
    attendant_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": attendant_email, "password": attendant_password, "fullName": "Pompiste Commercial Test"})
    login = await client.post("/api/v1/auth/login", json={"email": attendant_email, "password": attendant_password})
    attendant_token = login.json()["accessToken"]

    from app.identity.models import OrganizationUser, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        attendant_user = (await db.execute(select(User).where(User.email == attendant_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=attendant_user.id))
        await db.commit()
        attendant_user_id = attendant_user.id

    roles_res = await client.get(f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/roles", headers=owner_headers)
    pump_attendant_role = next(r for r in roles_res.json() if r["code"] == "zylo_liquid_pump_attendant")
    await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/user-roles",
        json={"userId": str(attendant_user_id), "roleId": pump_attendant_role["id"], "resourceType": "station", "resourceId": station_id},
        headers=owner_headers,
    )

    attendant_headers = {"Authorization": f"Bearer {attendant_token}", "X-Organization-Id": zylo_liquid_organization["id"]}
    res = await client.post(
        "/api/v1/zylo-liquid/sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "fuelProductId": fuel_product_id, "quantityLiters": 10, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "cash"},
        headers=attendant_headers,
    )
    assert res.status_code == 403
