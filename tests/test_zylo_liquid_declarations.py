"""Tests de la couche déclarative (processus-double-sources-verite, Phase 5-8,
Bloc 1/2 de 08-plan-implementation.md) : cycle de vie (declared -> locked),
modification en place réservée à l'auteur et à l'état 'declared', verrouillage
irréversible, portée station. Un seul type (DeliveryDeclaration) est testé en
profondeur ; les 5 autres partagent la même logique factorée côté service
(_list_declarations/_lock_declaration/_update_declaration_in_place) — un test
de fumée suffit pour eux, la logique commune étant déjà couverte en profondeur."""

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _setup_station_and_product(client: AsyncClient, headers: dict, suffix: str) -> tuple[str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {suffix}", "code": f"P{suffix[:8]}"}, headers=headers)
    return st_res.json()["id"], fp_res.json()["id"]


async def _setup_tank(client: AsyncClient, headers: dict, station_id: str, fuel_product_id: str, suffix: str) -> str:
    res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "fuelProductId": fuel_product_id,
            "tankNumber": 1,
            "displayName": f"Cuve {suffix}",
            "capacityLiters": 20000,
            "tankHeightMm": 3000,
            "heightAlarmMm": 2800,
            "heightAlertMm": 2600,
            "lowAlarmMm": 300,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_create_delivery_declaration(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)

    res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id,
            "fuelProductId": fuel_product_id,
            "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 5000,
            "supplierName": "Fournisseur Test",
            "deliveryNoteReference": "BL-2026-001",
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["lifecycleStatus"] == "declared"
    assert body["declaredVolumeLiters"] == 5000
    assert body["reconciledWithId"] is None


async def test_delivery_declaration_can_be_updated_by_author_while_declared(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    create_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = create_res.json()["id"]

    update_res = await client.patch(
        f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}",
        json={"declaredVolumeLiters": 5200, "changeReason": "Correction du volume relevé"},
        headers=headers,
    )
    assert update_res.status_code == 200, update_res.text
    assert update_res.json()["declaredVolumeLiters"] == 5200


async def test_delivery_declaration_lock_is_irreversible_and_blocks_further_update(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    create_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = create_res.json()["id"]

    lock_res = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}/lock", headers=headers)
    assert lock_res.status_code == 200, lock_res.text
    assert lock_res.json()["lifecycleStatus"] == "locked"

    second_lock = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}/lock", headers=headers)
    assert second_lock.status_code == 409
    assert second_lock.json()["error"]["code"] == "declaration_already_locked"

    update_after_lock = await client.patch(
        f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}", json={"declaredVolumeLiters": 9999}, headers=headers
    )
    assert update_after_lock.status_code == 409
    assert update_after_lock.json()["error"]["code"] == "declaration_locked"


async def test_delivery_declaration_correction_references_original_via_correctsDeclarationId(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    original_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    original_id = original_res.json()["id"]
    await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{original_id}/lock", headers=headers)

    correction_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id,
            "fuelProductId": fuel_product_id,
            "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 5200,
            "correctsDeclarationId": original_id,
            "changeReason": "Correction après vérification du bon de livraison papier",
        },
        headers=headers,
    )
    assert correction_res.status_code == 201, correction_res.text
    assert correction_res.json()["correctsDeclarationId"] == original_id
    # L'originale reste inchangée — jamais réécrite (Phase 5 §3).
    list_res = await client.get(f"/api/v1/zylo-liquid/delivery-declarations?stationId={station_id}", headers=headers)
    original_row = next(r for r in list_res.json()["data"] if r["id"] == original_id)
    assert original_row["declaredVolumeLiters"] == 5000
    assert original_row["lifecycleStatus"] == "locked"


