"""BE-035 — Boîte de réception des notifications (définition :
implementation-backend/tasks-socle-tenant-identite.md, section BE-035).

Routes visées : `GET /api/v1/notifications/inbox` et
`PATCH /api/v1/notifications/inbox/{itemId}` (marquer lu). Droits : destinataire
uniquement ; refus sans session = 401 ; élément d'un autre destinataire = 404.
Aucun producteur métier n'est activé : la liste vide est l'état attendu.
"""

import uuid
from pathlib import Path

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.notifications import service as notifications_service
from app.notifications.models import NotificationInboxItem
from app.shared.events import publish
from tests.conftest import unique_email

INBOX_URL = "/api/v1/notifications/inbox"
APP_DIR = Path(__file__).resolve().parent.parent / "app"


def _headers(user: dict, organization: dict) -> dict:
    return {"Authorization": f"Bearer {user['accessToken']}", "X-Organization-Id": organization["id"]}


async def _second_user_in_org(client, organization: dict) -> tuple[dict, uuid.UUID]:
    """Crée un second compte, membre de la même organisation (isolation intra-organisation)."""
    email = unique_email()
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Autre"})
    login = (await client.post("/api/v1/auth/login", json={"email": email, "password": password})).json()
    async with AsyncSessionLocal() as db:
        user_id = await db.scalar(select(User.id).where(User.email == email))
        db.add(OrganizationUser(userId=user_id, organizationId=uuid.UUID(organization["id"])))
        await db.commit()
    return {"email": email, "accessToken": login["accessToken"]}, user_id


async def _owner_id(email: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(User.id).where(User.email == email))


async def _create_item(organization_id: str, recipient_id: uuid.UUID) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        item = await notifications_service.create_inbox_item(
            db,
            organization_id=uuid.UUID(organization_id),
            recipient_user_id=recipient_id,
            source_event_type="test.be035",
            source_event_id=uuid.uuid4(),
            category="test",
            title="Message de test",
            body="Contenu de test",
        )
        await db.commit()
        return item.id


async def _inbox_row_count(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count()).select_from(NotificationInboxItem).where(
                NotificationInboxItem.organizationId == uuid.UUID(organization_id)
            )
        )


async def _read_at_in_db(item_id: uuid.UUID):
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(NotificationInboxItem.readAt).where(NotificationInboxItem.id == item_id))


# CA-1 : une liste vide renvoie l'état vide, sans élément inventé.
async def test_ca1_liste_vide_renvoie_letat_vide_sans_element_invente(client, registered_user, organization):
    response = await client.get(INBOX_URL, headers=_headers(registered_user, organization))

    assert response.status_code == 200, response.text
    assert response.json() == {"data": [], "meta": {"total": 0, "limit": 20, "offset": 0}}
    assert await _inbox_row_count(organization["id"]) == 0


# Refus sans session : 401 (recommandation de la définition).
async def test_lecture_de_la_boite_sans_session_renvoie_401(client):
    response = await client.get(INBOX_URL)

    assert response.status_code == 401, response.text


# CA-2 (isolation) : le destinataire A ne lit ni ne modifie l'élément de B (404).
async def test_ca2_destinataire_a_ne_lit_ni_ne_modifie_lelement_de_b(client, registered_user, organization):
    other, other_id = await _second_user_in_org(client, organization)
    owner_headers = _headers(registered_user, organization)
    other_headers = {"Authorization": f"Bearer {other['accessToken']}", "X-Organization-Id": organization["id"]}
    item_of_other = await _create_item(organization["id"], other_id)

    assert (await client.get(f"{INBOX_URL}/{item_of_other}", headers=owner_headers)).status_code == 404
    intrusion = await client.patch(f"{INBOX_URL}/{item_of_other}", headers=owner_headers)
    assert intrusion.status_code == 404, intrusion.text
    assert await _read_at_in_db(item_of_other) is None
    assert (await client.get(INBOX_URL, headers=owner_headers)).json()["meta"]["total"] == 0
    assert (await client.get(INBOX_URL, headers=other_headers)).json()["meta"]["total"] == 1


# CA-3 : marquer lu persiste après rechargement.
async def test_ca3_marquer_lu_persiste_apres_rechargement(client, registered_user, organization):
    owner_id = await _owner_id(registered_user["email"])
    item_id = await _create_item(organization["id"], owner_id)
    headers = _headers(registered_user, organization)

    marked = await client.patch(f"{INBOX_URL}/{item_id}", headers=headers)

    assert marked.status_code == 200, marked.text
    assert marked.json()["readAt"] is not None
    reloaded = await client.get(f"{INBOX_URL}/{item_id}", headers=headers)
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.json()["readAt"] == marked.json()["readAt"]
    assert await _read_at_in_db(item_id) is not None
    assert (await client.get(f"{INBOX_URL}?unreadOnly=true", headers=headers)).json()["meta"]["total"] == 0


async def test_patch_sans_session_renvoie_401(client, registered_user, organization):
    item_id = await _create_item(organization["id"], await _owner_id(registered_user["email"]))

    response = await client.patch(f"{INBOX_URL}/{item_id}")

    assert response.status_code == 401, response.text
    assert await _read_at_in_db(item_id) is None


async def test_patch_element_inexistant_renvoie_404(client, registered_user, organization):
    response = await client.patch(f"{INBOX_URL}/{uuid.uuid4()}", headers=_headers(registered_user, organization))

    assert response.status_code == 404, response.text


# CA-4 : aucun élément n'est créé par le système sans producteur approuvé.
async def test_ca4_evenement_systeme_sans_producteur_ne_cree_aucun_element(client, registered_user, organization, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    before = await _inbox_row_count(organization["id"])

    await publish(
        "AlertCreated",
        alert_id=uuid.uuid4(), alert_type="test", severity="low", station_id=uuid.uuid4(), truck_id=None,
    )

    assert await _inbox_row_count(organization["id"]) == before == 0


async def test_ca4_seul_le_module_notifications_appelle_create_inbox_item():
    """Aucun producteur n'est raccordé : `create_inbox_item` n'est appelée nulle part
    hors du module Notifications (et de ses tests)."""
    appels = [
        chemin
        for chemin in APP_DIR.rglob("*.py")
        if "app/notifications/" not in chemin.as_posix() and "create_inbox_item(" in chemin.read_text(encoding="utf-8")
    ]

    assert appels == []
