"""Scénario A1 (configurer les pompes) : nom généré, numéro unique par
station, création unitaire et en lot (tout-ou-rien), resynchronisation du nom,
pompe inactive refusée à la vente, droits par station."""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency


BASE = "/api/v1/zylo-liquid"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _station(client: AsyncClient, headers: dict, suffix: str, label: str = "") -> str:
    res = await client.post(f"{BASE}/stations", json={"name": f"Station {label}{suffix}", "code": f"S{label}{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _product(client: AsyncClient, headers: dict, name: str, code: str) -> str:
    res = await client.post(f"{BASE}/fuel-products", json={"name": name, "code": code}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _tank(client: AsyncClient, headers: dict, station_id: str, product_id: str, number: int = 1) -> str:
    res = await client.post(
        f"{BASE}/tanks",
        json={
            "stationId": station_id, "fuelProductId": product_id, "tankNumber": number, "displayName": f"Cuve {number}",
            "capacityLiters": 20000, "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _setup(client: AsyncClient, headers: dict) -> dict:
    suffix = uuid.uuid4().hex[:6]
    station = await _station(client, headers, suffix)
    super_id = await _product(client, headers, f"Super{suffix}", f"SU{suffix}")
    gasoil_id = await _product(client, headers, f"Gasoil{suffix}", f"GA{suffix}")
    return {
        "suffix": suffix, "station": station, "super": super_id, "gasoil": gasoil_id,
        "tankSuper": await _tank(client, headers, station, super_id, 1),
        "tankGasoil": await _tank(client, headers, station, gasoil_id, 2),
    }


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
        json={"userId": str(user_id), "roleId": role["id"], "resourceType": "station", "resourceId": station_id},
        headers=owner_headers,
    )
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"]}


async def _currency() -> str:
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        for _ in range(10):
            currency = Currency(code=uuid.uuid4().hex[:3].upper(), name="Pump Currency", symbol="T", decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            return str(currency.id)
    raise AssertionError("devise")


async def _create_pump(client, headers, ctx, tank="tankSuper", **extra):
    return await client.post(f"{BASE}/pumps", json={"stationId": ctx["station"], "tankId": ctx[tank], **extra}, headers=headers)


async def test_create_pump_generates_name_and_product(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    res = await _create_pump(client, h, ctx, pumpNumber=3, brand="Tokheim", serialNumber="SN1", installedOn="2025-05-01")
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["name"] == f"Pompe N° 3 – Super{ctx['suffix']}"
    assert body["pumpNumber"] == 3 and body["brand"] == "Tokheim" and body["installedOn"] == "2025-05-01"
    assert body["fuelProductId"] == ctx["super"] and body["fuelProductName"] == f"Super{ctx['suffix']}"

    # Sans numéro : prochain numéro libre de la station.
    auto = await _create_pump(client, h, ctx, tank="tankGasoil")
    assert auto.status_code == 201
    assert auto.json()["pumpNumber"] == 4


async def test_pump_name_is_not_accepted_as_input(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    res = await _create_pump(client, h, ctx, pumpNumber=1, name="Libre")
    assert res.status_code == 201
    assert res.json()["name"].startswith("Pompe N° 1 – ")


async def test_pump_number_unique_per_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    assert (await _create_pump(client, h, ctx, pumpNumber=1)).status_code == 201
    dup = await _create_pump(client, h, ctx, tank="tankGasoil", pumpNumber=1)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "pump_number_taken"
    assert "Pompe N° 1" in dup.json()["error"]["message"]

    # Même numéro dans une AUTRE station : autorisé (D1).
    other = await _setup(client, h)
    assert (await _create_pump(client, h, other, pumpNumber=1)).status_code == 201


async def test_bulk_create_success(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    res = await client.post(
        f"{BASE}/pumps/bulk",
        json={"stationId": ctx["station"], "rows": [
            {"rowNumber": 1, "tankId": ctx["tankSuper"], "pumpNumber": 1},
            {"rowNumber": 2, "tankId": ctx["tankGasoil"], "pumpNumber": 2, "brand": "Gilbarco", "installedOn": "2024-01-02"},
        ]},
        headers=h,
    )
    assert res.status_code == 201, res.text
    assert res.json()["createdCount"] == 2
    assert [p["pumpNumber"] for p in res.json()["data"]] == [1, 2]

    listing = await client.get(f"{BASE}/pumps?stationId={ctx['station']}", headers=h)
    assert [p["pumpNumber"] for p in listing.json()["data"]] == [1, 2]
    assert listing.json()["data"][1]["fuelProductName"] == f"Gasoil{ctx['suffix']}"


async def test_bulk_all_or_nothing_with_row_errors(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    assert (await _create_pump(client, h, ctx, pumpNumber=1)).status_code == 201
    res = await client.post(
        f"{BASE}/pumps/bulk",
        json={"stationId": ctx["station"], "rows": [
            {"rowNumber": 1, "tankId": ctx["tankSuper"], "pumpNumber": 2},
            {"rowNumber": 2, "tankId": ctx["tankGasoil"], "pumpNumber": 1},
            {"rowNumber": 3, "tankId": ctx["tankGasoil"], "pumpNumber": 5, "brand": "x" * 101},
        ]},
        headers=h,
    )
    assert res.status_code == 422, res.text
    error = res.json()["error"]
    assert error["code"] == "pump_bulk_invalid"
    pairs = {(d["rowNumber"], d["field"], d["code"]) for d in error["details"]}
    assert pairs == {(2, "pumpNumber", "pump_number_taken"), (3, "brand", "brand_too_long")}
    assert "déjà utilisé" in next(d["message"] for d in error["details"] if d["rowNumber"] == 2)

    # Rien n'a été écrit : seule la pompe préexistante reste, la ligne 1 (valide) n'est pas créée.
    listing = await client.get(f"{BASE}/pumps?stationId={ctx['station']}", headers=h)
    assert listing.json()["meta"]["total"] == 1


async def test_bulk_duplicate_number_in_batch(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    res = await client.post(
        f"{BASE}/pumps/bulk",
        json={"stationId": ctx["station"], "rows": [
            {"rowNumber": 1, "tankId": ctx["tankSuper"], "pumpNumber": 7},
            {"rowNumber": 2, "tankId": ctx["tankGasoil"], "pumpNumber": 7},
        ]},
        headers=h,
    )
    assert res.status_code == 422
    details = res.json()["error"]["details"]
    assert {d["rowNumber"] for d in details} == {1, 2}
    assert all(d["field"] == "pumpNumber" and d["code"] == "pump_number_duplicate_in_batch" for d in details)
    assert (await client.get(f"{BASE}/pumps?stationId={ctx['station']}", headers=h)).json()["meta"]["total"] == 0


async def test_bulk_tank_of_another_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    other = await _setup(client, h)
    res = await client.post(
        f"{BASE}/pumps/bulk",
        json={"stationId": ctx["station"], "rows": [{"rowNumber": 4, "tankId": other["tankSuper"], "pumpNumber": 1}]},
        headers=h,
    )
    assert res.status_code == 422
    detail = res.json()["error"]["details"][0]
    assert (detail["rowNumber"], detail["field"], detail["code"]) == (4, "tankId", "tank_not_in_station")


async def test_update_tank_change_regenerates_name(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    pump = (await _create_pump(client, h, ctx, pumpNumber=2)).json()
    res = await client.patch(f"{BASE}/pumps/{pump['id']}", json={"tankId": ctx["tankGasoil"]}, headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["name"] == f"Pompe N° 2 – Gasoil{ctx['suffix']}"
    assert res.json()["fuelProductId"] == ctx["gasoil"]

    renum = await client.patch(f"{BASE}/pumps/{pump['id']}", json={"pumpNumber": 9}, headers=h)
    assert renum.json()["name"] == f"Pompe N° 9 – Gasoil{ctx['suffix']}"

    # Désactivation : le nom ne bouge pas.
    off = await client.patch(f"{BASE}/pumps/{pump['id']}", json={"active": False}, headers=h)
    assert off.json()["active"] is False and off.json()["name"] == renum.json()["name"]


async def test_product_rename_and_tank_product_change_resync_names(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    pump = (await _create_pump(client, h, ctx, pumpNumber=1)).json()

    ren = await client.patch(f"{BASE}/fuel-products/{ctx['super']}", json={"name": f"Premium{ctx['suffix']}"}, headers=h)
    assert ren.status_code == 200, ren.text
    assert (await client.get(f"{BASE}/pumps/{pump['id']}", headers=h)).json()["name"] == f"Pompe N° 1 – Premium{ctx['suffix']}"

    chg = await client.patch(f"{BASE}/tanks/{ctx['tankSuper']}", json={"fuelProductId": ctx["gasoil"]}, headers=h)
    assert chg.status_code == 200, chg.text
    got = (await client.get(f"{BASE}/pumps/{pump['id']}", headers=h)).json()
    assert got["name"] == f"Pompe N° 1 – Gasoil{ctx['suffix']}" and got["fuelProductId"] == ctx["gasoil"]


async def test_inactive_pump_refused_for_sale(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    pump = (await _create_pump(client, h, ctx, pumpNumber=1)).json()
    currency_id = await _currency()
    payload = {
        "stationId": ctx["station"], "eventAt": "2026-02-01T10:00:00", "fuelProductId": ctx["super"],
        "quantityLiters": 10, "priceAmount": 800, "currencyId": currency_id, "paymentMethod": "cash", "pumpId": pump["id"],
    }
    assert (await client.post(f"{BASE}/sales", json=payload, headers=h)).status_code == 201

    await client.patch(f"{BASE}/pumps/{pump['id']}", json={"active": False}, headers=h)
    res = await client.post(f"{BASE}/sales", json=payload, headers=h)
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "pump_inactive"


async def test_pump_attendant_reads_own_station_but_cannot_write(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    other = await _setup(client, h)
    pump = (await _create_pump(client, h, ctx, pumpNumber=1)).json()
    await _create_pump(client, h, other, pumpNumber=1)

    attendant = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_pump_attendant", ctx["station"])
    listing = await client.get(f"{BASE}/pumps", headers=attendant)
    assert listing.status_code == 200, listing.text
    assert {p["stationId"] for p in listing.json()["data"]} == {ctx["station"]}

    assert (await _create_pump(client, attendant, ctx, pumpNumber=5)).status_code == 403
    assert (await client.patch(f"{BASE}/pumps/{pump['id']}", json={"active": False}, headers=attendant)).status_code == 403
    bulk = await client.post(f"{BASE}/pumps/bulk", json={"stationId": ctx["station"], "rows": [{"rowNumber": 1, "tankId": ctx["tankSuper"], "pumpNumber": 6}]}, headers=attendant)
    assert bulk.status_code == 403


async def test_team_lead_cannot_create_pump(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    h = _headers(registered_user, zylo_liquid_organization)
    ctx = await _setup(client, h)
    lead = await _scoped_user(client, h, zylo_liquid_organization, "zylo_liquid_team_lead", ctx["station"])
    assert (await client.get(f"{BASE}/pumps?stationId={ctx['station']}", headers=lead)).status_code == 200
    assert (await _create_pump(client, lead, ctx, pumpNumber=1)).status_code == 403
