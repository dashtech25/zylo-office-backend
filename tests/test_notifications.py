"""Module Notifications (Web Push) — abonnements navigateur, cloisonnés par
utilisateur et organisation (T-004b lot 2)."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.notifications import service as notifications_service
from app.notifications.models import PushSubscription
from tests.conftest import unique_email

PUSH_URL = "/api/v1/notifications/push-subscriptions"
VAPID_URL = "/api/v1/notifications/vapid-public-key"


def _payload(endpoint: str) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "BPlaceholderP256dh", "auth": "placeholderAuth"}, "userAgent": "pytest"}


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _second_user(client) -> dict:
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    return {"accessToken": login["accessToken"]}


async def _row_count(endpoint: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalars().all()
        return len(rows)


async def test_vapid_public_key_endpoint_returns_configured_key(client):
    res = await client.get(VAPID_URL)
    assert res.status_code == 200
    assert res.json() == {"publicKey": settings.VAPID_PUBLIC_KEY}


async def test_push_subscription_requires_authentication(client):
    res = await client.post(PUSH_URL, json=_payload("https://push.example.test/send/anonyme"))
    assert res.status_code in (401, 403)


async def test_push_subscription_is_created_then_updated_for_same_user(client, registered_user, organization):
    endpoint = f"https://push.example.test/send/{uuid.uuid4().hex}"
    first = await client.post(PUSH_URL, json=_payload(endpoint), headers=_headers(registered_user, organization))
    assert first.status_code == 200, first.text
    second = await client.post(PUSH_URL, json=_payload(endpoint), headers=_headers(registered_user, organization))
    assert second.status_code == 200, second.text
    assert second.json()["id"] == first.json()["id"]
    assert await _row_count(endpoint) == 1


async def test_push_subscription_endpoint_owned_by_another_organization_is_refused(client, registered_user, organization):
    endpoint = f"https://push.example.test/send/{uuid.uuid4().hex}"
    owner = await client.post(PUSH_URL, json=_payload(endpoint), headers=_headers(registered_user, organization))
    assert owner.status_code == 200, owner.text

    # Un autre utilisateur, membre de SA propre organisation, tente de rattacher
    # le même navigateur (même endpoint) à son organisation : refusé (409).
    other = await _second_user(client)
    other_headers = {"Authorization": f"Bearer {other['accessToken']}"}
    other_org = await client.post(
        "/api/v1/organizations", json={"name": "Autre Org", "slug": f"autre-{uuid.uuid4().hex[:8]}"}, headers=other_headers
    )
    other_org_id = other_org.json()["id"]
    intrus = await client.post(PUSH_URL, json=_payload(endpoint), headers={**other_headers, "X-Organization-Id": other_org_id})
    assert intrus.status_code == 409, intrus.text
    async with AsyncSessionLocal() as db:
        row = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalar_one()
        assert str(row.organizationId) == organization["id"]


async def test_delete_push_subscription_of_another_user_has_no_effect(client, registered_user, organization):
    endpoint = f"https://push.example.test/send/{uuid.uuid4().hex}"
    created = await client.post(PUSH_URL, json=_payload(endpoint), headers=_headers(registered_user, organization))
    subscription_id = created.json()["id"]

    other = await _second_user(client)
    res = await client.delete(
        f"{PUSH_URL}/{subscription_id}", headers={"Authorization": f"Bearer {other['accessToken']}", "X-Organization-Id": organization["id"]}
    )
    assert res.status_code in (204, 403, 404)
    assert await _row_count(endpoint) == 1


async def test_alert_notification_is_silent_without_vapid_private_key(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    # Sans clé privée, aucune requête push ni lecture de base : retour silencieux.
    await notifications_service._notify_new_alert(
        alert_id=uuid.uuid4(), alert_type="test", severity="low", station_id=uuid.uuid4(), truck_id=None
    )


async def test_handler_alert_created_est_awaitable_par_publish(monkeypatch):
    # `app.shared.events.publish` fait `await handler(...)` : le handler doit
    # donc être une coroutine. Une version synchrone levait une TypeError à
    # chaque alerte créée, avalée et journalisée par publish.
    from app.shared.events import publish, subscribe, _handlers

    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    monkeypatch.setitem(_handlers, "AlertCreated", [])
    subscribe("AlertCreated", notifications_service.handle_alert_created)
    journal_erreurs: list[str] = []
    monkeypatch.setattr(
        "app.shared.events.logger",
        type("Journal", (), {"exception": lambda self, msg, *a, **k: journal_erreurs.append(msg)})(),
    )
    await publish(
        "AlertCreated",
        alert_id=uuid.uuid4(), alert_type="test", severity="low", station_id=uuid.uuid4(), truck_id=None,
    )
    assert journal_erreurs == []
