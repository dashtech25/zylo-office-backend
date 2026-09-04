import random
import string

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


def _random_currency_code() -> str:
    return "".join(random.choices(string.ascii_uppercase, k=3))


async def test_create_and_list_currency(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code = _random_currency_code()
    res = await client.post("/api/v1/currencies", json={"code": code, "name": "Franc CFA", "symbol": "FCFA", "decimalPlaces": 0}, headers=headers)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["code"] == code
    assert body["active"] is True

    # Pas de GET /currencies/{id} unitaire (seule la liste paginée existe,
    # Point 2 §7.1) — on vérifie la persistance via un PATCH à vide, qui
    # renvoie la ressource sans dépendre de l'ordre/pagination de la liste
    # (potentiellement grande, les devises créées par d'autres tests
    # s'accumulant dans la même base réelle).
    confirm_res = await client.patch(f"/api/v1/currencies/{body['id']}", json={}, headers=headers)
    assert confirm_res.status_code == 200
    assert confirm_res.json()["code"] == code


async def test_create_currency_duplicate_code_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code = _random_currency_code()
    await client.post("/api/v1/currencies", json={"code": code, "name": "Test", "symbol": "T"}, headers=headers)
    res = await client.post("/api/v1/currencies", json={"code": code, "name": "Test 2", "symbol": "T2"}, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "currency_code_already_used"


async def test_create_currency_invalid_format_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    res = await client.post("/api/v1/currencies", json={"code": "usd", "name": "Dollar", "symbol": "$"}, headers=headers)
    assert res.status_code == 422  # code doit être 3 lettres majuscules (ISO 4217)


async def test_update_currency_cannot_change_code(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code = _random_currency_code()
    create_res = await client.post("/api/v1/currencies", json={"code": code, "name": "Test", "symbol": "T"}, headers=headers)
    currency_id = create_res.json()["id"]

    patch_res = await client.patch(f"/api/v1/currencies/{currency_id}", json={"name": "Nouveau nom", "active": False}, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["name"] == "Nouveau nom"
    assert patch_res.json()["active"] is False
    assert patch_res.json()["code"] == code  # jamais modifiable (schéma ne l'expose pas)


async def test_currency_not_found(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    res = await client.get("/api/v1/currencies", headers=headers)
    assert res.status_code == 200
    patch_res = await client.patch("/api/v1/currencies/00000000-0000-0000-0000-000000000000", json={"name": "x"}, headers=headers)
    assert patch_res.status_code == 404
    assert patch_res.json()["error"]["code"] == "currency_not_found"


async def test_create_and_list_exchange_rate(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code1 = _random_currency_code()
    code2 = _random_currency_code()
    c1 = (await client.post("/api/v1/currencies", json={"code": code1, "name": "A", "symbol": "A"}, headers=headers)).json()
    c2 = (await client.post("/api/v1/currencies", json={"code": code2, "name": "B", "symbol": "B"}, headers=headers)).json()

    res = await client.post(
        "/api/v1/exchange-rates",
        json={"sourceCurrencyId": c1["id"], "targetCurrencyId": c2["id"], "rate": 1.5, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["rate"] == 1.5

    list_res = await client.get(f"/api/v1/exchange-rates?sourceCurrencyId={c1['id']}", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["meta"]["total"] == 1


async def test_create_exchange_rate_same_currency_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code = _random_currency_code()
    c1 = (await client.post("/api/v1/currencies", json={"code": code, "name": "A", "symbol": "A"}, headers=headers)).json()

    res = await client.post(
        "/api/v1/exchange-rates",
        json={"sourceCurrencyId": c1["id"], "targetCurrencyId": c1["id"], "rate": 1.0, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "exchange_rate_same_currency"


async def test_create_exchange_rate_duplicate_pair_and_date_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code1 = _random_currency_code()
    code2 = _random_currency_code()
    c1 = (await client.post("/api/v1/currencies", json={"code": code1, "name": "A", "symbol": "A"}, headers=headers)).json()
    c2 = (await client.post("/api/v1/currencies", json={"code": code2, "name": "B", "symbol": "B"}, headers=headers)).json()
    payload = {"sourceCurrencyId": c1["id"], "targetCurrencyId": c2["id"], "rate": 1.5, "effectiveFrom": "2026-02-01T00:00:00"}
    await client.post("/api/v1/exchange-rates", json=payload, headers=headers)
    res = await client.post("/api/v1/exchange-rates", json=payload, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "exchange_rate_already_exists"


async def test_create_exchange_rate_negative_rate_is_rejected(client: AsyncClient, registered_user: dict, organization: dict):
    headers = _headers(registered_user, organization)
    code1 = _random_currency_code()
    code2 = _random_currency_code()
    c1 = (await client.post("/api/v1/currencies", json={"code": code1, "name": "A", "symbol": "A"}, headers=headers)).json()
    c2 = (await client.post("/api/v1/currencies", json={"code": code2, "name": "B", "symbol": "B"}, headers=headers)).json()

    res = await client.post(
        "/api/v1/exchange-rates",
        json={"sourceCurrencyId": c1["id"], "targetCurrencyId": c2["id"], "rate": -1, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=headers,
    )
    assert res.status_code == 422


async def test_currencies_without_permission_is_denied(client: AsyncClient):
    res = await client.get("/api/v1/currencies")
    assert res.status_code == 401
