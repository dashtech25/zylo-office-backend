"""BE-106 : membres du portail d'organisation (liste, changement de rôle, retrait).

Intention : prouver par des tests les critères d'acceptation de BE-106
(implementation-backend/tasks-portail-organisation.md, section BE-106) :
- CA-1 : `GET /organizations/{id}/members` ne renvoie que les memberships de cette organisation,
  et une organisation étrangère est refusée en 404 (isolation tenant) ;
- CA-2 : retrait ou rétrogradation du dernier propriétaire -> 409, membership intact ;
- CA-3 : `DELETE` d'un membership appartenant à une autre organisation -> 404 ;
- CA-4 : sans la permission de gestion des membres -> 403 (liste, changement de rôle, retrait) ;
- CA-5 : un changement de rôle écrit l'événement `RoleChanged` et une entrée d'audit.

Routes testées :
- GET    /api/v1/organizations/{organization_id}/members
- POST   /api/v1/organizations/{organization_id}/role-changes   (corps : membershipId, roleIds)
- DELETE /api/v1/organizations/{organization_id}/members/{membership}

Écarts (consignés dans docs/portail-organisation/membres.md) : la fiche écrit une seule permission
`members:manage`, qui n'existe pas dans le code. Les permissions existantes sont utilisées :
`organization.members.read` (liste), `rbac.role.manage` (changement de rôle, comme BE-015),
`organization.members.remove` (retrait). Le membership est l'identifiant de `organization_user`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal, engine
from app.evenements.models import OutboxEvenement
from app.identity.models import OrganizationUser
from app.rbac.models import Role, UserRole

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


async def _inscrire_et_connecter(client: AsyncClient, nom: str) -> dict:
    """Compte de test : identifiant et en-tête d'autorisation."""
    email = f"be106-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    inscription = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    assert login.status_code == 200, login.text
    return {"id": inscription.json()["id"], "authorization": f"Bearer {login.json()['accessToken']}"}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str) -> str:
    """Organisation créée par `proprietaire`, qui en devient le seul propriétaire."""
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be106-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": proprietaire["authorization"]},
    )
    assert res.status_code in (200, 201), res.text
    return res.json()["id"]


async def _rattacher(organisation_id: str, utilisateur_id: str, role_id: uuid.UUID | None = None) -> None:
    """Rattache l'utilisateur à l'organisation ; lui donne le rôle `role_id` si fourni."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        if role_id is not None:
            db.add(UserRole(userId=uuid.UUID(utilisateur_id), organizationId=uuid.UUID(organisation_id), roleId=role_id))
        await db.commit()


async def _role_de_test(organisation_id: str, code: str) -> uuid.UUID:
    """Rôle transverse sans permission, propre à l'organisation de test."""
    async with AsyncSessionLocal() as db:
        role = Role(organizationId=uuid.UUID(organisation_id), code=f"be106-{code}-{uuid.uuid4().hex[:6]}", name="Rôle de test BE-106")
        db.add(role)
        await db.commit()
        return role.id


async def _membership_de(organisation_id: str, utilisateur_id: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(utilisateur_id),
            )
        )


async def _roles_de(organisation_id: str, utilisateur_id: str) -> list[uuid.UUID]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(UserRole.roleId).where(
                        UserRole.organizationId == uuid.UUID(organisation_id),
                        UserRole.userId == uuid.UUID(utilisateur_id),
                    )
                )
            ).all()
        )


async def _nombre_audit(organisation_id: str) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.organizationId == uuid.UUID(organisation_id)))
        ) or 0


async def _evenements(organisation_id: str, type_evenement: str) -> list[OutboxEvenement]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(OutboxEvenement).where(
                        OutboxEvenement.tenantId == uuid.UUID(organisation_id),
                        OutboxEvenement.eventType == type_evenement,
                    )
                )
            ).all()
        )


def _entetes(utilisateur: dict) -> dict:
    return {"Authorization": utilisateur["authorization"]}


def _url_membres(organisation_id: str) -> str:
    return f"/api/v1/organizations/{organisation_id}/members"


def _url_changements(organisation_id: str) -> str:
    return f"/api/v1/organizations/{organisation_id}/role-changes"


def _url_membership(organisation_id: str, membership_id: uuid.UUID) -> str:
    return f"/api/v1/organizations/{organisation_id}/members/{membership_id}"


async def test_be106_ca1_liste_ne_contient_que_les_memberships_de_l_organisation(client: AsyncClient):
    """CA-1 : un membre de l'organisation B n'apparaît jamais dans la liste de A ; B est 404 pour A."""
    proprietaire_a = await _inscrire_et_connecter(client, "Propriétaire A")
    proprietaire_b = await _inscrire_et_connecter(client, "Propriétaire B")
    org_a = await _creer_organisation(client, proprietaire_a, "Organisation A")
    org_b = await _creer_organisation(client, proprietaire_b, "Organisation B")

    liste_a = await client.get(_url_membres(org_a), headers=_entetes(proprietaire_a))
    assert liste_a.status_code == 200, liste_a.text
    ids_a = {entree["userId"] for entree in liste_a.json()}
    assert proprietaire_a["id"] in ids_a
    assert proprietaire_b["id"] not in ids_a

    hors_portee = await client.get(_url_membres(org_b), headers=_entetes(proprietaire_a))
    assert hors_portee.status_code == 404, hors_portee.text


