"""Tests de la Couche Approvisionnement (fusion prototype #/livraisons avec
la couche réelle — décision commanditaire « créer toutes les tables
nécessaires, même fournisseur ») : référentiels réseau (fournisseur,
transporteur, camion) et commande d'approvisionnement scopée station.
Couvre les règles de cohérence posées dans le service :
  - plaque de camion unique par organisation ;
  - commande seulement contre un fournisseur actif ;
  - une déclaration de livraison peut être rattachée à une commande (mêmes
    station/produit — le produit est celui de la cuve visée, jamais stocké
    sur la commande) avec instantané documentaire `supplierName` figé au
    nom du fournisseur référentiel ;
  - transition 'open' → 'received' uniquement au VERROUILLAGE de la
    déclaration qui complète le volume commandé (jamais à la création, une
    réception partielle possible) ;
  - une déclaration CORRECTIVE peut reproduire le rattachement d'une
    livraison même quand la commande est déjà 'received' (elle remplace la
    ligne corrigée, elle n'ajoute aucun volume)."""

import uuid

from httpx import AsyncClient


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
    res = await client.post("/api/v1/zylo-liquid/suppliers", json={"name": name, "type": "Grossiste"}, headers=headers)
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


async def test_create_update_list_supplier(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    created = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    assert created["active"] is True
    assert created["type"] == "Grossiste"

    patch_res = await client.patch(
        f"/api/v1/zylo-liquid/suppliers/{created['id']}", json={"name": f"Fournisseur {suffix} (corrigé)", "active": False}, headers=headers
    )
    assert patch_res.status_code == 200, patch_res.text
    assert patch_res.json()["name"].endswith("(corrigé)")
    assert patch_res.json()["active"] is False

    list_res = await client.get("/api/v1/zylo-liquid/suppliers", headers=headers)
    assert list_res.status_code == 200
    assert any(r["id"] == created["id"] for r in list_res.json()["data"])


async def test_truck_plate_unique_per_organization(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    carrier_res = await client.post("/api/v1/zylo-liquid/carriers", json={"name": "Transporteur Test"}, headers=headers)
    assert carrier_res.status_code == 201, carrier_res.text
    carrier_id = carrier_res.json()["id"]

    plate = f"AB-{uuid.uuid4().hex[:6].upper()}"
    res = await client.post(
        "/api/v1/zylo-liquid/trucks",
        json={"carrierId": carrier_id, "plateNumber": plate, "capacityLiters": 30000, "compartmentsCount": 3},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    truck_id = res.json()["id"]

    dup = await client.post("/api/v1/zylo-liquid/trucks", json={"plateNumber": plate}, headers=headers)
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "truck_plate_already_used"

    filtered = await client.get(f"/api/v1/zylo-liquid/trucks?carrierId={carrier_id}", headers=headers)
    assert any(r["id"] == truck_id for r in filtered.json()["data"])
    unlinked = await client.get("/api/v1/zylo-liquid/trucks?carrierId={}".format(uuid.uuid4()), headers=headers)
    assert unlinked.json()["meta"]["total"] == 0


async def test_purchase_order_requires_active_supplier(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur inactif {suffix}")

    patch_res = await client.patch(f"/api/v1/zylo-liquid/suppliers/{supplier['id']}", json={"active": False}, headers=headers)
    assert patch_res.status_code == 200

    res = await client.post(
        "/api/v1/zylo-liquid/purchase-orders",
        json={
            "stationId": station_id, "tankId": tank_id, "supplierId": supplier["id"],
            "orderReference": "PO-INACTIF", "orderedVolumeLiters": 5000,
        },
        headers=headers,
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "supplier_inactive"


async def test_delivery_link_coherence_controls(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier_a = await _create_supplier(client, headers, f"Fournisseur A {suffix}")
    supplier_b = await _create_supplier(client, headers, f"Fournisseur B {suffix}")

    # Second produit carburant : la cuve ne porte que le premier.
    fp2_res = await client.post(
        "/api/v1/zylo-liquid/fuel-products", json={"name": f"Produit autre {suffix}", "code": f"Q{suffix[:8]}"}, headers=headers
    )
    other_product_id = fp2_res.json()["id"]

    order = await _create_order(client, headers, station_id, tank_id, supplier_a["id"], "PO-COHERENCE", 5000)

    # Produit différent de celui de la cuve visée par la commande.
    wrong_product = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": other_product_id, "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 1000, "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    assert wrong_product.status_code == 422
    assert wrong_product.json()["error"]["code"] == "purchase_order_product_mismatch"

    # Fournisseur différent de celui de la commande.
    wrong_supplier = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 1000, "supplierId": supplier_b["id"], "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    assert wrong_supplier.status_code == 422
    assert wrong_supplier.json()["error"]["code"] == "purchase_order_supplier_mismatch"

    # Camion hors référentiel (autre organisation / inexistant).
    unknown_truck = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 1000, "truckId": str(uuid.uuid4()),
        },
        headers=headers,
    )
    assert unknown_truck.status_code == 404
    assert unknown_truck.json()["error"]["code"] == "truck_not_found"

    # Rattachement valide : l'instantané documentaire est figé au nom du
    # fournisseur du référentiel quand aucun libellé libre n'est fourni.
    ok = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 1000, "supplierId": supplier_a["id"], "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["supplierName"] == supplier_a["name"]
    assert ok.json()["supplierId"] == supplier_a["id"]
    assert ok.json()["purchaseOrderId"] == order["id"]


async def test_order_received_only_on_completing_lock(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Réceptions partielles possibles : la commande ne passe à 'received'
    qu'au verrouillage de la déclaration qui complète le volume commandé —
    jamais à la création d'une déclaration."""
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    station_id, fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    supplier = await _create_supplier(client, headers, f"Fournisseur {suffix}")
    order = await _create_order(client, headers, station_id, tank_id, supplier["id"], "PO-PARTIEL", 10000)

    first_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T08:00:00",
            "declaredVolumeLiters": 3000, "supplierId": supplier["id"], "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    first_id = first_res.json()["id"]

    # La simple création ne fait jamais basculer la commande.
    still_open = await client.get(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}", headers=headers)
    assert still_open.json()["status"] == "open"

    lock_first = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{first_id}/lock", headers=headers)
    assert lock_first.status_code == 200, lock_first.text
    still_open = await client.get(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}", headers=headers)
    assert still_open.json()["status"] == "open"

    second_res = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T16:00:00",
            "declaredVolumeLiters": 7000, "supplierId": supplier["id"], "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    second_id = second_res.json()["id"]
    lock_second = await client.post(f"/api/v1/zylo-liquid/delivery-declarations/{second_id}/lock", headers=headers)
    assert lock_second.status_code == 200, lock_second.text

    received = await client.get(f"/api/v1/zylo-liquid/purchase-orders/{order['id']}", headers=headers)
    assert received.json()["status"] == "received"

    # Plus aucune nouvelle réception sur cette commande — mais une
    # déclaration CORRECTIVE de la dernière livraison reste possible : elle
    # reproduit le rattachement d'origine, elle ne crée aucun volume nouveau.
    extra = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-02T08:00:00",
            "declaredVolumeLiters": 7000, "supplierId": supplier["id"], "purchaseOrderId": order["id"],
        },
        headers=headers,
    )
    assert extra.status_code == 409
    assert extra.json()["error"]["code"] == "purchase_order_received"

    correction = await client.post(
        "/api/v1/zylo-liquid/delivery-declarations",
        json={
            "stationId": station_id, "fuelProductId": fuel_product_id, "eventAt": "2026-02-01T16:00:00",
            "declaredVolumeLiters": 6900, "supplierId": supplier["id"], "purchaseOrderId": order["id"],
            "correctsDeclarationId": second_id, "changeReason": "Écart de comptage corrigé",
        },
        headers=headers,
    )
    assert correction.status_code == 201, correction.text
    assert correction.json()["correctsDeclarationId"] == second_id
