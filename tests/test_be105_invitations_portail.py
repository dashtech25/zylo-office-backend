"""BE-105 : invitations d'organisation du portail (création et acceptation).

Intention : prouver par des tests les critères d'acceptation de BE-105
(implementation-backend/tasks-portail-organisation.md, section BE-105) :
- CA-1 : création par un membre avec la permission d'invitation -> 201, invitation `pending`,
  événement `MemberInvited` émis (double d'événements) ;
- CA-2 : création par un membre sans la permission -> 403, aucune invitation créée ;
- CA-3 : acceptation par une identité autre que le destinataire -> 403, statut inchangé ;
- CA-4 : acceptation d'une invitation `expired` ou `revoked` -> 409, statut inchangé ;
- CA-5 : invitation demandant le rôle Owner -> refusée (QE-POR-04).

Routes testées :
- POST /api/v1/organizations/{organization_id}/invitations
- POST /api/v1/organizations/{organization_id}/invitations/{invitation}/accept

Écarts (consignés dans docs/portail-organisation/invitations.md) : la permission de création
est `organization.members.invite` (format domaine.entite.action, déjà seedée), et non
`members:manage` écrit dans la fiche ; le destinataire est désigné par `recipientUserId`.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.identity.models import Invitation, OrganizationUser
from app.rbac.models import Role, UserRole

MOT_DE_PASSE = "TestPassword123!"


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


@pytest.fixture
def evenements(monkeypatch):
    """Double d'événements : chaque appel à l'outbox est enregistré, sans écriture réelle."""
    recus: list[dict] = []

    async def double(db, donnees, *, emetteur_tenant):
        recus.append(donnees)
        return None

    monkeypatch.setattr("app.identity.invitations_portail.enregistrer_evenement", double)
    return recus


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/invitations"


def _entete(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _inscrit(client: AsyncClient) -> dict:
    """Utilisateur inscrit et connecté : id, e-mail et jeton d'accès."""
    email = f"be105-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    inscription = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Personne BE-105"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"id": inscription.json()["id"], "accessToken": login.json()["accessToken"]}


async def _rattache_sans_role(organization_id: str, user_id: str) -> None:
    """Appartenance à l'organisation sans aucun rôle (aucune permission d'invitation)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organization_id), userId=uuid.UUID(user_id)))
        await db.commit()


async def _id_de(client: AsyncClient, utilisateur: dict) -> str:
    """Identifiant d'un utilisateur de test, lu via le profil de la session."""
    profil = await client.get("/api/v1/account/profile", headers=_entete(utilisateur["accessToken"]))
    return profil.json()["id"]


async def _role_owner(organization_id: str) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Role.id).where(Role.organizationId == uuid.UUID(organization_id), Role.code == "owner")
        )


async def _insere_invitation(organization_id: str, recipient_id: str, createur_id: str, statut: str) -> uuid.UUID:
    """Invitation déjà existante, dans l'état voulu, pour tester l'acceptation."""
    async with AsyncSessionLocal() as db:
        ligne = Invitation(
            organizationId=uuid.UUID(organization_id),
            recipientUserId=uuid.UUID(recipient_id),
            roleId=None,
            status=statut,
            expiresAt=datetime.now(timezone.utc) + timedelta(days=7),
            createdByUserId=uuid.UUID(createur_id),
        )
        db.add(ligne)
        await db.commit()
        return ligne.id


async def _statut(invitation_id: uuid.UUID) -> str:
    async with AsyncSessionLocal() as db:
        return await db.scalar(select(Invitation.status).where(Invitation.id == invitation_id))


async def _nombre_invitations(organization_id: str) -> int:
    async with AsyncSessionLocal() as db:
        resultat = await db.scalars(select(Invitation.id).where(Invitation.organizationId == uuid.UUID(organization_id)))
        return len(resultat.all())


