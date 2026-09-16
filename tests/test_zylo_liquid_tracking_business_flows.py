"""Tests des flux métier du tracking GPS des camions-citernes (mission
« tracking », étape 2 — scénarios 1 à 8 validés avec le commanditaire).
Couvre :
  - réaffectation d'un boîtier : l'historique des positions passées reste
    attribué au bon camion, même après réaffectation ailleurs ;
  - lieux nommés : création, protection contre le déplacement d'un lieu
    déjà visité, suppression douce (jamais physique) si historique ;
  - reconnaissance automatique de lieu et réconciliation d'ambiguïté ;
  - alerte d'arrêt hors lieu connu, jamais liée à une station ;
  - commentaires multiples, modifiables/supprimables, jamais liés à une
    alerte ;
  - rattachement plusieurs-à-plusieurs camion<->commande."""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _create_truck(client: AsyncClient, headers: dict, suffix: str) -> dict:
    res = await client.post("/api/v1/zylo-liquid/trucks", json={"plateNumber": f"CM-{suffix}"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _create_gps_device(client: AsyncClient, headers: dict, suffix: str, truck_id: str | None) -> dict:
    body = {"deviceIdentifier": f"IMEI-{suffix}"}
    if truck_id is not None:
        body["truckId"] = truck_id
    res = await client.post("/api/v1/zylo-liquid/gps-devices", json=body, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def _get_ingest_secret(client: AsyncClient, headers: dict) -> str:
    res = await client.get("/api/v1/zylo-liquid/gps-ingest-credential", headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["secretToken"]


async def _ingest(client: AsyncClient, organization: dict, secret: str, device_identifier: str, at: datetime, lat: float, lon: float) -> None:
    res = await client.post(
        "/api/v1/zylo-liquid/gps/ingest",
        json={"deviceIdentifier": device_identifier, "recordedAt": at.isoformat(), "latitude": lat, "longitude": lon},
        headers={"X-Gps-Ingest-Secret": secret, "X-Organization-Id": organization["id"]},
    )
    assert res.status_code == 201, res.text


async def test_reassigning_gps_device_preserves_history_of_old_truck(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Les horodatages de position restent proches de « maintenant », dans
    le même ordre réel que les actions (association -> positions -> ré-
    affectation -> nouvelles positions) : l'historique d'association
    (`GpsDeviceAssignment`) est lui-même timestampé au moment réel de
    chaque appel API, donc jamais mélangé avec des dates synthétiques
    éloignées dans le passé, sous peine de fausser les bornes de période."""
    headers = _headers(registered_user, zylo_liquid_organization)
    truck_a = await _create_truck(client, headers, "REASSIGN-A")
    truck_b = await _create_truck(client, headers, "REASSIGN-B")
    device = await _create_gps_device(client, headers, "REASSIGN", truck_a["id"])
    secret = await _get_ingest_secret(client, headers)

    # `datetime.now()` repris à chaque appel : les 3 points sont aux mêmes
    # coordonnées, donc plausibles quel que soit l'écart réel (vitesse
    # implicite nulle) — surtout, `recordedAt` doit rester proche du temps
    # réel ici, jamais des minutes dans le "futur" simulé, car la lecture
    # ci-dessous se fait APRÈS la réaffectation réelle : la fenêtre
    # d'affectation du camion A serait alors bornée par le vrai
    # `unassignedAt` (horodaté au moment réel de l'appel `/unassign`), qui
    # exclurait toute position simulée plus tard que ce vrai instant.
    before_first_batch = datetime.now(timezone.utc).replace(tzinfo=None)
    for _ in range(3):
        await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], datetime.now(timezone.utc).replace(tzinfo=None), 4.05, 9.70)
    after_first_batch = datetime.now(timezone.utc).replace(tzinfo=None)

    # Réaffectation : le boîtier passe du camion A au camion B.
    res = await client.post(f"/api/v1/zylo-liquid/gps-devices/{device['id']}/unassign", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["truckId"] is None

    res = await client.patch(f"/api/v1/zylo-liquid/gps-devices/{device['id']}", json={"truckId": truck_b["id"]}, headers=headers)
    assert res.status_code == 200, res.text

    # Écart de temps explicite depuis le dernier point (voir commentaire
    # plus haut) — coordonnées proches, ce test vérifie l'attribution au bon
    # camion après réaffectation, pas la géographie du déplacement.
    before_second_position = after_first_batch + timedelta(seconds=30)
    await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], before_second_position, 4.0501, 9.7001)
    after_second_position = before_second_position + timedelta(seconds=10)

    # L'historique d'avant la réaffectation reste attribué au camion A.
    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck_a['id']}/positions",
        params={"since": before_first_batch.isoformat(), "until": after_first_batch.isoformat()},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert len(res.json()) == 3

    # Les nouvelles positions vont au camion B, jamais au camion A.
    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck_b['id']}/positions",
        params={"since": before_second_position.isoformat(), "until": after_second_position.isoformat()},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert len(res.json()) == 1

    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck_a['id']}/positions",
        params={"since": before_second_position.isoformat(), "until": after_second_position.isoformat()},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json() == []


async def test_unassign_requires_permission_and_active_device(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(f"/api/v1/zylo-liquid/gps-devices/{uuid.uuid4()}/unassign", headers=headers)
    assert res.status_code == 404


async def test_tracking_location_crud_and_move_protection(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    truck = await _create_truck(client, headers, "LOC-A")
    device = await _create_gps_device(client, headers, "LOC-A", truck["id"])
    secret = await _get_ingest_secret(client, headers)

    res = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": "Port de Douala", "type": "port", "latitude": 4.05, "longitude": 9.70, "radiusMeters": 150},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    location = res.json()

    # Jamais visité : renommer, déplacer, changer le rayon restent libres.
    res = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"latitude": 4.06}, headers=headers)
    assert res.status_code == 200, res.text

    # Génère un arrêt confirmé (>=10 min stable) au lieu déplacé, pour le qualifier.
    base = datetime.now(timezone.utc).replace(tzinfo=None)  # jamais avant l'ouverture de l'affectation boitier<->camion (voir _open_gps_device_assignment), sinon les positions tombent hors fenetre
    for i in range(0, 13):
        await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=i), 4.06, 9.70)
    # Reprise du mouvement : juste hors du rayon de détection (150m), jamais
    # à des centaines de km — le filtre de plausibilité (2026-09-13) rejette
    # un déplacement dont la vitesse implicite est irréaliste pour un camion.
    await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=20), 4.07, 9.71)

    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": (base - timedelta(minutes=5)).isoformat(), "until": (base + timedelta(minutes=30)).isoformat()},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    stops = res.json()
    assert len(stops) == 1
    assert stops[0]["locationId"] == location["id"]

    # Le lieu est maintenant visité : le déplacement doit être bloqué.
    res = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"latitude": 4.20}, headers=headers)
    assert res.status_code == 409, res.text

    # Renommer et changer le rayon restent libres même après visite.
    res = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"name": "Port de Douala (zone A)"}, headers=headers)
    assert res.status_code == 200, res.text
    res = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"radiusMeters": 200}, headers=headers)
    assert res.status_code == 200, res.text

    # Suppression douce : le lieu passe en `deleted`, jamais effacé physiquement.
    res = await client.delete(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "deleted"

    res = await client.get("/api/v1/zylo-liquid/tracking-locations", headers=headers)
    assert res.status_code == 200, res.text
    assert location["id"] not in {loc["id"] for loc in res.json()}

    res = await client.get("/api/v1/zylo-liquid/tracking-locations?includeDeleted=true", headers=headers)
    assert res.status_code == 200, res.text
    assert location["id"] in {loc["id"] for loc in res.json()}


async def test_never_visited_location_can_be_deleted_physically_or_freely_moved(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": "Dépôt jamais utilisé", "latitude": 3.0, "longitude": 8.0},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    location = res.json()

    res = await client.patch(f"/api/v1/zylo-liquid/tracking-locations/{location['id']}", json={"latitude": 3.5}, headers=headers)
    assert res.status_code == 200, res.text


async def test_overlapping_locations_ambiguous_go_to_reconciliation_queue(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    truck = await _create_truck(client, headers, "RECON-A")
    device = await _create_gps_device(client, headers, "RECON-A", truck["id"])
    secret = await _get_ingest_secret(client, headers)

    # Deux lieux quasi équidistants du point d'arrêt -> ambigu (écart < 20 %).
    res_a = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": "Entrepôt X", "latitude": 4.0500, "longitude": 9.7000, "radiusMeters": 300},
        headers=headers,
    )
    res_b = await client.post(
        "/api/v1/zylo-liquid/tracking-locations",
        json={"name": "Entrepôt Y", "latitude": 4.0510, "longitude": 9.7010, "radiusMeters": 300},
        headers=headers,
    )
    assert res_a.status_code == 201 and res_b.status_code == 201

    base = datetime.now(timezone.utc).replace(tzinfo=None)  # jamais avant l'ouverture de l'affectation boitier<->camion (voir _open_gps_device_assignment), sinon les positions tombent hors fenetre
    for i in range(0, 13):
        await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=i), 4.0505, 9.7005)
    # Reprise plausible (voir commentaire équivalent plus haut dans ce fichier).
    await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=20), 4.06, 9.71)

    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": (base - timedelta(minutes=5)).isoformat(), "until": (base + timedelta(minutes=30)).isoformat()},
        headers=headers,
    )
    stops = res.json()
    assert len(stops) == 1
    assert stops[0]["locationId"] is None
    assert stops[0]["reconciliationStatus"] == "pending"

    res = await client.get("/api/v1/zylo-liquid/truck-stop-reconciliations?status=pending", headers=headers)
    assert res.status_code == 200, res.text
    pending = res.json()
    assert len(pending) == 1
    reconciliation = pending[0]
    assert set(reconciliation["candidateLocationIds"]) == {res_a.json()["id"], res_b.json()["id"]}

    # Résolution humaine : choisir le lieu A.
    res = await client.post(
        f"/api/v1/zylo-liquid/truck-stop-reconciliations/{reconciliation['id']}/resolve",
        json={"locationId": res_a.json()["id"]},
        headers=headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "resolved"
    assert res.json()["resolvedLocationId"] == res_a.json()["id"]

    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": (base - timedelta(minutes=5)).isoformat(), "until": (base + timedelta(minutes=30)).isoformat()},
        headers=headers,
    )
    assert res.json()[0]["locationId"] == res_a.json()["id"]
    assert res.json()[0]["reconciliationStatus"] == "resolved"


async def test_unqualified_stop_triggers_alert_without_station(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    truck = await _create_truck(client, headers, "ALERT-A")
    device = await _create_gps_device(client, headers, "ALERT-A", truck["id"])
    secret = await _get_ingest_secret(client, headers)

    base = datetime.now(timezone.utc).replace(tzinfo=None)  # jamais avant l'ouverture de l'affectation boitier<->camion (voir _open_gps_device_assignment), sinon les positions tombent hors fenetre
    for i in range(0, 13):
        await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=i), 1.0, 1.0)
    # Reprise plausible (voir commentaire équivalent plus haut dans ce fichier).
    await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=20), 1.01, 1.01)

    res = await client.get("/api/v1/zylo-liquid/alerts?status=active&type=truck_stop_unqualified", headers=headers)
    assert res.status_code == 200, res.text
    alerts = res.json()["data"]
    assert len(alerts) == 1
    assert alerts[0]["stationId"] is None
    assert alerts[0]["truckId"] == truck["id"]


async def test_truck_stop_comments_multiple_editable_deletable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    truck = await _create_truck(client, headers, "CMT-A")
    device = await _create_gps_device(client, headers, "CMT-A", truck["id"])
    secret = await _get_ingest_secret(client, headers)

    base = datetime.now(timezone.utc).replace(tzinfo=None)  # jamais avant l'ouverture de l'affectation boitier<->camion (voir _open_gps_device_assignment), sinon les positions tombent hors fenetre
    for i in range(0, 13):
        await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=i), 2.0, 2.0)
    # Reprise plausible (voir commentaire équivalent plus haut dans ce fichier).
    await _ingest(client, zylo_liquid_organization, secret, device["deviceIdentifier"], base + timedelta(minutes=20), 2.01, 2.01)

    res = await client.get(
        f"/api/v1/zylo-liquid/trucks/{truck['id']}/stops",
        params={"since": (base - timedelta(minutes=5)).isoformat(), "until": (base + timedelta(minutes=30)).isoformat()},
        headers=headers,
    )
    stop_id = res.json()[0]["id"]

    res1 = await client.post(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", json={"body": "Bouchon au rond-point"}, headers=headers)
    assert res1.status_code == 201, res1.text
    res2 = await client.post(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", json={"body": "Confirmé par le chauffeur"}, headers=headers)
    assert res2.status_code == 201, res2.text

    res = await client.get(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", headers=headers)
    assert res.status_code == 200, res.text
    assert len(res.json()) == 2

    comment_id = res1.json()["id"]
    res = await client.patch(f"/api/v1/zylo-liquid/truck-stop-comments/{comment_id}", json={"body": "Bouchon au rond-point, résolu"}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["body"] == "Bouchon au rond-point, résolu"

    res = await client.delete(f"/api/v1/zylo-liquid/truck-stop-comments/{comment_id}", headers=headers)
    assert res.status_code == 204, res.text

    res = await client.get(f"/api/v1/zylo-liquid/truck-stops/{stop_id}/comments", headers=headers)
    assert len(res.json()) == 1


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


async def test_truck_order_assignment_is_many_to_many_and_bidirectional(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:6]
    station_id, _fuel_product_id, tank_id = await _setup_station_product_tank(client, headers, suffix)
    sup_res = await client.post("/api/v1/zylo-liquid/suppliers", json={"name": f"Fournisseur {suffix}", "type": "Grossiste"}, headers=headers)
    supplier_id = sup_res.json()["id"]
    order_res = await client.post(
        "/api/v1/zylo-liquid/purchase-orders",
        json={"stationId": station_id, "tankId": tank_id, "supplierId": supplier_id, "orderReference": f"CMD-{suffix}", "orderedVolumeLiters": 5000},
        headers=headers,
    )
    assert order_res.status_code == 201, order_res.text
    order_id = order_res.json()["id"]

    truck_1 = await _create_truck(client, headers, f"ORD1-{suffix}")
    truck_2 = await _create_truck(client, headers, f"ORD2-{suffix}")

    # Plusieurs camions sur une seule commande.
    for truck in (truck_1, truck_2):
        res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order_id}/trucks", json={"truckId": truck["id"]}, headers=headers)
        assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/zylo-liquid/purchase-orders/{order_id}/trucks", headers=headers)
    assert res.status_code == 200, res.text
    assert {a["truckId"] for a in res.json()} == {truck_1["id"], truck_2["id"]}

    # Un camion peut être rattaché à plusieurs commandes.
    order_res_2 = await client.post(
        "/api/v1/zylo-liquid/purchase-orders",
        json={"stationId": station_id, "tankId": tank_id, "supplierId": supplier_id, "orderReference": f"CMD2-{suffix}", "orderedVolumeLiters": 3000},
        headers=headers,
    )
    order_id_2 = order_res_2.json()["id"]
    res = await client.post(f"/api/v1/zylo-liquid/purchase-orders/{order_id_2}/trucks", json={"truckId": truck_1["id"]}, headers=headers)
    assert res.status_code == 201, res.text

    res = await client.get(f"/api/v1/zylo-liquid/trucks/{truck_1['id']}/orders", headers=headers)
    assert res.status_code == 200, res.text
    assert {a["purchaseOrderId"] for a in res.json()} == {order_id, order_id_2}

    # Détachement.
    res = await client.delete(f"/api/v1/zylo-liquid/purchase-orders/{order_id}/trucks/{truck_1['id']}", headers=headers)
    assert res.status_code == 204, res.text
    res = await client.get(f"/api/v1/zylo-liquid/purchase-orders/{order_id}/trucks", headers=headers)
    assert {a["truckId"] for a in res.json()} == {truck_2["id"]}


async def test_tracking_settings_default_then_configurable(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get("/api/v1/zylo-liquid/tracking-settings", headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["stopStabilizationMinutes"] is None  # aucun réglage -> repli sur la constante réseau

    res = await client.patch("/api/v1/zylo-liquid/tracking-settings", json={"stopStabilizationMinutes": 5, "stopRadiusMeters": 80}, headers=headers)
    assert res.status_code == 200, res.text
    assert res.json()["stopStabilizationMinutes"] == 5
    assert res.json()["stopRadiusMeters"] == 80
