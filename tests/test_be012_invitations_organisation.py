"""Invitations à rejoindre une organisation : création et jeton à usage unique (BE-012).

Définition : implementation-backend/tasks-socle-tenant-identite.md, section BE-012.
Routes : POST et GET /api/v1/organizations/current/invitations, organisation
courante désignée par l'en-tête X-Organization-Id.

Critères testés :
- CA-1 : un administrateur crée une invitation ; elle apparaît dans la liste de son organisation ;
- CA-2 (refus) : un membre sans permission d'inviter reçoit 403, aucune invitation n'est créée ;
- CA-3 (isolation) : la liste des invitations de O1 ne contient aucune invitation de O2 ;
- CA-4 : le jeton d'invitation n'est stocké que sous forme de condensat SHA-256 ;
- CA-5 : une invitation créée ouvre une entrée d'audit.

Le lien d'invitation part par e-mail (boîte mémoire) ; le test lit le jeton dans ce
message, jamais dans la réponse de l'API.
"""

import hashlib
import re
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.shared.email import memory_outbox
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
URL_INVITATIONS = "/api/v1/organizations/current/invitations"
REGEX_JETON = re.compile(r"#token=([A-Za-z0-9_\-]+)")
ACTION_INVITATION_CREATE = "identity.organization.invitation.create"


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": f"Bearer {utilisateur['token']}", "X-Organization-Id": organisation_id}


async def _inscrire(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur test"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "email": email, "token": token}


async def _administrateur(client: AsyncClient) -> dict:
    """Utilisateur ayant créé une organisation : propriétaire, donc administrateur."""
    acteur = await _inscrire(client)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": f"Bearer {acteur['token']}"},
    )
    assert res.status_code == 201, res.text
    acteur["organisation"] = res.json()["id"]
    return acteur


async def _ajouter_membre_sans_role(client: AsyncClient, organisation_id: str) -> dict:
    """Membre rattaché à l'organisation sans aucun rôle : pas de permission d'inviter."""
    membre = await _inscrire(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(membre["id"])))
        await db.commit()
    membre["organisation"] = organisation_id
    return membre


async def _creer_invitation(client: AsyncClient, acteur: dict, email: str | None = None) -> dict:
    res = await client.post(
        URL_INVITATIONS,
        json={"email": email or unique_email(), "roleId": None},
        headers=_entetes(acteur, acteur["organisation"]),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _lister(client: AsyncClient, acteur: dict, organisation_id: str):
    return await client.get(URL_INVITATIONS, headers=_entetes(acteur, organisation_id))


def _jeton_envoye(email: str) -> str:
    message = [m for m in memory_outbox() if m.to == email][-1]
    correspondance = REGEX_JETON.search(message.body)
    assert correspondance is not None, "le message d'invitation doit contenir le lien avec le jeton"
    return correspondance.group(1)


async def _lignes_invitation(**filtres) -> list[dict]:
    """Lit la table directement : c'est la base qui fait foi, pas la réponse de l'API."""
    clause = " AND ".join(f'"{nom}" = :{nom}' for nom in filtres) or "TRUE"
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(text(f'SELECT * FROM "organizationInvitation" WHERE {clause}'), filtres)
        return [dict(ligne._mapping) for ligne in resultat]


@pytest.fixture(autouse=True)
def _boite_de_test(monkeypatch):
    """Envoi en boîte mémoire pour ce module seulement (réglage sur `settings`)."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    yield
    memory_outbox().clear()


async def test_administrateur_cree_une_invitation_visible_dans_la_liste(client: AsyncClient):
    """CA-1 : création (201, e-mail envoyé) puis présence dans la liste de l'organisation."""
    admin = await _administrateur(client)
    email = unique_email()

    cree = await _creer_invitation(client, admin, email)
    assert cree["email"] == email
    assert cree["status"] == "pending"

    liste = await _lister(client, admin, admin["organisation"])
    assert liste.status_code == 200, liste.text
    emails = [item["email"] for item in liste.json()]
    assert email in emails
    assert any(m.to == email for m in memory_outbox())


async def test_membre_sans_permission_recoit_403_et_rien_n_est_cree(client: AsyncClient):
    """CA-2 : sans permission d'inviter, 403 ; aucune ligne, aucun e-mail."""
    admin = await _administrateur(client)
    membre = await _ajouter_membre_sans_role(client, admin["organisation"])
    email = unique_email()

    res = await client.post(
        URL_INVITATIONS,
        json={"email": email, "roleId": None},
        headers=_entetes(membre, admin["organisation"]),
    )
    assert res.status_code == 403, res.text
    assert await _lignes_invitation(email=email) == []
    assert not any(m.to == email for m in memory_outbox())


async def test_liste_isolee_par_organisation(client: AsyncClient):
    """CA-3 : la liste de O1 ne contient aucune invitation de O2, et inversement."""
    admin_1 = await _administrateur(client)
    admin_2 = await _administrateur(client)
    email_1 = unique_email()
    email_2 = unique_email()
    await _creer_invitation(client, admin_1, email_1)
    await _creer_invitation(client, admin_2, email_2)

    liste_1 = await _lister(client, admin_1, admin_1["organisation"])
    liste_2 = await _lister(client, admin_2, admin_2["organisation"])
    emails_1 = [item["email"] for item in liste_1.json()]
    emails_2 = [item["email"] for item in liste_2.json()]

    assert email_1 in emails_1
    assert email_2 not in emails_1
    assert email_2 in emails_2
    assert email_1 not in emails_2


async def test_jeton_stocke_seulement_sous_forme_de_condensat(client: AsyncClient):
    """CA-4 : la base ne contient que le SHA-256 du jeton envoyé, jamais le jeton ;
    la réponse de création ne contient pas le jeton non plus."""
    admin = await _administrateur(client)
    email = unique_email()
    cree = await _creer_invitation(client, admin, email)
    jeton = _jeton_envoye(email)

    lignes = await _lignes_invitation(email=email)
    assert len(lignes) == 1
    ligne = lignes[0]
    assert ligne["tokenHash"] == hashlib.sha256(jeton.encode()).hexdigest()
    assert jeton not in str(ligne.values())
    assert jeton not in str(cree)


async def test_creation_ouvre_une_entree_d_audit(client: AsyncClient):
    """CA-5 : une entrée d'audit est écrite pour l'organisation, avec l'acteur."""
    admin = await _administrateur(client)
    email = unique_email()
    cree = await _creer_invitation(client, admin, email)

    async with AsyncSessionLocal() as db:
        resultat = await db.execute(
            text(
                'SELECT "actorUserId", "entityId" FROM audit_event '
                'WHERE "organizationId" = :org AND action = :action'
            ),
            {"org": uuid.UUID(admin["organisation"]), "action": ACTION_INVITATION_CREATE},
        )
        entrees = [dict(ligne._mapping) for ligne in resultat]

    assert len(entrees) == 1
    assert str(entrees[0]["actorUserId"]) == admin["id"]
    assert str(entrees[0]["entityId"]) == cree["id"]