async def test_delivery_declaration_update_by_non_author_is_denied(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    create_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 5000},
        headers=headers,
    )
    declaration_id = create_res.json()["id"]

    other_email = f"other-{uuid.uuid4().hex[:8]}@example.com"
    other_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": other_email, "password": other_password, "fullName": "Other User"})
    other_login = await client.post("/api/v1/auth/login", json={"email": other_email, "password": other_password})
    other_token = other_login.json()["accessToken"]

    from app.identity.models import OrganizationUser, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        other_user = (await db.execute(select(User).where(User.email == other_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=other_user.id))
        await db.commit()

    other_headers = {"Authorization": f"Bearer {other_token}", "X-Organization-Id": zylo_liquid_organization["id"]}
    update_res = await client.patch(
        f"/api/v1/zylo-liquid/delivery-declarations/{declaration_id}", json={"declaredVolumeLiters": 1}, headers=other_headers
    )
    assert update_res.status_code == 403


async def test_list_delivery_declarations_filtered_by_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_a_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    station_b_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station B {suffix}", "code": f"STB{suffix}"}, headers=headers)
    station_b_id = station_b_res.json()["id"]

    await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_a_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 100},
        headers=headers,
    )
    await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={"stationId": station_b_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00", "declaredVolumeLiters": 200},
        headers=headers,
    )

    res = await client.get(f"/api/v1/zylo-liquid/delivery-declarations?stationId={station_a_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 1
    assert res.json()["data"][0]["declaredVolumeLiters"] == 100


async def test_station_scoped_pump_attendant_can_declare_and_is_blocked_outside_scope(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Vérifie réellement la portée par station pour la couche déclarative
    (permissions Bloc 2) — même mécanisme déjà éprouvé pour PriceHistory.

    Utilise shift-cash-declarations (pas delivery-declarations) : depuis
    l'alignement strict du rôle pompiste sur le prototype validé
    (`prototype.html`, ROLES.POMP/MATRICE — Livraisons/Stocks = null pour
    POMP, mission « vente-maintenant-reglementation »), le pompiste ne
    déclare plus de livraison — seul son propre shift/caisse reste dans son
    périmètre, avec verrouillage (clôture de son shift, DECLARATION_LOCK
    désormais accordé au pompiste pour ce seul usage)."""
    owner_headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_a_id, fuel_product_id = await _setup_station_and_product(client, owner_headers, suffix)
    tank_a_id = await _setup_tank(client, owner_headers, station_a_id, fuel_product_id, suffix)
    station_b_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station B {suffix}", "code": f"STB{suffix}"}, headers=owner_headers)
    station_b_id = station_b_res.json()["id"]
    tank_b_id = await _setup_tank(client, owner_headers, station_b_id, fuel_product_id, f"{suffix}b")
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        # `currency.code` est limité à 3 caractères (ISO 4217) et la base de
        # test est persistante entre les sessions : tirage renouvelé sur
        # violation d'unicité (pattern commun aux helpers `_create_currency`).
        for _ in range(10):
            currency = Currency(code=f"P{uuid.uuid4().hex[:2].upper()}", name="Pump Test Currency", symbol="P", decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            currency_id = str(currency.id)
            break
        else:
            raise AssertionError("impossible d'allouer un code devise unique")

    attendant_email = f"pompiste-{suffix}@example.com"
    attendant_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": attendant_email, "password": attendant_password, "fullName": "Pompiste Test"})
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
    assign_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/user-roles",
        json={"userId": str(attendant_user_id), "roleId": pump_attendant_role["id"], "resourceType": "station", "resourceId": station_a_id},
        headers=owner_headers,
    )
    assert assign_res.status_code == 201, assign_res.text

    attendant_headers = {"Authorization": f"Bearer {attendant_token}", "X-Organization-Id": zylo_liquid_organization["id"]}

    ok = await client.post(
        "/api/v1/zylo-liquid/shift-cash-declarations",
        json={
            "stationId": station_a_id, "tankId": tank_a_id, "eventAt": "2026-02-01T20:00:00",
            "shiftStart": "2026-02-01T08:00:00", "shiftEnd": "2026-02-01T20:00:00",
            "declaredCashAmount": 50000, "currencyId": currency_id,
        },
        headers=attendant_headers,
    )
    assert ok.status_code == 201, ok.text

    denied = await client.post(
        "/api/v1/zylo-liquid/shift-cash-declarations",
        json={
            "stationId": station_b_id, "tankId": tank_b_id, "eventAt": "2026-02-01T20:00:00",
            "shiftStart": "2026-02-01T08:00:00", "shiftEnd": "2026-02-01T20:00:00",
            "declaredCashAmount": 50000, "currencyId": currency_id,
        },
        headers=attendant_headers,
    )
    assert denied.status_code == 403

    # Le pompiste PEUT clôturer son propre shift (DECLARATION_LOCK accordé
    # pour cet usage précis, aligné sur "Clôturer mon shift" du prototype).
    lock_ok = await client.post(f"/api/v1/zylo-liquid/shift-cash-declarations/{ok.json()['id']}/lock", headers=attendant_headers)
    assert lock_ok.status_code == 200, lock_ok.text
    assert lock_ok.json()["lifecycleStatus"] == "locked"


async def test_shift_cash_declaration_smoke(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    tank_id = await _setup_tank(client, headers, station_id, fuel_product_id, suffix)
    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        for _ in range(10):
            currency = Currency(code=f"S{uuid.uuid4().hex[:2].upper()}", name="Smoke Currency", symbol="SC", decimalPlaces=0)
            db.add(currency)
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                continue
            await db.refresh(currency)
            currency_id = str(currency.id)
            break
        else:
            raise AssertionError("impossible d'allouer un code devise unique")

    res = await client.post(
        "/api/v1/zylo-liquid/shift-cash-declarations",
        json={
            "stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T20:00:00",
            "shiftStart": "2026-02-01T08:00:00", "shiftEnd": "2026-02-01T20:00:00",
            "declaredCashAmount": 150000, "currencyId": currency_id,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["lifecycleStatus"] == "declared"


async def test_manual_gauging_declaration_smoke(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    tank_id = await _setup_tank(client, headers, station_id, fuel_product_id, suffix)
    res = await client.post(
        "/api/v1/zylo-liquid/manual-gauging-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "declaredHeightMm": 1200, "method": "dipstick"},
        headers=headers,
    )
    assert res.status_code == 201, res.text


async def test_quality_check_declaration_smoke(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    tank_id = await _setup_tank(client, headers, station_id, fuel_product_id, suffix)
    res = await client.post(
        "/api/v1/zylo-liquid/quality-check-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "waterDetected": True, "waterHeightMm": 5, "method": "water_paste"},
        headers=headers,
    )
    assert res.status_code == 201, res.text


async def test_leak_test_declaration_smoke(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    tank_id = await _setup_tank(client, headers, station_id, fuel_product_id, suffix)
    res = await client.post(
        "/api/v1/zylo-liquid/leak-test-declarations",
        json={"stationId": station_id, "tankId": tank_id, "eventAt": "2026-02-01T08:00:00", "result": "normal"},
        headers=headers,
    )
    assert res.status_code == 201, res.text


async def test_incident_declaration_smoke_without_tank(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, _fuel_product_id = await _setup_station_and_product(client, headers, suffix)
    res = await client.post(
        "/api/v1/zylo-liquid/incident-declarations",
        json={"stationId": station_id, "eventAt": "2026-02-01T08:00:00", "category": "safety", "description": "Fuite d'huile constatée près de la piste 2."},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["tankId"] is None
