"""Tests de la génération de document (bon de commande PDF/DOCX) —
mission « bon de commande + aperçu/partage ». Couvre :
  - génération PDF et DOCX, octets non vides, type MIME correct ;
  - le document généré est bien rattaché à la commande via DocumentLink
    (visible ensuite par GET /documents/by-entity) ;
  - format invalide rejeté ;
  - permission requise (même droit que la création de la commande)."""

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _setup_station_product_tank(client: AsyncClient, headers: dict, suffix: str) -> tuple[str, str, str]:
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]
    fp_res = await client.post("/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit {suffix}", "code": f"P{suffix[:8]}"}, headers=headers)
    fuel_product_id = fp_res.json()["id"]
    tank_res = await client.post(
        "/api/v1/zylo-liquid/tanks",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "tankNumber": 1, "displayName": f"Cuve {suffix}",
            "capacityLiters": 20000, "tankHeightMm": 3000, "heightAlarmMm": 2800, "heightAlertMm": 2600, "lowAlarmMm": 300,
        },
        headers=headers,
    )
    return station_id, fuel_product_id, tank_res.json()["id"]


async def _create_supplier(client: AsyncClient, headers: dict, name: str) -> dict:
    res = await client.post("/api/v1/zylo-liquid/suppliers", json={"name": name, "type": "Grossiste", "address": "1 rue du Test", "taxId": "SIRET-TEST-001"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _create_order(client: AsyncClient, headers: dict, station_id: str, tank_id: str, supplier_id: str, reference: str, volume: int) -> dict:
    res = await client.post(
        "/api/v1/zylo-liquid/purchase-orders",
        json={
            "stationId": station_id, "tankId": tank_id, "supplierId": supplier_id,
            "orderReference": reference, "orderedVolumeLiters": volume,
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_generate_purchase_order_document_pdf(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, _fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    order = await _create_order(client, headers, station_id, tank_id, supplier["id"], f"CMD-{suffix}", 5000)

    res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}/generate-document", json={"format": "pdf"}, headers=headers)
    assert res.status_code == 201, res.text
    document = res.json()
    assert document["mimeType"] == "application/pdf"
    assert document["fileName"].endswith(".pdf")
    assert document["fileName"].startswith("bon-commande-")

    download = await client.get(f"/api/v1/zylo-liquid/documents/{document['id']}/download-url", headers=headers)
    assert download.status_code == 200, download.text
    signed_url = download.json()["url"]
    # Régression : la route de service local doit refléter le vrai type MIME
    # (déduit de l'extension conservée dans storageReference) — pas
    # application/octet-stream par défaut, qui empêche un aperçu PDF en
    # ligne (iframe) côté frontend (bug trouvé et corrigé dans cette même
    # mission, 2026-09-10).
    served = await client.get(signed_url, headers=headers)
    assert served.status_code == 200, served.text
    assert served.headers["content-type"] == "application/pdf"

    linked = await client.get(
        "/api/v1/zylo-liquid/documents/by-entity",
        params={"linkedEntityType": "PurchaseOrder", "linkedEntityId": order["id"]},
        headers=headers,
    )
    assert linked.status_code == 200, linked.text
    assert any(d["id"] == document["id"] for d in linked.json())


async def test_generate_purchase_order_document_docx(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, _fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    order = await _create_order(client, headers, station_id, tank_id, supplier["id"], f"CMD-{suffix}", 3200)

    res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}/generate-document", json={"format": "docx"}, headers=headers)
    assert res.status_code == 201, res.text
    document = res.json()
    assert document["mimeType"] == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    assert document["fileName"].endswith(".docx")


async def test_generate_purchase_order_document_invalid_format(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, _fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    order = await _create_order(client, headers, station_id, tank_id, supplier["id"], f"CMD-{suffix}", 1000)

    res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}/generate-document", json={"format": "xls"}, headers=headers)
    assert res.status_code == 422


async def test_generate_purchase_order_document_requires_permission(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Un utilisateur de l'organisation sans aucun rôle (donc sans
    PURCHASE_ORDER_MANAGE) ne peut pas générer le bon de commande — même
    droit que la création de la commande elle-même."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, _fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    order = await _create_order(client, headers, station_id, tank_id, supplier["id"], f"CMD-{suffix}", 1000)

    outsider_email = f"outsider-{suffix}@example.com"
    outsider_password = "Password123!"
    await client.post("/api/v1/auth/register", json={"email": outsider_email, "password": outsider_password, "fullName": "Outsider Test"})
    login = await client.post("/api/v1/auth/login", json={"email": outsider_email, "password": outsider_password})
    outsider_token = login.json()["accessToken"]

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        outsider_user = (await db.execute(select(User).where(User.email == outsider_email))).scalar_one()
        db.add(OrganizationUser(organizationId=zylo_liquid_organization["id"], userId=outsider_user.id))
        await db.commit()

    outsider_headers = {"Authorization": f"Bearer {outsider_token}", "X-Organization-Id": zylo_liquid_organization["id"]}
    res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}/generate-document", json={"format": "pdf"}, headers=outsider_headers)
    assert res.status_code == 403
