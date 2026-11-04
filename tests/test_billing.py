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


async def test_billing_reads_invoices_and_blocks_unconfigured_checkout_without_attempt(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": organization["id"],
    }
    plan_code = f"plan-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code, prix=1234)
    subscription_response = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions",
        json={"planCode": plan_code}, headers=headers,
    )
    assert subscription_response.status_code == 201
    subscription = await client.get(
        f"/api/v1/billing/organizations/{organization['id']}/subscription", headers=headers,
    )
    assert subscription.status_code == 200
    assert subscription.json()["planVersionId"]
    assert subscription.json()["entitlementCodes"] == []

    key = str(uuid.uuid4())
    invoice_response = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/invoices",
        json={"subscriptionId": subscription_response.json()["id"]},
        headers={**headers, "Idempotency-Key": key},
    )
    assert invoice_response.status_code == 201, invoice_response.text
    invoice = invoice_response.json()
    assert invoice["amountMinor"] == 1234
    assert invoice["currency"] == "XAF"
    assert invoice["status"] == "pending"

    retry = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/invoices",
        json={"subscriptionId": subscription_response.json()["id"]},
        headers={**headers, "Idempotency-Key": key},
    )
    assert retry.status_code == 201
    assert retry.json()["id"] == invoice["id"]

    listed = await client.get(f"/api/v1/billing/organizations/{organization['id']}/invoices", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == invoice["id"]

    attempt = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/invoices/{invoice['id']}/payment-attempts",
        headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert attempt.status_code == 503
    assert attempt.json()["error"]["code"] == "provider_not_configured"
    attempts = await client.get(
        f"/api/v1/billing/organizations/{organization['id']}/invoices/{invoice['id']}/payment-attempts",
        headers=headers,
    )
    assert attempts.status_code == 200
    assert attempts.json() == []


async def test_flutterwave_webhook_requires_secret_and_deduplicates_event(client: AsyncClient, monkeypatch):
    monkeypatch.delenv("FLUTTERWAVE_WEBHOOK_SECRET", raising=False)
    payload = {"id": f"evt-{uuid.uuid4().hex}", "event": "charge.completed", "data": {"id": "fake"}}
    unavailable = await client.post("/api/v1/billing/webhooks/flutterwave", json=payload)
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "provider_not_configured"

    monkeypatch.setenv("FLUTTERWAVE_WEBHOOK_SECRET", "test-only-webhook-secret")
    invalid = await client.post("/api/v1/billing/webhooks/flutterwave", json=payload, headers={"verif-hash": "wrong"})
    assert invalid.status_code == 401

    accepted = await client.post(
        "/api/v1/billing/webhooks/flutterwave", json=payload,
        headers={"verif-hash": "test-only-webhook-secret"},
    )
    assert accepted.status_code == 200
    assert accepted.json() == {"received": True, "duplicate": False}
    duplicate = await client.post(
        "/api/v1/billing/webhooks/flutterwave", json=payload,
        headers={"verif-hash": "test-only-webhook-secret"},
    )
    assert duplicate.status_code == 200
    assert duplicate.json() == {"received": True, "duplicate": True}
    conflict = await client.post(
        "/api/v1/billing/webhooks/flutterwave",
        json={**payload, "data": {"id": "different"}},
        headers={"verif-hash": "test-only-webhook-secret"},
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "webhook_event_conflict"


async def test_payment_provider_is_explicitly_disabled(client: AsyncClient):
    response = await client.get("/api/v1/billing/payment-provider")
    assert response.status_code == 200
    assert response.json()["mode"] == "test"
    assert response.json()["checkoutAvailable"] is False


async def test_price_versions_keep_existing_subscription_snapshot(
    client: AsyncClient, registered_user: dict, organization: dict,
):
    headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": organization["id"],
    }
    plan_code = f"versioned-{uuid.uuid4().hex[:8]}"
    await creer_plan_catalogue(plan_code, prix=1000)
    created = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/subscriptions",
        json={"planCode": plan_code}, headers=headers,
    )
    assert created.status_code == 201
    before = await client.get(f"/api/v1/billing/organizations/{organization['id']}/subscription", headers=headers)
    async with AsyncSessionLocal() as db:
        version = await service.publish_plan_version(db, plan_code, 2200, "XAF", 30, ["zylo_liquid.export"])
    assert version.version == 2

    key = str(uuid.uuid4())
    invoice = await client.post(
        f"/api/v1/billing/organizations/{organization['id']}/invoices",
        json={"subscriptionId": created.json()["id"]}, headers={**headers, "Idempotency-Key": key},
    )
    assert invoice.status_code == 201, invoice.text
    assert invoice.json()["amountMinor"] == 1000
    current_plan = await client.get("/api/v1/billing/plans", headers=headers)
    published = next(plan for plan in current_plan.json() if plan["code"] == plan_code)
    assert published["version"] == 2
    assert published["amountMinor"] == 2200
    after = await client.get(f"/api/v1/billing/organizations/{organization['id']}/subscription", headers=headers)
    assert after.json()["planVersionId"] == before.json()["planVersionId"]
