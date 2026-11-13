"""BE-172 : routes API de consultation du journal d'audit.

Tests écrits d'après la définition `### BE-172` de
implementation-backend/tasks-parametres-notifications-audit.md, avant le code.

Routes cibles :
- `GET /api/v1/audit/evenements` : recherche (période et sujet obligatoires) ;
- `GET /api/v1/audit/evenements/{event_id}` : détail d'un événement.

Lecture seule de la table unique `audit_event` (BE-007, BE-152, BE-153) ; aucune
table ni migration. Organisation désignée par l'en-tête `X-Organization-Id`.

Écarts avec la définition, signalés ici et dans app/audit/consultation.py :
- la définition cite la permission `audit.read` ; le code existant utilise
  `audit.log.view` (BE-033, BE-260). Le code réutilise `audit.log.view`.
- la valeur de visibilité restreinte et la permission associée sont NON DÉFINIES
  (QE-PAR-16) : hypothèse retenue, `visibility = "restreinte"` exige la permission
  `audit.restricted.view`.

Couverture :
- CA-1 : une recherche sans période renvoie 422 (et sans sujet, 422) ;
- CA-2 : une recherche valide renvoie acteur, cible, action, motif, temps,
  résultat, corrélation et visibilité ;
- CA-3 (refus) : sans `audit.log.view`, 403 ;
- CA-4 : détail d'un événement restreint sans la permission de visibilité : 403,
  et 200 une fois la permission accordée ;
- CA-5 (isolation tenant) : un administrateur du tenant A reçoit 404 sur un
  identifiant du tenant B, et la recherche de A ne contient aucun événement de B.
"""

import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser, User
from app.rbac.models import RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

ROUTE = "/api/v1/audit/evenements"
MOT_DE_PASSE = "TestPassword123!"
TYPE_SUJET = "TestBe172Sujet"
ACTION = "test.be172.action"
MOTIF = "Motif BE172"
VISIBILITE_RESTREINTE = "restreinte"
PERMISSION_RESTREINTE = "audit.restricted.view"


def _periode() -> dict:
    """Fenêtre encadrant l'instant présent : contient les événements créés par les tests."""
    maintenant = datetime.now(timezone.utc)
    return {
        "dateDebut": (maintenant - timedelta(hours=1)).isoformat(),
        "dateFin": (maintenant + timedelta(hours=1)).isoformat(),
    }


def _entetes(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


async def _inscrire_et_connecter(client: AsyncClient) -> dict:
    """Crée un compte et renvoie son identifiant et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE172"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return {"id": str(user.id), "accessToken": login.json()["accessToken"]}


async def _id_de(utilisateur: dict) -> str:
    """Identifiant de l'utilisateur du fixture `registered_user` (lu en base par courriel)."""
    async with AsyncSessionLocal() as db:
        return str((await db.execute(select(User).where(User.email == utilisateur["email"]))).scalar_one().id)


async def _enregistrer(organization_id: str, actor_user_id: str, entity_id: uuid.UUID, visibility: str | None = None) -> str:
    """Écrit une entrée réelle via le service (table audit_event) et renvoie son identifiant."""
    async with AsyncSessionLocal() as db:
        evenement = await record_audit_event(
            db,
            uuid.UUID(organization_id),
            uuid.UUID(actor_user_id),
            action=ACTION,
            entity_type=TYPE_SUJET,
            entity_id=entity_id,
            summary="Résumé BE172",
            reason=MOTIF,
            visibility=visibility,
            correlation_id="be172-corr",
        )
        await db.commit()
        return str(evenement.id)


async def _ajouter_membre_sans_permission(client: AsyncClient, organization_id: str) -> dict:
    """Membre actif de l'organisation sans aucun rôle ni grant."""
    membre = await _inscrire_et_connecter(client)
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(membre["id"])))
        await db.commit()
    return membre


async def _accorder_permission_restreinte(user_id: str, organization_id: str) -> None:
    """Accorde `audit.restricted.view` via le rôle du propriétaire (rôle existant, pas de doublon)."""
    async with AsyncSessionLocal() as db:
        permission = await get_or_create_permission(db, PERMISSION_RESTREINTE, "audit", "Consulter les événements restreints.")
        role_id = (
            await db.execute(
                select(UserRole.roleId).where(
                    UserRole.userId == uuid.UUID(user_id), UserRole.organizationId == uuid.UUID(organization_id)
                )
            )
        ).scalars().first()
        db.add(RolePermission(roleId=role_id, permissionId=permission.id))
        await db.commit()


