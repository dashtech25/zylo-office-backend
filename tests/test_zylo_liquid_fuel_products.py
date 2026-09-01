import uuid

from httpx import AsyncClient

from tests.conftest import unique_email


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_create_and_get_fuel_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/fuel-products",
        json={"name": "Super", "code": "SP", "densityGPerCm3": 0.755, "currentPriceFcfa": 730, "displayColor": "#e11d48"},
        headers=headers,
    )
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "Super"
    assert body["code"] == "SP"
    assert body["active"] is True
    assert body["organizationId"] == zylo_liquid_organization["id"]

    get_res = await client.get(f"/api/v1/zylo-liquid/fuel-products/{body['id']}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == body["id"]


async def test_list_fuel_products_is_paginated_and_isolated_per_organization(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Gasoil", "code": "GO"}, headers=headers)

    list_res = await client.get("/api/v1/zylo-liquid/fuel-products", headers=headers)
    assert list_res.status_code == 200
    body = list_res.json()
    assert body["meta"]["total"] == 1
    assert body["data"][0]["code"] == "GO"

    # Une autre organisation, avec le module activé, ne doit voir aucun des
    # produits carburant de la première (isolation multi-tenant — justification
    # de l'extension organizationId, issue #23).
    other_email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": other_email, "password": "TestPassword123!", "fullName": "Other"})
    other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": "TestPassword123!"})
    other_user = other_login.json()
    other_org_res = await client.post(
        "/api/v1/organizations",
        json={"name": "Other Org", "slug": f"other-org-fp-test-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {other_user['accessToken']}"},
    )
    other_org = other_org_res.json()
    other_activate_res = await client.post(
        f"/api/v1/modules/organizations/{other_org['id']}/activate",
        json={"moduleCode": "zylo_liquid"},
        headers={"Authorization": f"Bearer {other_user['accessToken']}", "X-Organization-Id": other_org["id"]},
    )
    assert other_activate_res.status_code == 200, other_activate_res.text
    other_headers = {"Authorization": f"Bearer {other_user['accessToken']}", "X-Organization-Id": other_org["id"]}
    other_list_res = await client.get("/api/v1/zylo-liquid/fuel-products", headers=other_headers)
    assert other_list_res.status_code == 200
    assert other_list_res.json()["meta"]["total"] == 0


async def test_create_fuel_product_duplicate_code_same_organization_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = _headers(registered_user, zylo_liquid_organization)
    await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Pétrole lampant", "code": "PL"}, headers=headers)
    res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Pétrole lampant 2", "code": "PL"}, headers=headers)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "fuel_product_code_already_used"


async def test_update_fuel_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    create_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Kérosène", "code": "KE"}, headers=headers)
    fuel_product_id = create_res.json()["id"]

    patch_res = await client.patch(
        f"/api/v1/zylo-liquid/fuel-products/{fuel_product_id}", json={"currentPriceFcfa": 900, "active": False}, headers=headers
    )
    assert patch_res.status_code == 200
    body = patch_res.json()
    assert body["currentPriceFcfa"] == 900
    assert body["active"] is False
    assert body["code"] == "KE"  # code jamais modifiable par ce endpoint


async def test_fuel_product_not_found(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/fuel-products/00000000-0000-0000-0000-000000000000", headers=headers)
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "fuel_product_not_found"


async def test_create_fuel_product_without_permission_is_denied(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """Module activé mais pas de permission accordée (contrairement à
    zylo_liquid_organization) et module non activé du tout — deux cas de refus
    distincts à vérifier séparément (module_inactive vs permission_denied)."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Super", "code": "SP"}, headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "module_inactive"


async def test_create_fuel_product_without_organization_header_is_rejected(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict
):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": "Super", "code": "SP"}, headers=headers)
    assert res.status_code == 422


async def test_create_fuel_product_without_authentication_is_rejected(client: AsyncClient, zylo_liquid_organization: dict):
    res = await client.post(
        "/api/v1/zylo-liquid/fuel-products",
        json={"name": "Super", "code": "SP"},
        headers={"X-Organization-Id": zylo_liquid_organization["id"]},
    )
    assert res.status_code == 401