async def test_be106_ca2_retrait_et_retrogradation_du_dernier_owner_donnent_409(client: AsyncClient):
    """CA-2 : le seul propriétaire ne peut ni se rétrograder ni se retirer ; rien n'est modifié."""
    proprietaire = await _inscrire_et_connecter(client, "Seul propriétaire")
    org = await _creer_organisation(client, proprietaire, "Organisation CA-2")
    membership = await _membership_de(org, proprietaire["id"])
    roles_avant = await _roles_de(org, proprietaire["id"])
    assert roles_avant, "le créateur doit avoir son rôle propriétaire"

    retrogradation = await client.post(
        _url_changements(org),
        json={"membershipId": str(membership), "roleIds": []},
        headers=_entetes(proprietaire),
    )
    assert retrogradation.status_code == 409, retrogradation.text
    assert await _roles_de(org, proprietaire["id"]) == roles_avant

    retrait = await client.delete(_url_membership(org, membership), headers=_entetes(proprietaire))
    assert retrait.status_code == 409, retrait.text
    assert await _membership_de(org, proprietaire["id"]) == membership


async def test_be106_ca3_membership_d_une_autre_organisation_donne_404(client: AsyncClient):
    """CA-3 : supprimer le membership d'un membre de B en passant par A est refusé en 404, sans effet."""
    proprietaire_a = await _inscrire_et_connecter(client, "Propriétaire A CA-3")
    proprietaire_b = await _inscrire_et_connecter(client, "Propriétaire B CA-3")
    org_a = await _creer_organisation(client, proprietaire_a, "Organisation A CA-3")
    org_b = await _creer_organisation(client, proprietaire_b, "Organisation B CA-3")
    membership_b = await _membership_de(org_b, proprietaire_b["id"])

    reponse = await client.delete(_url_membership(org_a, membership_b), headers=_entetes(proprietaire_a))
    assert reponse.status_code == 404, reponse.text
    assert await _membership_de(org_b, proprietaire_b["id"]) == membership_b


async def test_be106_ca4_sans_permission_de_gestion_des_membres_donne_403(client: AsyncClient):
    """CA-4 : un membre rattaché sans rôle ne peut ni lister, ni changer de rôle, ni retirer ; rien n'est écrit."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-4")
    simple_membre = await _inscrire_et_connecter(client, "Membre sans droit CA-4")
    org = await _creer_organisation(client, proprietaire, "Organisation CA-4")
    await _rattacher(org, simple_membre["id"])
    cible = await _inscrire_et_connecter(client, "Cible CA-4")
    await _rattacher(org, cible["id"], await _role_de_test(org, "cible"))
    membership_cible = await _membership_de(org, cible["id"])
    roles_avant = await _roles_de(org, cible["id"])

    liste = await client.get(_url_membres(org), headers=_entetes(simple_membre))
    assert liste.status_code == 403, liste.text

    changement = await client.post(
        _url_changements(org),
        json={"membershipId": str(membership_cible), "roleIds": []},
        headers=_entetes(simple_membre),
    )
    assert changement.status_code == 403, changement.text
    assert await _roles_de(org, cible["id"]) == roles_avant

    retrait = await client.delete(_url_membership(org, membership_cible), headers=_entetes(simple_membre))
    assert retrait.status_code == 403, retrait.text
    assert await _membership_de(org, cible["id"]) == membership_cible


async def test_be106_ca5_changement_de_role_ecrit_role_changed_et_audit(client: AsyncClient):
    """CA-5 : le propriétaire change le rôle d'un membre ; l'événement RoleChanged et une entrée d'audit sont écrits."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire CA-5")
    membre = await _inscrire_et_connecter(client, "Membre CA-5")
    org = await _creer_organisation(client, proprietaire, "Organisation CA-5")
    ancien_role = await _role_de_test(org, "ancien")
    nouveau_role = await _role_de_test(org, "nouveau")
    await _rattacher(org, membre["id"], ancien_role)
    membership = await _membership_de(org, membre["id"])
    audit_avant = await _nombre_audit(org)

    reponse = await client.post(
        _url_changements(org),
        json={"membershipId": str(membership), "roleIds": [str(nouveau_role)]},
        headers=_entetes(proprietaire),
    )

    assert reponse.status_code in (200, 201), reponse.text
    assert await _roles_de(org, membre["id"]) == [nouveau_role]
    assert await _nombre_audit(org) > audit_avant
    evenements = await _evenements(org, "RoleChanged")
    assert len(evenements) == 1
    # La colonne `payload` de l'outbox porte l'enveloppe complète : les données métier sont sous `payload`.
    assert evenements[0].payload["payload"]["userId"] == membre["id"]
    assert evenements[0].payload["subject"]["type"] == "membership"


async def test_be106_retrait_d_un_membre_emet_removed_et_audit(client: AsyncClient):
    """Complément : le retrait d'un membre (non propriétaire) écrit `Removed` et une entrée d'audit."""
    proprietaire = await _inscrire_et_connecter(client, "Propriétaire retrait")
    membre = await _inscrire_et_connecter(client, "Membre retiré")
    org = await _creer_organisation(client, proprietaire, "Organisation retrait")
    await _rattacher(org, membre["id"], await _role_de_test(org, "retire"))
    membership = await _membership_de(org, membre["id"])
    audit_avant = await _nombre_audit(org)

    reponse = await client.delete(_url_membership(org, membership), headers=_entetes(proprietaire))

    assert reponse.status_code in (200, 204), reponse.text
    assert await _membership_de(org, membre["id"]) is None
    assert await _nombre_audit(org) == audit_avant + 1
    assert len(await _evenements(org, "Removed")) == 1