async def test_be172_ca1_recherche_sans_periode_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 : sans `dateDebut` / `dateFin`, la recherche est refusée en 422."""
    res = await client.get(
        ROUTE,
        params={"sujetType": TYPE_SUJET},
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 422, res.text


async def test_be172_ca1_recherche_sans_sujet_renvoie_422(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-1 (complément, définition : « filtres obligatoires période et sujet ») :
    sans `sujetType`, la recherche est refusée en 422 même avec une période."""
    res = await client.get(ROUTE, params=_periode(), headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 422, res.text


async def test_be172_ca2_recherche_valide_renvoie_les_champs(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-2 : une recherche valide renvoie acteur, cible, action, motif, temps,
    résultat, corrélation et visibilité de l'événement recherché."""
    cible = uuid.uuid4()
    evenement_id = await _enregistrer(organization["id"], await _id_de(registered_user), cible)

    res = await client.get(
        ROUTE,
        params={**_periode(), "sujetType": TYPE_SUJET},
        headers=_entetes(registered_user["accessToken"], organization["id"]),
    )

    assert res.status_code == 200, res.text
    ligne = next(ligne for ligne in res.json()["data"] if ligne["id"] == evenement_id)
    assert ligne["actorUserId"] == await _id_de(registered_user)
    assert ligne["entityType"] == TYPE_SUJET
    assert ligne["entityId"] == str(cible)
    assert ligne["action"] == ACTION
    assert ligne["reason"] == MOTIF
    assert ligne["createdAt"]
    assert ligne["result"] == "success"
    assert ligne["request_id"]
    assert "visibility" in ligne


async def test_be172_ca3_sans_audit_read_renvoie_403(client: AsyncClient, registered_user: dict, organization: dict):
    """CA-3 : un membre sans `audit.log.view` reçoit 403 `permission_denied`."""
    membre = await _ajouter_membre_sans_permission(client, organization["id"])

    res = await client.get(
        ROUTE,
        params={**_periode(), "sujetType": TYPE_SUJET},
        headers=_entetes(membre["accessToken"], organization["id"]),
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_be172_ca4_evenement_restreint_exige_la_permission_de_visibilite(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : le détail d'un événement de visibilité restreinte renvoie 403 sans
    `audit.restricted.view`, et 200 une fois la permission accordée."""
    user_id = await _id_de(registered_user)
    evenement_id = await _enregistrer(organization["id"], user_id, uuid.uuid4(), visibility=VISIBILITE_RESTREINTE)
    entetes = _entetes(registered_user["accessToken"], organization["id"])

    refuse = await client.get(f"{ROUTE}/{evenement_id}", headers=entetes)
    assert refuse.status_code == 403, refuse.text

    await _accorder_permission_restreinte(user_id, organization["id"])
    accepte = await client.get(f"{ROUTE}/{evenement_id}", headers=entetes)
    assert accepte.status_code == 200, accepte.text
    assert accepte.json()["id"] == evenement_id


async def test_be172_ca5_isolation_tenant_404_sur_identifiant_d_un_autre_tenant(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : un administrateur de A reçoit 404 sur un événement de B, et la
    recherche de A ne contient aucun événement de B."""
    autre = await _inscrire_et_connecter(client)
    creation = await client.post(
        "/api/v1/organizations",
        json={"name": "Tenant B BE172", "slug": f"tenant-b-be172-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {autre['accessToken']}"},
    )
    assert creation.status_code == 201, creation.text
    tenant_b = creation.json()["id"]
    evenement_b = await _enregistrer(tenant_b, autre["id"], uuid.uuid4())
    assert evenement_b

    entetes_a = _entetes(registered_user["accessToken"], organization["id"])
    direct = await client.get(f"{ROUTE}/{evenement_b}", headers=entetes_a)
    assert direct.status_code == 404, direct.text

    liste = await client.get(ROUTE, params={**_periode(), "sujetType": TYPE_SUJET}, headers=entetes_a)
    assert liste.status_code == 200, liste.text
    assert evenement_b not in [ligne["id"] for ligne in liste.json()["data"]]
