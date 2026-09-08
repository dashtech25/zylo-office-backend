"""Tests du Centre administratif et opérationnel de la station : domaines
Sécurité (SecurityEquipment), Fournisseurs par station (StationSupplier) et
Finances (sous-ressource dédiée sur Station, gardée par STATION_FINANCIAL_READ).
Couvre :
  - CRUD SecurityEquipment scopé station ;
  - CRUD StationSupplier (lien vers le référentiel réseau existant), avec
    ré-activation d'un lien déjà retiré plutôt qu'un doublon ;
  - la sous-ressource /stations/{id}/financial : `bankAccountInfo` et les
    autres champs fiscaux ne sont JAMAIS exposés par le StationResponse
    standard, uniquement via cette sous-ressource, gardée par
    STATION_FINANCIAL_READ/MANAGE (absente de tout rôle par défaut sauf
    owner) ;
  - le filtre `scopeResourceType`/`scopeResourceId` de l'historique d'audit."""

import uuid

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_station(client: AsyncClient, headers: dict, suffix: str) -> str:
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def test_security_equipment_crud(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    created = await client.post(
        "/api/v1/zylo-liquid/security-equipment",
        json={"stationId": station_id, "category": "extincteur", "label": "Extincteur boutique"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["conformityStatus"] == "a_controler"  # défaut, jamais inventé "conforme"

    updated = await client.patch(
        f"/api/v1/zylo-liquid/security-equipment/{body['id']}",
        json={"conformityStatus": "conforme", "lastControlAt": "2026-01-15"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["conformityStatus"] == "conforme"

    invalid = await client.post(
        "/api/v1/zylo-liquid/security-equipment",
        json={"stationId": station_id, "category": "inconnue", "label": "X"},
        headers=headers,
    )
    assert invalid.status_code in (400, 422)

    listed = await client.get(f"/api/v1/zylo-liquid/security-equipment?stationId={station_id}", headers=headers)
    assert listed.status_code == 200
    assert any(r["id"] == body["id"] for r in listed.json()["data"])


async def test_station_supplier_link_and_reactivate(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    supplier_res = await client.post("/api/v1/zylo-liquid/suppliers", json={"name": f"Fournisseur {suffix}"}, headers=headers)
    assert supplier_res.status_code == 201, supplier_res.text
    supplier_id = supplier_res.json()["id"]

    link = await client.post(
        "/api/v1/zylo-liquid/station-suppliers", json={"stationId": station_id, "supplierId": supplier_id}, headers=headers
    )
    assert link.status_code == 201, link.text
    link_id = link.json()["id"]
    assert link.json()["active"] is True

    duplicate = await client.post(
        "/api/v1/zylo-liquid/station-suppliers", json={"stationId": station_id, "supplierId": supplier_id}, headers=headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "station_supplier_already_linked"

    deactivate = await client.patch(f"/api/v1/zylo-liquid/station-suppliers/{link_id}", json={"active": False}, headers=headers)
    assert deactivate.status_code == 200
    assert deactivate.json()["active"] is False

    # Retirer puis réassocier le même fournisseur réactive le lien existant
    # plutôt que d'en créer un doublon (unique constraint stationId+supplierId).
    reactivate = await client.post(
        "/api/v1/zylo-liquid/station-suppliers", json={"stationId": station_id, "supplierId": supplier_id}, headers=headers
    )
    assert reactivate.status_code == 201, reactivate.text
    assert reactivate.json()["id"] == link_id
    assert reactivate.json()["active"] is True

    listed = await client.get(f"/api/v1/zylo-liquid/station-suppliers?stationId={station_id}", headers=headers)
    assert listed.status_code == 200
    assert any(r["id"] == link_id for r in listed.json()["data"])


async def test_station_financial_never_leaks_via_standard_response(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    update = await client.patch(
        f"/api/v1/zylo-liquid/stations/{station_id}/financial",
        json={"taxId": "NIU-12345", "bankAccountInfo": "IBAN CM00 0000 0000"},
        headers=headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["taxId"] == "NIU-12345"
    assert update.json()["bankAccountInfo"] == "IBAN CM00 0000 0000"

    # Le StationResponse standard (GET /stations/{id}) n'expose JAMAIS ces
    # champs, quel que soit l'appelant — seule la sous-ressource dédiée le fait.
    standard = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}", headers=headers)
    assert standard.status_code == 200
    assert "bankAccountInfo" not in standard.json()
    assert "taxId" not in standard.json()

    financial = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}/financial", headers=headers)
    assert financial.status_code == 200
    assert financial.json()["bankAccountInfo"] == "IBAN CM00 0000 0000"


async def test_station_financial_denied_without_permission(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Un rôle scopé station sans STATION_FINANCIAL_READ (aucun rôle par
    défaut ne l'accorde, sauf owner) reçoit un 403 explicite — jamais une
    liste vide silencieuse ni une valeur masquée."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    attendant_email = f"pompiste-{suffix}@example.com"
    attendant_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": attendant_email, "password": attendant_password, "fullName": "Pompiste Test"})
    login = await client.post("/api/v1/auth/login", json={"email": attendant_email, "password": attendant_password})
    attendant_token = login.json()["accessToken"]
    attendant_headers = {"Authorization": f"Bearer {attendant_token}", "X-Organization-Id": zylo_liquid_organization["id"]}

    from app.core.database import AsyncSessionLocal
    from app.rbac.models import Role, UserRole
    from sqlalchemy import select
    import uuid as uuid_module

    async with AsyncSessionLocal() as db:
        role = (
            await db.execute(select(Role).where(Role.organizationId == uuid_module.UUID(zylo_liquid_organization["id"]), Role.code == "zylo_liquid_pump_attendant"))
        ).scalar_one()
        me = await client.get("/api/v1/auth/me", headers=attendant_headers)
        user_id = me.json()["id"]
        db.add(UserRole(userId=uuid_module.UUID(user_id), organizationId=uuid_module.UUID(zylo_liquid_organization["id"]), roleId=role.id, resourceType="station", resourceId=uuid_module.UUID(station_id)))
        await db.commit()

    denied = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}/financial", headers=attendant_headers)
    assert denied.status_code == 403


async def test_audit_history_scoped_to_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_a_id = await _create_station(client, headers, suffix)
    station_b_id = await _create_station(client, headers, f"{suffix}b")

    # Une modification sur chaque station génère un évènement d'audit scopé.
    await client.patch(f"/api/v1/zylo-liquid/stations/{station_a_id}", json={"notes": "A"}, headers=headers)
    await client.patch(f"/api/v1/zylo-liquid/stations/{station_b_id}", json={"notes": "B"}, headers=headers)

    filtered = await client.get(
        f"/api/v1/audit/organizations/{zylo_liquid_organization['id']}?scopeResourceType=station&scopeResourceId={station_a_id}",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    rows = filtered.json()["data"]
    assert len(rows) > 0
    assert all(r["scopeResourceId"] == station_a_id for r in rows)
    assert not any(r["scopeResourceId"] == station_b_id for r in rows)
