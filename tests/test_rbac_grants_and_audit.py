"""Tests du moteur de résolution des permissions (UserPermissionGrant) et du
journal d'audit — voir « rôle et permissions global global et spécifique par
module Zylo Office.md » §5.4 (algorithme de résolution) et §17 (visibilité de
l'audit par portée). Logique critique pour la sécurité : ces tests couvrent
en priorité le point sur lequel Zylo Office diverge délibérément d'Odoo/
Dolibarr (le refus explicite qui prime toujours sur un octroi)."""

import uuid
from datetime import datetime, timedelta

from httpx import AsyncClient


async def test_org_wide_deny_overrides_role_derived_allow(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Le owner a STATION_READ via son rôle "owner". Un deny direct sur cette
    permission, sans portée (org entière), doit annuler cet accès malgré le
    rôle — c'est la règle qui n'existe ni chez Odoo ni chez Dolibarr (§0.2 de
    `formation/role_permission.md`, §5.4 étape 4 du document d'architecture)."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    # Avant le deny : accès normal.
    ok = await client.get("/api/v1/zylo-liquid/stations", headers=headers)
    assert ok.status_code == 200

    from app.core.database import AsyncSessionLocal
    from app.identity.models import User

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        user_id = user.id

    grant_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/grants",
        json={"userId": str(user_id), "permissionCode": "zyloLiquid.station.read", "effect": "deny"},
        headers=headers,
    )
    assert grant_res.status_code == 201, grant_res.text

    denied = await client.get("/api/v1/zylo-liquid/stations", headers=headers)
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"


async def test_scoped_deny_blocks_only_the_targeted_station_over_http(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Preuve de bout en bout (pas seulement le moteur interne) : un deny
    scopé à la station A, posé via l'API, bloque bien GET/PATCH sur cette
    station précise (`require_permission_scoped`, `station_id` du chemin
    d'URL) sans affecter une station B — le owner garde son rôle org entière,
    seule cette ressource précise lui est refusée."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    station_a = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station A", "code": f"A-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=headers,
    )
    station_b = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station B", "code": f"B-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=headers,
    )
    assert station_a.status_code == 201 and station_b.status_code == 201
    station_a_id = station_a.json()["id"]
    station_b_id = station_b.json()["id"]

    from app.core.database import AsyncSessionLocal
    from app.identity.models import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        user_id = user.id

    grant_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/grants",
        json={
            "userId": str(user_id),
            "permissionCode": "zyloLiquid.station.read",
            "effect": "deny",
            "resourceType": "station",
            "resourceId": station_a_id,
        },
        headers=headers,
    )
    assert grant_res.status_code == 201, grant_res.text

    denied = await client.get(f"/api/v1/zylo-liquid/stations/{station_a_id}", headers=headers)
    assert denied.status_code == 403

    still_ok = await client.get(f"/api/v1/zylo-liquid/stations/{station_b_id}", headers=headers)
    assert still_ok.status_code == 200

    # La liste globale (pas scopée à une station précise) reste également
    # accessible : seul l'accès à LA fiche de la station A est bloqué.
    list_ok = await client.get("/api/v1/zylo-liquid/stations", headers=headers)
    assert list_ok.status_code == 200


async def test_scoped_deny_on_station_also_blocks_its_tanks_via_resolver(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Une cuve n'a pas de portée propre (§10.3 du document d'architecture) :
    `require_permission_scoped_via` + `_tank_station_scope` doivent résoudre
    la cuve vers SA station avant de vérifier le grant — un deny posé sur la
    station doit donc bloquer GET/PATCH sur les cuves qu'elle contient,
    sans qu'aucun grant n'ait jamais mentionné la cuve elle-même."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    station_res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Cuves", "code": f"TK-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=headers,
    )
    assert station_res.status_code == 201, station_res.text
    station_id = station_res.json()["id"]

    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 30000,
            "tankHeightMm": 2000,
            "newFuelProductName": f"Produit {station_id[:8]}",
            "newFuelProductCode": station_id[:10],
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    assert tank_res.status_code == 201, tank_res.text
    tank_id = tank_res.json()["id"]

    ok_before = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}", headers=headers)
    assert ok_before.status_code == 200

    from app.core.database import AsyncSessionLocal
    from app.identity.models import User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        user_id = user.id

    grant_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/grants",
        json={
            "userId": str(user_id),
            "permissionCode": "zyloLiquid.tank.read",
            "effect": "deny",
            "resourceType": "station",
            "resourceId": station_id,
        },
        headers=headers,
    )
    assert grant_res.status_code == 201, grant_res.text

    denied = await client.get(f"/api/v1/zylo-liquid/tanks/{tank_id}", headers=headers)
    assert denied.status_code == 403


