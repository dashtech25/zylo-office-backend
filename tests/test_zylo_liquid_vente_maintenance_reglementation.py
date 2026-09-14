"""Tests des Blocs 4 (corrigé)/5/6/7 de la mission
« vente-maintenant-reglementation » (08-plan-implementation-par-blocs.md) :
ventes de produits boutique (paniers, entité séparée de `Sale`), catalogue de
produits vendables, équipements/interventions de maintenance, documents
réglementaires."""

import uuid
from datetime import date, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.shared.currency import Currency


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_currency(prefix: str) -> str:
    # `currency.code` est limité à 3 caractères (norme ISO 4217) et la base de
    # test est persistante entre les sessions : un code court déterministe
    # finit par entrer en collision. Code aléatoire + nouvelle tentative sur
    # violation d'unicité → tests idempotents (le préfixe n'a aucune valeur
    # sémantique pour les assertions).
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


async def _create_station(client: AsyncClient, headers: dict, suffix: str) -> str:
    res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ----------------------------------------------------------------
# Bloc 5 — Catalogue de produits vendables
# ----------------------------------------------------------------


async def test_create_sellable_product_and_list(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency("SP")
    res = await client.post(
        "/api/v1/zylo-liquid/sellable-products",
        json={"name": "Huile moteur 5W40", "sku": "HM-5W40", "barcodeValue": f"BC{uuid.uuid4().hex[:10]}", "category": "lubrifiant", "unitPriceAmount": 12500, "currencyId": currency_id},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["active"] is True

    list_res = await client.get("/api/v1/zylo-liquid/sellable-products", headers=headers)
    assert list_res.status_code == 200
    assert list_res.json()["meta"]["total"] >= 1


async def test_sellable_product_duplicate_barcode_rejected(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency("DB")
    barcode = f"BC{uuid.uuid4().hex[:10]}"
    first = await client.post(
        "/api/v1/zylo-liquid/sellable-products",
        json={"name": "Produit A", "barcodeValue": barcode, "unitPriceAmount": 1000, "currencyId": currency_id},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = await client.post(
        "/api/v1/zylo-liquid/sellable-products",
        json={"name": "Produit B", "barcodeValue": barcode, "unitPriceAmount": 2000, "currencyId": currency_id},
        headers=headers,
    )
    assert second.status_code == 409, second.text


# ----------------------------------------------------------------
# Bloc 4 corrigé — Ventes boutique (paniers), séparées de Sale
# ----------------------------------------------------------------


async def test_product_sale_transaction_multi_line_computes_total(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("PS")

    product1 = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Huile", "unitPriceAmount": 10000, "currencyId": currency_id, "stockQuantity": 10}, headers=headers)).json()
    product2 = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Filtre", "unitPriceAmount": 3000, "currencyId": currency_id, "stockQuantity": 10}, headers=headers)).json()

    res = await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={
            "stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "cash",
            "lines": [
                {"sellableProductId": product1["id"], "quantity": 2, "unitPriceAmount": 10000},
                {"sellableProductId": product2["id"], "quantity": 3, "unitPriceAmount": 3000},
            ],
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["totalAmount"] == 2 * 10000 + 3 * 3000
    assert len(body["lines"]) == 2
    assert body["status"] == "completed"


async def test_product_sale_credit_creates_receivable_via_new_column(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Confirme la décision de la Phase 3/9 du plan de mission : une vente
    boutique à crédit crée une `Receivable` via `productSaleTransactionId`,
    sans jamais toucher à `Sale` ni `saleId`."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("PC")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Batterie", "unitPriceAmount": 45000, "currencyId": currency_id, "stockQuantity": 5}, headers=headers)).json()
    account = (await client.post("/api/v1/zylo-liquid/commercial-accounts", json={"name": "Client Boutique", "currencyId": currency_id, "creditLimit": 500000}, headers=headers)).json()

    res = await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={
            "stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "credit",
            "commercialAccountId": account["id"], "lines": [{"sellableProductId": product["id"], "quantity": 1, "unitPriceAmount": 45000}],
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text

    receivables = await client.get(f"/api/v1/zylo-liquid/receivables?commercialAccountId={account['id']}", headers=headers)
    assert receivables.json()["meta"]["total"] == 1
    assert receivables.json()["data"][0]["amount"] == 45000


async def test_product_sale_cancel_is_status_only(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("PX")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Ampoule", "unitPriceAmount": 1500, "currencyId": currency_id, "stockQuantity": 3}, headers=headers)).json()

    sale = (await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "cash", "lines": [{"sellableProductId": product["id"], "quantity": 1, "unitPriceAmount": 1500}]},
        headers=headers,
    )).json()

    cancel_res = await client.post(f"/api/v1/zylo-liquid/product-sales/{sale['id']}/cancel", headers=headers)
    assert cancel_res.status_code == 200, cancel_res.text
    assert cancel_res.json()["status"] == "cancelled"
    assert cancel_res.json()["cancelledByUserId"] is not None

    already = await client.post(f"/api/v1/zylo-liquid/product-sales/{sale['id']}/cancel", headers=headers)
    assert already.status_code == 409


# ----------------------------------------------------------------
# Bloc 4 corrigé — Stock simple (Phase 4 mission Boutique)
# ----------------------------------------------------------------


async def test_product_sale_decrements_stock(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("SD")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Savon", "unitPriceAmount": 500, "currencyId": currency_id, "stockQuantity": 10}, headers=headers)).json()

    res = await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "cash", "lines": [{"sellableProductId": product["id"], "quantity": 4, "unitPriceAmount": 500}]},
        headers=headers,
    )
    assert res.status_code == 201, res.text

    updated = (await client.get("/api/v1/zylo-liquid/sellable-products", headers=headers)).json()
    row = next(p for p in updated["data"] if p["id"] == product["id"])
    assert row["stockQuantity"] == 6


async def test_product_sale_rejected_when_stock_insufficient(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("SI")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Chargeur", "unitPriceAmount": 2000, "currencyId": currency_id, "stockQuantity": 2}, headers=headers)).json()

    res = await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "cash", "lines": [{"sellableProductId": product["id"], "quantity": 3, "unitPriceAmount": 2000}]},
        headers=headers,
    )
    assert res.status_code == 409, res.text
    assert res.json()["error"]["code"] == "insufficient_stock"

    # Vente refusée -> aucune conséquence, ni sur le stock ni sur une vente fantôme.
    unchanged = (await client.get("/api/v1/zylo-liquid/sellable-products", headers=headers)).json()
    row = next(p for p in unchanged["data"] if p["id"] == product["id"])
    assert row["stockQuantity"] == 2
    sales = (await client.get(f"/api/v1/zylo-liquid/product-sales?stationId={station_id}", headers=headers)).json()
    assert sales["meta"]["total"] == 0


async def test_product_sale_cancel_restocks(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    currency_id = await _create_currency("RS")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Clé USB", "unitPriceAmount": 3000, "currencyId": currency_id, "stockQuantity": 5}, headers=headers)).json()

    sale = (await client.post(
        "/api/v1/zylo-liquid/product-sales",
        json={"stationId": station_id, "eventAt": "2026-02-01T10:00:00", "currencyId": currency_id, "paymentMethod": "cash", "lines": [{"sellableProductId": product["id"], "quantity": 2, "unitPriceAmount": 3000}]},
        headers=headers,
    )).json()

    after_sale = (await client.get("/api/v1/zylo-liquid/sellable-products", headers=headers)).json()
    assert next(p for p in after_sale["data"] if p["id"] == product["id"])["stockQuantity"] == 3

    cancel_res = await client.post(f"/api/v1/zylo-liquid/product-sales/{sale['id']}/cancel", headers=headers)
    assert cancel_res.status_code == 200, cancel_res.text

    after_cancel = (await client.get("/api/v1/zylo-liquid/sellable-products", headers=headers)).json()
    assert next(p for p in after_cancel["data"] if p["id"] == product["id"])["stockQuantity"] == 5


async def test_sellable_product_manual_stock_adjustment(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    currency_id = await _create_currency("MA")
    product = (await client.post("/api/v1/zylo-liquid/sellable-products", json={"name": "Bidon 5L", "unitPriceAmount": 8000, "currencyId": currency_id, "stockQuantity": 10, "lowStockThreshold": 3}, headers=headers)).json()
    assert product["stockQuantity"] == 10
    assert product["lowStockThreshold"] == 3

    patched = await client.patch(f"/api/v1/zylo-liquid/sellable-products/{product['id']}", json={"stockQuantity": 25}, headers=headers)
    assert patched.status_code == 200, patched.text
    assert patched.json()["stockQuantity"] == 25


# ----------------------------------------------------------------
# Bloc 6 — Maintenance
# ----------------------------------------------------------------


async def test_intervention_full_lifecycle_updates_equipment_last_maintenance(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    equipment = (await client.post("/api/v1/zylo-liquid/equipment", json={"stationId": station_id, "type": "pompe", "name": "Pompe 1"}, headers=headers)).json()
    assert equipment["status"] == "in_service"

    technician = (await client.post("/api/v1/zylo-liquid/technicians", json={"name": "Jean Mbarga", "company": "TechServ"}, headers=headers)).json()

    intervention = (await client.post(
        "/api/v1/zylo-liquid/interventions",
        json={"equipmentId": equipment["id"], "stationId": station_id, "priority": "high", "type": "corrective", "description": "Panne moteur pompe."},
        headers=headers,
    )).json()
    assert intervention["status"] == "planned"

    assign_res = await client.post(f"/api/v1/zylo-liquid/interventions/{intervention['id']}/assign", json={"technicianId": technician["id"]}, headers=headers)
    assert assign_res.status_code == 200
    assert assign_res.json()["status"] == "in_progress"
    assert assign_res.json()["technicianId"] == technician["id"]

    close_res = await client.post(
        f"/api/v1/zylo-liquid/interventions/{intervention['id']}/close",
        json={"diagnosis": "Joint défectueux.", "actionTaken": "Remplacement du joint.", "cost": 15000},
        headers=headers,
    )
    assert close_res.status_code == 200
    assert close_res.json()["status"] == "closed"
    assert close_res.json()["closedAt"] is not None

    already_closed = await client.post(f"/api/v1/zylo-liquid/interventions/{intervention['id']}/close", json={}, headers=headers)
    assert already_closed.status_code == 409

    equipment_list = await client.get(f"/api/v1/zylo-liquid/equipment?stationId={station_id}", headers=headers)
    updated_equipment = next(e for e in equipment_list.json()["data"] if e["id"] == equipment["id"])
    assert updated_equipment["lastMaintenanceAt"] == date.today().isoformat()


async def test_intervention_can_reference_existing_alert(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Confirme la décision de la Phase 3 §6 du plan de mission : une
    intervention réutilise le système d'alertes déjà existant, jamais un
    second mécanisme."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)
    equipment = (await client.post("/api/v1/zylo-liquid/equipment", json={"stationId": station_id, "type": "sonde", "name": "Sonde 1"}, headers=headers)).json()

    intervention = (await client.post(
        "/api/v1/zylo-liquid/interventions",
        json={"equipmentId": equipment["id"], "stationId": station_id, "priority": "critical", "type": "corrective", "description": "Défaut de communication.", "linkedAlertId": None},
        headers=headers,
    )).json()
    assert intervention["linkedAlertId"] is None  # nullable, confirmé fonctionnel sans alerte liée


# ----------------------------------------------------------------
# Bloc 7 — Réglementation
# ----------------------------------------------------------------


async def test_regulatory_document_status_computed_from_expiry(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    expired = (await client.post(
        "/api/v1/zylo-liquid/regulatory-documents",
        json={"stationId": station_id, "documentType": "autorisation_exploitation", "expiresAt": (date.today() - timedelta(days=5)).isoformat(), "certaintyLevel": "medium"},
        headers=headers,
    )).json()
    assert expired["computedStatus"] == "expired"

    renew_soon = (await client.post(
        "/api/v1/zylo-liquid/regulatory-documents",
        json={"stationId": station_id, "documentType": "controle_metrologique", "expiresAt": (date.today() + timedelta(days=20)).isoformat(), "certaintyLevel": "low"},
        headers=headers,
    )).json()
    assert renew_soon["computedStatus"] == "renew_soon"

    valid = (await client.post(
        "/api/v1/zylo-liquid/regulatory-documents",
        json={"stationId": station_id, "documentType": "controle_incendie", "expiresAt": (date.today() + timedelta(days=200)).isoformat(), "certaintyLevel": "high"},
        headers=headers,
    )).json()
    assert valid["computedStatus"] == "valid"

    unknown = (await client.post(
        "/api/v1/zylo-liquid/regulatory-documents",
        json={"stationId": station_id, "documentType": "licence_cgi", "certaintyLevel": "low"},
        headers=headers,
    )).json()
    assert unknown["computedStatus"] == "unknown"

    needs_action = await client.get(f"/api/v1/zylo-liquid/regulatory-documents?stationId={station_id}&needsActionOnly=true", headers=headers)
    returned_types = {d["documentType"] for d in needs_action.json()["data"]}
    assert returned_types == {"autorisation_exploitation", "controle_metrologique"}


async def test_regulatory_document_renewal_chains_supersession(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Renouvellement = nouveau document chaîné (Phase 5 §3 du plan de
    mission : jamais réécrire, toujours ajouter)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    old_doc = (await client.post(
        "/api/v1/zylo-liquid/regulatory-documents",
        json={"stationId": station_id, "documentType": "autorisation_exploitation", "expiresAt": (date.today() - timedelta(days=1)).isoformat()},
        headers=headers,
    )).json()

    new_doc = (await client.post(
        f"/api/v1/zylo-liquid/regulatory-documents/{old_doc['id']}/renew",
        json={"stationId": station_id, "documentType": "autorisation_exploitation", "expiresAt": (date.today() + timedelta(days=365)).isoformat()},
        headers=headers,
    )).json()
    assert new_doc["computedStatus"] == "valid"

    list_res = await client.get(f"/api/v1/zylo-liquid/regulatory-documents?stationId={station_id}", headers=headers)
    refreshed_old = next(d for d in list_res.json()["data"] if d["id"] == old_doc["id"])
    assert refreshed_old["supersededByDocumentId"] == new_doc["id"]


async def test_regulatory_declaration_create_and_list(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id = await _create_station(client, headers, suffix)

    res = await client.post(
        "/api/v1/zylo-liquid/regulatory-declarations",
        json={"stationId": station_id, "type": "declaration_incident", "reserve": "Détail à confirmer auprès de l'autorité compétente."},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "to_produce"

    list_res = await client.get(f"/api/v1/zylo-liquid/regulatory-declarations?stationId={station_id}", headers=headers)
    assert list_res.json()["meta"]["total"] == 1


# ----------------------------------------------------------------
# Bloc 1 — Documents : sensibilité et suppression logique
# ----------------------------------------------------------------


async def test_document_sensitivity_level_and_logical_deletion(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    doc = (await client.post(
        "/api/v1/zylo-liquid/documents",
        json={"storageReference": f"ref-{uuid.uuid4().hex}", "fileName": "confidentiel.pdf", "sensitivityLevel": "restreint"},
        headers=headers,
    )).json()
    assert doc["sensitivityLevel"] == "restreint"
    assert doc["deletedAt"] is None

    delete_res = await client.delete(f"/api/v1/zylo-liquid/documents/{doc['id']}", headers=headers)
    assert delete_res.status_code == 200
    assert delete_res.json()["deletedAt"] is not None
