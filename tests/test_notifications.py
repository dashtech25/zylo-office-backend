"""Module Notifications (Web Push) — abonnements navigateur, cloisonnés par
utilisateur et organisation (T-004b lot 2)."""

import uuid

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.notifications import service as notifications_service
from app.notifications.models import NotificationInboxItem, PushSubscription
from tests.conftest import unique_email

PUSH_URL = "/api/v1/notifications/push-subscriptions"
VAPID_URL = "/api/v1/notifications/vapid-public-key"
INBOX_URL = "/api/v1/notifications/inbox"


def _payload(endpoint: str) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "BPlaceholderP256dh", "auth": "placeholderAuth"}, "userAgent": "pytest"}


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _second_user(client) -> dict:
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    return {"email": email, "accessToken": login["accessToken"]}


async def _row_count(endpoint: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalars().all()
        return len(rows)


async def _user_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _create_inbox_item(organization_id: str, recipient_user_id: uuid.UUID, source_event_id: uuid.UUID):
    async with AsyncSessionLocal() as db:
        item = await notifications_service.create_inbox_item(
            db,
            organization_id=uuid.UUID(organization_id),
            recipient_user_id=recipient_user_id,
            source_event_type="test.explicit",
            source_event_id=source_event_id,
            category="test",
            title="Message de test",
            body="Contenu de test",
        )
        await db.commit()
        return item.id


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


async def test_inbox_est_vide_et_exige_une_session(client, registered_user, organization):
    unauthorized = await client.get(INBOX_URL)
    assert unauthorized.status_code in (401, 403)

    response = await client.get(INBOX_URL, headers=_headers(registered_user, organization))
    assert response.status_code == 200, response.text
    assert response.json() == {"data": [], "meta": {"total": 0, "limit": 20, "offset": 0}}


async def test_inbox_isole_chaque_destinataire_et_marque_lu_de_facon_idempotente(client, registered_user, organization):
    owner_id = await _user_id(registered_user["email"])
    other = await _second_user(client)
    other_id = await _user_id(other["email"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(userId=other_id, organizationId=uuid.UUID(organization["id"])))
        await db.commit()

    source_event_id = uuid.uuid4()
    item_id = await _create_inbox_item(organization["id"], owner_id, source_event_id)
    owner_headers = _headers(registered_user, organization)
    other_headers = {"Authorization": f"Bearer {other['accessToken']}", "X-Organization-Id": organization["id"]}

    owner_list = await client.get(INBOX_URL, headers=owner_headers)
    assert owner_list.status_code == 200, owner_list.text
    assert owner_list.json()["meta"]["total"] == 1
    item = owner_list.json()["data"][0]
    assert item["id"] == str(item_id)
    assert "recipientUserId" not in item and "organizationId" not in item

    other_list = await client.get(INBOX_URL, headers=other_headers)
    assert other_list.status_code == 200, other_list.text
    assert other_list.json()["data"] == []
    assert other_list.json()["meta"]["total"] == 0
    assert (await client.get(f"{INBOX_URL}/{item_id}", headers=other_headers)).status_code == 404
    assert (await client.patch(f"{INBOX_URL}/{item_id}/read", headers=other_headers)).status_code == 404

    other_organization = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre organisation", "slug": f"autre-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {registered_user['accessToken']}"},
    )
    assert other_organization.status_code == 201, other_organization.text
    other_org_headers = {
        "Authorization": f"Bearer {registered_user['accessToken']}",
        "X-Organization-Id": other_organization.json()["id"],
    }
    assert (await client.get(INBOX_URL, headers=other_org_headers)).json()["data"] == []
    assert (await client.get(f"{INBOX_URL}/{item_id}", headers=other_org_headers)).status_code == 404

    first_read = await client.patch(f"{INBOX_URL}/{item_id}/read", headers=owner_headers)
    assert first_read.status_code == 200, first_read.text
    read_at = first_read.json()["readAt"]
    assert read_at is not None
    second_read = await client.patch(f"{INBOX_URL}/{item_id}/read", headers=owner_headers)
    assert second_read.status_code == 200, second_read.text
    assert second_read.json()["readAt"] == read_at
    unread = await client.get(f"{INBOX_URL}?unreadOnly=true", headers=owner_headers)
    assert unread.status_code == 200
    assert unread.json()["meta"]["total"] == 0


async def test_create_inbox_item_is_idempotent_par_evenement_et_destinataire(client, registered_user, organization):
    recipient_id = await _user_id(registered_user["email"])
    event_id = uuid.uuid4()
    first_id = await _create_inbox_item(organization["id"], recipient_id, event_id)
    second_id = await _create_inbox_item(organization["id"], recipient_id, event_id)

    assert first_id == second_id
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(NotificationInboxItem).where(
                    NotificationInboxItem.organizationId == uuid.UUID(organization["id"]),
                    NotificationInboxItem.recipientUserId == recipient_id,
                    NotificationInboxItem.sourceEventId == event_id,
                )
            )
        ).scalars().all()
    assert len(rows) == 1