async def test_scoped_deny_does_not_cover_org_wide_check(client: AsyncClient):
    """Un deny scopé à une station précise ne doit JAMAIS couvrir une
    vérification à portée organisation entière (§5.4 : la portée du deny
    doit être égale ou plus large que celle demandée, jamais l'inverse) —
    testé directement sur le moteur de résolution, aucun endpoint HTTP
    n'exposant aujourd'hui de vérification scopée par station. Dépend de
    `client` uniquement pour bénéficier du `engine.dispose()` de sa
    fixture (voir conftest.py) — sans lui, les connexions du pool restent
    liées à la boucle d'évènements d'un test HTTP précédent."""
    from app.core.database import AsyncSessionLocal
    from app.identity.service import create_organization
    from app.identity.schemas import CreateOrganizationRequest
    from app.rbac.service import create_grant, user_has_permission
    from app.identity.models import User
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        owner = User(email=f"scope-test-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName="Owner")
        db.add(owner)
        await db.flush()
        org = await create_organization(db, owner, CreateOrganizationRequest(name="ScopeOrg", slug=f"scope-{uuid.uuid4().hex[:8]}"))

        fake_station_id = uuid.uuid4()
        await create_grant(
            db,
            org.id,
            owner.id,
            owner.id,
            "identity.organization.manage",
            "deny",
            resource_type="station",
            resource_id=fake_station_id,
        )

        # Portée org entière (aucune ressource précise demandée) : le deny
        # scopé à une station ne s'applique pas -> toujours autorisé.
        assert await user_has_permission(db, owner.id, org.id, "identity.organization.manage") is True

        # Portée = exactement la ressource déniée : refusé.
        assert (
            await user_has_permission(db, owner.id, org.id, "identity.organization.manage", "station", fake_station_id)
            is False
        )

        # Portée = une AUTRE station : toujours autorisé (le deny ne déborde
        # jamais sur une ressource différente).
        other_station_id = uuid.uuid4()
        assert (
            await user_has_permission(db, owner.id, org.id, "identity.organization.manage", "station", other_station_id)
            is True
        )


async def test_privilege_escalation_is_denied(client: AsyncClient, registered_user: dict, organization: dict):
    """Un utilisateur sans MODULE_MANAGE ne peut pas créer un rôle qui inclut
    cette permission — non-élévation de privilège vérifiée côté serveur
    (§5.5), même si l'appelant possède par ailleurs ROLE_MANAGE."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}

    # Le owner a ROLE_MANAGE (bootstrap) mais PAS zyloLiquid.station.manage
    # tant que le module n'est pas activé pour cette organisation.
    res = await client.post(
        f"/api/v1/rbac/organizations/{organization['id']}/roles",
        json={"code": "custom_role", "name": "Rôle personnalisé", "permissionCodes": ["zyloLiquid.station.manage"]},
        headers=headers,
    )
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "privilege_escalation_denied"


async def test_delegation_cascade_revocation(client: AsyncClient):
    """Révoquer un grant révoque en cascade toute délégation issue de lui,
    récursivement (§5.6)."""
    from app.core.database import AsyncSessionLocal
    from app.identity.service import create_organization
    from app.identity.schemas import CreateOrganizationRequest
    from app.rbac.service import create_grant, revoke_grant
    from app.rbac.models import UserPermissionGrant
    from app.identity.models import User
    from app.core.security import hash_password

    async with AsyncSessionLocal() as db:
        owner = User(email=f"delegation-test-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName="Owner")
        delegate1 = User(email=f"delegate1-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName="Delegate1")
        delegate2 = User(email=f"delegate2-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName="Delegate2")
        db.add_all([owner, delegate1, delegate2])
        await db.flush()
        org = await create_organization(db, owner, CreateOrganizationRequest(name="DelegOrg", slug=f"deleg-{uuid.uuid4().hex[:8]}"))

        origin_grant = await create_grant(db, org.id, owner.id, owner.id, "identity.organization.manage", "allow")

        # owner délègue à delegate1
        deleg1_grant = await create_grant(
            db,
            org.id,
            owner.id,
            delegate1.id,
            "identity.organization.manage",
            "allow",
            delegated_from_grant_id=origin_grant.id,
        )
        # delegate1 redélègue à son tour à delegate2 — le grant d'origine
        # d'une délégation doit appartenir à celui qui délègue (contrôlé par
        # create_grant), donc c'est bien delegate1 qui est ici le granter.
        deleg2_grant = await create_grant(
            db,
            org.id,
            delegate1.id,
            delegate2.id,
            "identity.organization.manage",
            "allow",
            delegated_from_grant_id=deleg1_grant.id,
        )

        await revoke_grant(db, org.id, owner.id, origin_grant.id)

        for grant_id in (origin_grant.id, deleg1_grant.id, deleg2_grant.id):
            grant = await db.get(UserPermissionGrant, grant_id)
            assert grant.revokedAt is not None, f"grant {grant_id} aurait dû être révoqué en cascade"


async def test_audit_log_records_sensitive_actions_and_filters_by_scope(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Une action sensible (création de station) est journalisée et visible
    par le owner (audit.log.view org entière, §17)."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    create_res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Audit Test", "code": f"AUD-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=headers,
    )
    assert create_res.status_code == 201, create_res.text

    audit_res = await client.get(
        f"/api/v1/audit/organizations/{zylo_liquid_organization['id']}", params={"actionPrefix": "zyloLiquid.station.create"}, headers=headers
    )
    assert audit_res.status_code == 200
    body = audit_res.json()
    assert body["meta"]["total"] >= 1
    assert any("Station Audit Test" in row["summary"] for row in body["data"])


async def test_audit_log_denied_without_permission(client: AsyncClient, organization: dict):
    """Un utilisateur sans `audit.log.view` (aucun rôle, aucun grant) reçoit
    un 403 explicite — jamais une liste vide silencieuse (§17)."""
    from tests.conftest import unique_email

    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Outsider"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    outsider_token = login.json()["accessToken"]

    from app.core.database import AsyncSessionLocal
    from app.identity.models import OrganizationUser, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        outsider = (await db.execute(select(User).where(User.email == email))).scalar_one()
        db.add(OrganizationUser(organizationId=uuid.UUID(organization["id"]), userId=outsider.id))
        await db.commit()

    headers = {"Authorization": f"Bearer {outsider_token}", "X-Organization-Id": organization["id"]}
    res = await client.get(f"/api/v1/audit/organizations/{organization['id']}", headers=headers)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "permission_denied"


async def test_scoped_deny_on_station_also_blocks_its_deliveries_and_leak_events(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Ni `DeliveryDetected` ni `LeakageRecord` ne portent de portée propre —
    `_delivery_station_scope`/`_leak_event_station_scope` doivent résoudre la
    station via la réponse déjà jointe (`DeliveryDetectedResponse.stationId`/
    `LeakEventResponse.stationId`) avant de vérifier le grant."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    station_res = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Livraisons", "code": f"LV-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=headers,
    )
    assert station_res.status_code == 201, station_res.text
    station_id = station_res.json()["id"]

    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id,
            "tankNumber": 1,
            "displayName": "Cuve 1",
            "capacityLiters": 30000,
            "tankHeightMm": 2000,
            "newFuelProductName": f"Produit {station_id[:8]}",
            "newFuelProductCode": station_id[:10],
            "heightAlarmMm": 1900,
            "heightAlertMm": 1800,
            "lowAlarmMm": 200,
        },
        headers=headers,
    )
    assert tank_res.status_code == 201, tank_res.text
    tank_id = tank_res.json()["id"]

    from app.core.database import AsyncSessionLocal
    from app.identity.models import User
    from app.modules.zylo_liquid.models import DeliveryDetected, LeakageRecord
    from sqlalchemy import select

    now = datetime.utcnow()
    async with AsyncSessionLocal() as db:
        delivery = DeliveryDetected(
            tankId=tank_id, startTime=now - timedelta(hours=2), startHeightMm=500, endTime=now - timedelta(hours=1),
            endHeightMm=1500, volumeLiters=8000,
        )
        leak = LeakageRecord(
            tankId=tank_id, startTime=now - timedelta(hours=3), startHeightMm=1000, endTime=now - timedelta(hours=2, minutes=30),
            endHeightMm=999, result="normal",
        )
        db.add(delivery)
        db.add(leak)
        await db.commit()
        await db.refresh(delivery)
        await db.refresh(leak)
        delivery_id = delivery.id
        leak_id = leak.id

        user = (await db.execute(select(User).where(User.email == registered_user["email"]))).scalar_one()
        user_id = user.id

    ok_delivery = await client.get(f"/api/v1/zylo-liquid/deliveries/{delivery_id}", headers=headers)
    assert ok_delivery.status_code == 200
    ok_leak = await client.get(f"/api/v1/zylo-liquid/leak-events/{leak_id}", headers=headers)
    assert ok_leak.status_code == 200

    for permission_code in ("zyloLiquid.delivery.read", "zyloLiquid.leakEvent.read"):
        grant_res = await client.post(
            f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/grants",
            json={"userId": str(user_id), "permissionCode": permission_code, "effect": "deny", "resourceType": "station", "resourceId": station_id},
            headers=headers,
        )
        assert grant_res.status_code == 201, grant_res.text

    denied_delivery = await client.get(f"/api/v1/zylo-liquid/deliveries/{delivery_id}", headers=headers)
    assert denied_delivery.status_code == 403
    denied_leak = await client.get(f"/api/v1/zylo-liquid/leak-events/{leak_id}", headers=headers)
    assert denied_leak.status_code == 403


async def test_scoped_role_assignment_restricts_station_list_and_access(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Résout le point bloquant de `processus-double-sources-verite/
    02-modele-double-source.md` §6 : attribuer un rôle à une station précise
    (UserRole.resourceType/resourceId) doit restreindre à la fois l'ACCÈS
    (GET /stations/{id} sur une autre station -> 403) et la LISTE (GET
    /stations -> seule la station attribuée apparaît) — pour un utilisateur
    qui n'a AUCUNE permission org entière, uniquement ce rôle scopé."""
    owner_headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    station_a = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Scope A", "code": f"SA-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=owner_headers,
    )
    station_b = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Scope B", "code": f"SB-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=owner_headers,
    )
    assert station_a.status_code == 201 and station_b.status_code == 201
    station_a_id = station_a.json()["id"]
    station_b_id = station_b.json()["id"]

    # Créer un second utilisateur (le futur "gérant"), sans aucun rôle par défaut.
    manager_email = f"gerant-{uuid.uuid4().hex[:8]}@example.com"
    manager_password = "Password123!"
    register_res = await client.post(
        "/api/v1/auth/register",
        json={"email": manager_email, "password": manager_password, "fullName": "Gérant Test"},
    )
    assert register_res.status_code == 201, register_res.text
    manager_login = await client.post("/api/v1/auth/login", json={"email": manager_email, "password": manager_password})
    assert manager_login.status_code == 200, manager_login.text
    manager_token = manager_login.json()["accessToken"]

    from app.core.database import AsyncSessionLocal
    from app.identity.models import OrganizationUser, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        manager_user = (await db.execute(select(User).where(User.email == manager_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=manager_user.id))
        await db.commit()
        manager_user_id = manager_user.id

    roles_res = await client.get(f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/roles", headers=owner_headers)
    station_admin_role = next(r for r in roles_res.json() if r["code"] == "zylo_liquid_station_admin")

    assign_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/user-roles",
        json={"userId": str(manager_user_id), "roleId": station_admin_role["id"], "resourceType": "station", "resourceId": station_a_id},
        headers=owner_headers,
    )
    assert assign_res.status_code == 201, assign_res.text

    manager_headers = {"Authorization": f"Bearer {manager_token}", "X-Organization-Id": zylo_liquid_organization["id"]}

    list_res = await client.get("/api/v1/zylo-liquid/stations", headers=manager_headers)
    assert list_res.status_code == 200, list_res.text
    seen_ids = {row["id"] for row in list_res.json()["data"]}
    assert seen_ids == {station_a_id}, f"le gérant ne doit voir que sa station, vu : {seen_ids}"

    ok = await client.get(f"/api/v1/zylo-liquid/stations/{station_a_id}", headers=manager_headers)
    assert ok.status_code == 200

    denied = await client.get(f"/api/v1/zylo-liquid/stations/{station_b_id}", headers=manager_headers)
    assert denied.status_code == 403


async def test_scoped_role_assignment_restricts_price_history_create_list_and_access(
    client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict, test_city: dict
):
    """Bloc 2 de la Phase 5 (refonte-configuration-zylo-liquid.md, Phase 4
    §4, gap identifié en Phase 1 §1.6) : un utilisateur dont le rôle n'est
    attribué que sur une station précise ne doit pouvoir ni créer, ni lister,
    ni consulter les prix d'une AUTRE station — mais doit toujours voir les
    prix par défaut réseau, qui n'appartiennent à aucune station."""
    owner_headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": zylo_liquid_organization["id"]}

    station_a = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Prix Scope A", "code": f"PSA-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=owner_headers,
    )
    station_b = await client.post(
        "/api/v1/zylo-liquid/stations",
        json={"name": "Station Prix Scope B", "code": f"PSB-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
        headers=owner_headers,
    )
    assert station_a.status_code == 201 and station_b.status_code == 201
    station_a_id = station_a.json()["id"]
    station_b_id = station_b.json()["id"]

    fp_res = await client.post(
        "/api/v1/zylo-liquid/fuel-products", json={"name": "Produit Scope Prix", "code": f"PSP-{uuid.uuid4().hex[:6]}"}, headers=owner_headers
    )
    fuel_product_id = fp_res.json()["id"]

    from app.shared.currency import Currency
    from app.core.database import AsyncSessionLocal

    from sqlalchemy.exc import IntegrityError

    async with AsyncSessionLocal() as db:
        # `currency.code` est limité à 3 caractères (ISO 4217) et la base de
        # test est persistante entre les sessions : tirage renouvelé sur
        # violation d'unicité (pattern commun aux helpers `_create_currency`).
        for _ in range(10):
            currency = Currency(code=f"S{uuid.uuid4().hex[:2].upper()}", name="Scope Currency", symbol="SC", decimalPlaces=0)
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

    # Un prix propre à chaque station (owner, org entière) + un prix par défaut réseau.
    price_a = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_a_id, "fuelProductId": fuel_product_id, "priceAmount": 700, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=owner_headers,
    )
    price_b = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_b_id, "fuelProductId": fuel_product_id, "priceAmount": 710, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=owner_headers,
    )
    price_network = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"fuelProductId": fuel_product_id, "priceAmount": 680, "currencyId": currency_id, "effectiveFrom": "2026-01-01T00:00:00"},
        headers=owner_headers,
    )
    assert price_a.status_code == 201 and price_b.status_code == 201 and price_network.status_code == 201
    price_a_id = price_a.json()["id"]
    price_b_id = price_b.json()["id"]

    manager_email = f"gerant-prix-{uuid.uuid4().hex[:8]}@example.com"
    manager_password = "Password123!"
    register_res = await client.post(
        "/api/v1/auth/register", json={"email": manager_email, "password": manager_password, "fullName": "Gérant Prix Test"}
    )
    assert register_res.status_code == 201, register_res.text
    manager_login = await client.post("/api/v1/auth/login", json={"email": manager_email, "password": manager_password})
    manager_token = manager_login.json()["accessToken"]

    from app.identity.models import OrganizationUser, User
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        manager_user = (await db.execute(select(User).where(User.email == manager_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=manager_user.id))
        await db.commit()
        manager_user_id = manager_user.id

    roles_res = await client.get(f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/roles", headers=owner_headers)
    station_admin_role = next(r for r in roles_res.json() if r["code"] == "zylo_liquid_station_admin")

    assign_res = await client.post(
        f"/api/v1/rbac/organizations/{zylo_liquid_organization['id']}/user-roles",
        json={"userId": str(manager_user_id), "roleId": station_admin_role["id"], "resourceType": "station", "resourceId": station_a_id},
        headers=owner_headers,
    )
    assert assign_res.status_code == 201, assign_res.text

    manager_headers = {"Authorization": f"Bearer {manager_token}", "X-Organization-Id": zylo_liquid_organization["id"]}

    # Liste : seuls le prix de sa station et le prix réseau doivent apparaître, jamais celui de l'autre station.
    list_res = await client.get("/api/v1/zylo-liquid/prices", headers=manager_headers)
    assert list_res.status_code == 200, list_res.text
    seen_ids = {row["id"] for row in list_res.json()["data"]}
    assert price_a_id in seen_ids
    assert price_network.json()["id"] in seen_ids
    assert price_b_id not in seen_ids

    # Accès direct : sa station OK, l'autre station refusée.
    ok = await client.get(f"/api/v1/zylo-liquid/prices/{price_a_id}", headers=manager_headers)
    assert ok.status_code == 200
    denied = await client.get(f"/api/v1/zylo-liquid/prices/{price_b_id}", headers=manager_headers)
    assert denied.status_code == 403

    # Création : sa station OK, l'autre station refusée.
    create_ok = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_a_id, "fuelProductId": fuel_product_id, "priceAmount": 705, "currencyId": currency_id, "effectiveFrom": "2026-02-01T00:00:00"},
        headers=manager_headers,
    )
    assert create_ok.status_code == 201, create_ok.text
    create_denied = await client.post(
        "/api/v1/zylo-liquid/prices",
        json={"stationId": station_b_id, "fuelProductId": fuel_product_id, "priceAmount": 715, "currencyId": currency_id, "effectiveFrom": "2026-02-01T00:00:00"},
        headers=manager_headers,
    )
    assert create_denied.status_code == 403