async def test_ca1_creation_par_membre_avec_droit_cree_invitation_pending_et_emet_member_invited(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """CA-1 : le propriétaire (permission d'invitation) crée une invitation `pending` ; MemberInvited est émis."""
    destinataire = await _inscrit(client)

    reponse = await client.post(
        _url(organization["id"]),
        json={"recipientUserId": destinataire["id"]},
        headers=_entete(registered_user["accessToken"]),
    )

    assert reponse.status_code == 201, reponse.text
    corps = reponse.json()
    assert corps["status"] == "pending"
    assert corps["recipientUserId"] == destinataire["id"]
    assert await _nombre_invitations(organization["id"]) == 1
    types = [evt["eventType"] for evt in evenements]
    assert types == ["MemberInvited"]


async def test_ca2_creation_par_membre_sans_droit_retourne_403_sans_invitation(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """CA-2 : un membre sans `organization.members.invite` ne crée aucune invitation."""
    membre = await _inscrit(client)
    await _rattache_sans_role(organization["id"], membre["id"])
    destinataire = await _inscrit(client)

    reponse = await client.post(
        _url(organization["id"]),
        json={"recipientUserId": destinataire["id"]},
        headers=_entete(membre["accessToken"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "permission_denied"
    assert await _nombre_invitations(organization["id"]) == 0
    assert evenements == []


async def test_ca3_acceptation_par_une_autre_identite_retourne_403(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """CA-3 : seule l'identité destinataire peut accepter ; le statut reste `pending`."""
    destinataire = await _inscrit(client)
    autre = await _inscrit(client)
    invitation_id = await _insere_invitation(
        organization["id"], destinataire["id"], await _id_de(client, registered_user), "pending"
    )

    reponse = await client.post(
        f"{_url(organization['id'])}/{invitation_id}/accept",
        headers=_entete(autre["accessToken"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert await _statut(invitation_id) == "pending"


@pytest.mark.parametrize("statut", ["expired", "revoked"])
async def test_ca4_acceptation_d_une_invitation_expiree_ou_revoquee_retourne_409(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list, statut: str
):
    """CA-4 : invitation `expired` ou `revoked` -> 409, statut inchangé."""
    destinataire = await _inscrit(client)
    invitation_id = await _insere_invitation(
        organization["id"], destinataire["id"], await _id_de(client, registered_user), statut
    )

    reponse = await client.post(
        f"{_url(organization['id'])}/{invitation_id}/accept",
        headers=_entete(destinataire["accessToken"]),
    )

    assert reponse.status_code == 409, reponse.text
    assert await _statut(invitation_id) == statut
    assert await _nombre_invitations(organization["id"]) == 1


async def test_ca5_invitation_au_role_owner_est_refusee(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """CA-5 : aucune invitation ne propose le rôle Owner (QE-POR-04) ; aucune ligne n'est écrite."""
    destinataire = await _inscrit(client)
    role_owner = await _role_owner(organization["id"])

    reponse = await client.post(
        _url(organization["id"]),
        json={"recipientUserId": destinataire["id"], "roleId": str(role_owner)},
        headers=_entete(registered_user["accessToken"]),
    )

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "owner_role_forbidden"
    assert await _nombre_invitations(organization["id"]) == 0
    assert evenements == []


async def test_acceptation_par_le_destinataire_cree_l_appartenance_et_emet_l_evenement(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """Acceptation nominale : statut `accepted`, appartenance créée, événement d'acceptation émis."""
    destinataire = await _inscrit(client)
    invitation_id = await _insere_invitation(
        organization["id"], destinataire["id"], await _id_de(client, registered_user), "pending"
    )

    reponse = await client.post(
        f"{_url(organization['id'])}/{invitation_id}/accept",
        headers=_entete(destinataire["accessToken"]),
    )

    assert reponse.status_code == 200, reponse.text
    assert await _statut(invitation_id) == "accepted"
    async with AsyncSessionLocal() as db:
        appartenance = await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == uuid.UUID(organization["id"]),
                OrganizationUser.userId == uuid.UUID(destinataire["id"]),
            )
        )
    assert appartenance is not None
    assert [evt["eventType"] for evt in evenements] == ["InvitationAccepted"]


async def test_creation_sans_session_retourne_401(client: AsyncClient, organization: dict, evenements: list):
    """Sans jeton d'accès, la création est refusée avant toute écriture."""
    reponse = await client.post(_url(organization["id"]), json={"recipientUserId": str(uuid.uuid4())})

    assert reponse.status_code == 401, reponse.text
    assert await _nombre_invitations(organization["id"]) == 0


async def test_creation_par_non_membre_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict, evenements: list
):
    """Un utilisateur hors de l'organisation ne voit pas celle-ci : 404 uniforme, rien d'écrit."""
    etranger = await _inscrit(client)
    destinataire = await _inscrit(client)

    reponse = await client.post(
        _url(organization["id"]),
        json={"recipientUserId": destinataire["id"]},
        headers=_entete(etranger["accessToken"]),
    )

    assert reponse.status_code == 404, reponse.text
    assert await _nombre_invitations(organization["id"]) == 0


