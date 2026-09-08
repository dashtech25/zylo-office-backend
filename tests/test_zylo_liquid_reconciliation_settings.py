"""Tests de la configuration des tolérances de rapprochement (Phase 6 §6,
Phase 7 §1 de processus-double-sources-verite, Bloc 6 de
08-plan-implementation.md) : dérogation par station, repli implicite sur
NULL par défaut tant qu'aucune dérogation n'existe."""

import uuid

from httpx import AsyncClient


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def test_reconciliation_settings_absent_by_default(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]

    res = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings", headers=headers)
    assert res.status_code == 200
    assert res.json() is None


async def test_upsert_reconciliation_settings_creates_then_replaces(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    headers = _headers(registered_user, zylo_liquid_organization)
    suffix = uuid.uuid4().hex[:8]
    st_res = await client.post("/api/v1/zylo-liquid/stations", json={"name": f"Station {suffix}", "code": f"ST{suffix}"}, headers=headers)
    station_id = st_res.json()["id"]

    first = await client.put(
        f"/api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings",
        json={"deliveryWindowHours": 3, "gaugingHeightToleranceMm": 15},
        headers=headers,
    )
    assert first.status_code == 200, first.text
    assert first.json()["deliveryWindowHours"] == 3
    assert first.json()["deliveryVolumeToleranceFixedLiters"] is None

    second = await client.put(
        f"/api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings",
        json={"deliveryWindowHours": 1.5},
        headers=headers,
    )
    assert second.status_code == 200, second.text
    assert second.json()["deliveryWindowHours"] == 1.5
    # Champ non renvoyé cette fois -> réinitialisé à NULL (remplacement complet, pas un patch partiel).
    assert second.json()["gaugingHeightToleranceMm"] is None

    get_res = await client.get(f"/api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings", headers=headers)
    assert get_res.json()["deliveryWindowHours"] == 1.5


async def test_list_reconciliation_records_empty_for_a_fresh_subject(client: AsyncClient, registered_user: dict, zylo_liquid_organization: dict):
    """Aucun `ReconciliationRecord` n'est jamais créé automatiquement à la
    création d'une déclaration — seul un calcul explicite (Bloc 7) en
    produit. Filtré sur un `subjectId` fraîchement généré (jamais un total
    non filtré : le mécanisme de calcul, Bloc 7, écrit dans cette même base
    partagée par les autres tests de la suite)."""
    headers = _headers(registered_user, zylo_liquid_organization)
    res = await client.get(f"/api/v1/zylo-liquid/reconciliation-records?subjectId={uuid.uuid4()}", headers=headers)
    assert res.status_code == 200
    assert res.json()["meta"]["total"] == 0
