"""Facturation : catalogue de plans et abonnements d'essai (T-019, T-050 option A).

Intention : le catalogue n'est plus créable par API (`POST /billing/plans`
retiré). Les plans de test sont créés par le service, comme le ferait la
commande de seed ; un plan de même code mais de prix différent est refusé.
"""

import uuid

from httpx import AsyncClient

from app.billing import service
from app.core.database import AsyncSessionLocal


async def creer_plan_catalogue(code: str, prix: int = 1000) -> None:
    """Crée (ou retrouve) un plan du catalogue, comme la commande de seed."""
    async with AsyncSessionLocal() as db:
        await service.get_or_create_plan(db, "zylo_liquid", code, "Test Plan", prix, "XAF", 30)


async def test_catalogue_de_plans_lisible_sans_creation_par_api(client: AsyncClient, registered_user: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code)

    res = await client.get("/api/v1/billing/plans", headers=headers)
    assert res.status_code == 200
    assert any(p["code"] == plan_code for p in res.json())


async def test_creation_de_plan_par_api_est_retiree(client: AsyncClient, registered_user: dict):
    """Tout utilisateur connecté recevait 201 avant T-019 : la route n'existe plus."""
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}"}
    res = await client.post(
        "/api/v1/billing/plans",
        json={"moduleCode": "zylo_liquid", "code": f"plan-{uuid.uuid4().hex[:8]}", "name": "Pirate", "priceCents": 1, "currency": "XAF", "periodDays": 30},
        headers=headers,
    )
    assert res.status_code in (404, 405)


async def test_plan_existant_a_prix_different_refuse(client: AsyncClient):
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code, prix=1000)
    async with AsyncSessionLocal() as db:
        try:
            await service.get_or_create_plan(db, "zylo_liquid", plan_code, "Test Plan", 2000, "XAF", 30)
        except Exception as exc:  # AppError : code stable attendu
            assert getattr(exc, "status_code", None) == 409
            assert getattr(exc, "code", None) == "plan_conflict"
        else:
            raise AssertionError("un plan de même code et de prix différent doit être refusé")


async def test_trial_subscription_lifecycle(client: AsyncClient, registered_user: dict, organization: dict):
    headers = {"Authorization": f"Bearer {registered_user['accessToken']}", "X-Organization-Id": organization["id"]}
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code)

    res = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions", json={"planCode": plan_code}, headers=headers
    )
    assert res.status_code == 201
    assert res.json()["status"] == "trial"

    duplicate = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions", json={"planCode": plan_code}, headers=headers
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "subscription_already_active"
