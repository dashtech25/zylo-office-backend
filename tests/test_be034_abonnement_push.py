"""BE-034 : abonnement push et désabonnement côté serveur.

Définition : tasks-socle-tenant-identite.md, section BE-034. Critères :
- CA-1 : le désabonnement côté serveur supprime l'abonnement (la ligne disparaît).
- CA-2 (refus) : sans session, POST et DELETE sont refusés (401).
- CA-3 (isolation) : un utilisateur A ne peut pas supprimer l'abonnement de B
  (404, et la ligne de B reste en base).
"""

import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.notifications.models import PushSubscription
from tests.conftest import unique_email

PUSH_URL = "/api/v1/notifications/push-subscriptions"


def _payload(endpoint: str) -> dict:
    return {"endpoint": endpoint, "keys": {"p256dh": "BPlaceholderP256dh", "auth": "placeholderAuth"}, "userAgent": "pytest"}


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


def _endpoint() -> str:
    return f"https://push.example.test/send/{uuid.uuid4().hex}"


async def _row_count(endpoint: str) -> int:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == endpoint))).scalars().all()
        return len(rows)


async def _second_member(client, organization: dict) -> dict:
    """Second utilisateur, membre de la MÊME organisation : l'isolation testée
    porte bien sur l'utilisateur, pas sur l'organisation."""
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre membre"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    async with AsyncSessionLocal() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
        db.add(OrganizationUser(userId=user_id, organizationId=uuid.UUID(organization["id"])))
        await db.commit()
    return {"email": email, "accessToken": login["accessToken"]}


async def test_ca1_desabonnement_supprime_l_abonnement_en_base(client, registered_user, organization):
    endpoint = _endpoint()
    headers = _headers(registered_user, organization)
    created = await client.post(PUSH_URL, json=_payload(endpoint), headers=headers)
    assert created.status_code == 200, created.text
    assert await _row_count(endpoint) == 1

    res = await client.delete(f"{PUSH_URL}/{created.json()['id']}", headers=headers)

    assert res.status_code == 204, res.text
    assert await _row_count(endpoint) == 0


async def test_ca1_desabonnement_ne_supprime_que_l_abonnement_designe(client, registered_user, organization):
    headers = _headers(registered_user, organization)
    keep_endpoint, drop_endpoint = _endpoint(), _endpoint()
    await client.post(PUSH_URL, json=_payload(keep_endpoint), headers=headers)
    dropped = await client.post(PUSH_URL, json=_payload(drop_endpoint), headers=headers)

    res = await client.delete(f"{PUSH_URL}/{dropped.json()['id']}", headers=headers)

    assert res.status_code == 204, res.text
    assert await _row_count(drop_endpoint) == 0
    assert await _row_count(keep_endpoint) == 1


async def test_ca1_desabonnement_d_un_abonnement_inexistant_renvoie_404(client, registered_user, organization):
    res = await client.delete(f"{PUSH_URL}/{uuid.uuid4()}", headers=_headers(registered_user, organization))

    assert res.status_code == 404, res.text


async def test_ca2_abonnement_sans_session_est_refuse(client):
    endpoint = _endpoint()

    res = await client.post(PUSH_URL, json=_payload(endpoint))

    assert res.status_code == 401, res.text
    assert await _row_count(endpoint) == 0


async def test_ca2_desabonnement_sans_session_est_refuse_et_garde_l_abonnement(client, registered_user, organization):
    endpoint = _endpoint()
    created = await client.post(PUSH_URL, json=_payload(endpoint), headers=_headers(registered_user, organization))
    assert created.status_code == 200, created.text

    res = await client.delete(f"{PUSH_URL}/{created.json()['id']}")

    assert res.status_code == 401, res.text
    assert await _row_count(endpoint) == 1


async def test_ca3_supprimer_l_abonnement_d_un_autre_utilisateur_renvoie_404_et_garde_la_ligne(client, registered_user, organization):
    endpoint = _endpoint()
    owner_headers = _headers(registered_user, organization)
    created = await client.post(PUSH_URL, json=_payload(endpoint), headers=owner_headers)
    assert created.status_code == 200, created.text
    other = await _second_member(client, organization)

    res = await client.delete(
        f"{PUSH_URL}/{created.json()['id']}",
        headers={"Authorization": f"Bearer {other['accessToken']}", "X-Organization-Id": organization["id"]},
    )

    assert res.status_code == 404, res.text
    assert await _row_count(endpoint) == 1
