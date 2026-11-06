"""Tests BE-104 : mise à jour du profil organisation (PATCH /api/v1/organizations/{organization_id}).

Source : implementation-backend/tasks-portail-organisation.md, section BE-104.

Décisions appliquées à cette branche (écarts consignés dans docs/portail-organisation/profil-organisation.md) :
- Droit : `organization.update` (décision BE-186 sur la même route), au lieu de `org:profile:manage`.
- Champs modifiables : `name` seul (aucun autre champ modifiable dans le modèle, QE-POR-18).
- Champ sensible : `name` (toute modification écrit une entrée d'audit).
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from app.identity.models import Organization, OrganizationUser
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_PROFIL = "organization.update"


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    jeton = utilisateur["token"]
    entetes = {"Authorization": f"Bearer {jeton}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    """Crée un compte et renvoie son identifiant et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-104"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _ajouter_membre(organisation_id: str, user_id: str, codes_permissions: list[str] | None = None) -> None:
    """Rend `user_id` membre actif de l'organisation, avec un rôle dédié portant `codes_permissions` si fourni."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(user_id)))
        if codes_permissions:
            role = Role(organizationId=uuid.UUID(organisation_id), code=f"be104-{uuid.uuid4().hex[:8]}", name="Rôle BE-104")
            db.add(role)
            await db.flush()
            for code in codes_permissions:
                permission = await get_or_create_permission(db, code, "identity", "Permission de test BE-104")
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=uuid.UUID(user_id), organizationId=uuid.UUID(organisation_id), roleId=role.id))
        await db.commit()


async def _etat_organisation(organisation_id: str) -> tuple[str, int]:
    """Renvoie (nom, version) relus en base, sans passer par l'API."""
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organisation_id))
        return organisation.name, organisation.version


async def _profil_avec_droit(client: AsyncClient, organization: dict) -> dict:
    """Utilisateur membre de `organization` portant `PERMISSION_PROFIL`."""
    utilisateur = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], utilisateur["id"], [PERMISSION_PROFIL])
    return utilisateur


# ---------------------------------------------------------------------------
# CA-1 : PATCH avec la version courante et un champ autorisé -> 200, version incrémentée
# ---------------------------------------------------------------------------


async def test_ca1_patch_version_courante_renvoie_200_et_incremente_version(client: AsyncClient, organization: dict):
    acteur = await _profil_avec_droit(client, organization)
    _, version_avant = await _etat_organisation(organization["id"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Nouveau nom BE-104", "expectedVersion": version_avant},
        headers=_entetes(acteur, organization["id"]),
    )

    assert res.status_code == 200, res.text
    nom_apres, version_apres = await _etat_organisation(organization["id"])
    assert nom_apres == "Nouveau nom BE-104"
    assert version_apres == version_avant + 1


# ---------------------------------------------------------------------------
# CA-2 : PATCH avec une version obsolète -> 409, aucune modification
# ---------------------------------------------------------------------------


async def test_ca2_version_obsolete_renvoie_409_sans_modification(client: AsyncClient, organization: dict):
    acteur = await _profil_avec_droit(client, organization)
    nom_avant, version_avant = await _etat_organisation(organization["id"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Conflit BE-104", "expectedVersion": version_avant + 5},
        headers=_entetes(acteur, organization["id"]),
    )

    assert res.status_code == 409, res.text
    assert await _etat_organisation(organization["id"]) == (nom_avant, version_avant)


# ---------------------------------------------------------------------------
# CA-3 : champ non listé -> 400, aucune modification
# ---------------------------------------------------------------------------


async def test_ca3_champ_non_liste_renvoie_400_sans_modification(client: AsyncClient, organization: dict):
    acteur = await _profil_avec_droit(client, organization)
    nom_avant, version_avant = await _etat_organisation(organization["id"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Champ interdit BE-104", "status": "suspended", "expectedVersion": version_avant},
        headers=_entetes(acteur, organization["id"]),
    )

    assert res.status_code == 400, res.text
    assert await _etat_organisation(organization["id"]) == (nom_avant, version_avant)


# ---------------------------------------------------------------------------
# CA-4 : sans droit -> 403 ; organisation hors portée -> 404
# ---------------------------------------------------------------------------


async def test_ca4_sans_droit_renvoie_403(client: AsyncClient, organization: dict):
    sans_droit = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], sans_droit["id"], ["organization.read"])
    nom_avant, version_avant = await _etat_organisation(organization["id"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Refus BE-104", "expectedVersion": version_avant},
        headers=_entetes(sans_droit, organization["id"]),
    )

    assert res.status_code == 403, res.text
    assert await _etat_organisation(organization["id"]) == (nom_avant, version_avant)


async def test_ca4_organisation_hors_portee_renvoie_404(client: AsyncClient, organization: dict):
    """Un acteur membre de sa propre organisation ne modifie pas une autre organisation : 404, sans fuite."""
    acteur = await _profil_avec_droit(client, organization)
    autre = await _creer_utilisateur(client)
    creation = await client.post(
        "/api/v1/organizations",
        json={"name": "Autre BE-104", "slug": f"autre-be104-{uuid.uuid4().hex[:8]}"},
        headers=_entetes(autre),
    )
    autre_organisation_id = creation.json()["id"]
    nom_avant, version_avant = await _etat_organisation(autre_organisation_id)

    res = await client.patch(
        f"/api/v1/organizations/{autre_organisation_id}",
        json={"name": "Hors portée BE-104", "expectedVersion": version_avant},
        headers=_entetes(acteur, organization["id"]),
    )

    assert res.status_code == 404, res.text
    assert await _etat_organisation(autre_organisation_id) == (nom_avant, version_avant)


# ---------------------------------------------------------------------------
# CA-5 : modification d'un champ sensible -> entrée d'audit
# ---------------------------------------------------------------------------


async def test_ca5_modification_champ_sensible_ecrit_audit(client: AsyncClient, organization: dict):
    acteur = await _profil_avec_droit(client, organization)
    _, version_avant = await _etat_organisation(organization["id"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Audité BE-104", "expectedVersion": version_avant},
        headers=_entetes(acteur, organization["id"]),
    )
    assert res.status_code == 200, res.text

    async with AsyncSessionLocal() as db:
        evenements = (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.entityId == uuid.UUID(organization["id"]),
                    AuditEvent.action == "identity.organization.update",
                )
            )
        ).scalars().all()
    assert len(evenements) >= 1
    dernier = evenements[-1]
    assert dernier.actorUserId == uuid.UUID(acteur["id"])
    assert dernier.changes["name"]["after"] == "Audité BE-104"
