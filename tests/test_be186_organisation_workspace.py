"""Tests BE-186 : organisation et workspace (CA-1 à CA-5).

Source : implementation-backend/tasks-donnees-api-contrats.md, section BE-186.

Décisions de cette branche (QE de la fiche, appliquées sans attendre) :
- PATCH `/api/v1/organizations/{organization_id}` existe déjà sur develop (BE-104
  le porte) ; BE-186 en fixe les droits : `organization.update` (au lieu de
  `identity.organization.manage`) et le verrou `expectedVersion`.
- `organization.tenantId` : clé étrangère vers `tenant.id`, unique. Une
  organisation créée reçoit son tenant racine ; un tenant porte au plus une
  organisation (CA-1).
- Identifiants légaux : colonnes `legalRegistrationNumberChiffre` et
  `legalTaxNumberChiffre`, chiffrées au repos (app.core.field_crypto) ; visibles
  dans la réponse de GET seulement avec `organization.legal.read`.
- Aucun workspace en v1 (QE-API-05) : aucune table ni route `workspace`.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.core.field_crypto import chiffrer
from app.identity.models import Organization, OrganizationUser, Tenant
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    jeton = utilisateur.get("token") or utilisateur["accessToken"]
    entetes = {"Authorization": f"Bearer {jeton}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    """Crée un compte et renvoie son identifiant et son jeton d'accès."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-186"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _ajouter_membre(organisation_id: str, user_id: str, codes_permissions: list[str] | None = None) -> None:
    """Rend `user_id` membre actif de l'organisation.

    Si `codes_permissions` est fourni, crée un rôle dédié ne portant que ces
    permissions et l'attribue ; sinon le membre n'a aucun rôle.
    """
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(user_id)))
        if codes_permissions:
            role = Role(organizationId=uuid.UUID(organisation_id), code=f"be186-{uuid.uuid4().hex[:8]}", name="Rôle BE-186")
            db.add(role)
            await db.flush()
            for code in codes_permissions:
                permission = await get_or_create_permission(db, code, "identity", "Permission de test BE-186")
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=uuid.UUID(user_id), organizationId=uuid.UUID(organisation_id), roleId=role.id))
        await db.commit()


async def _definir_identifiants_legaux(organisation_id: str, registre: str, fiscal: str) -> None:
    """Renseigne les identifiants légaux chiffrés de l'organisation (aucune route ne les écrit en BE-186)."""
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organisation_id))
        organisation.legalRegistrationNumberChiffre = chiffrer(registre)
        organisation.legalTaxNumberChiffre = chiffrer(fiscal)
        await db.commit()


# ---------------------------------------------------------------------------
# CA-1 : un tenant actif possède exactement une organisation (unicité de tenantId)
# ---------------------------------------------------------------------------


async def test_ca1_organisation_creee_recoit_un_tenant_actif(organization: dict):
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organization["id"]))
        assert organisation.tenantId is not None
        tenant = await db.get(Tenant, organisation.tenantId)
        assert tenant is not None
        assert tenant.status == "active"


async def test_ca1_un_tenant_ne_porte_qu_une_organisation(organization: dict):
    """Une seconde organisation sur le même tenant est refusée par la contrainte d'unicité."""
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organization["id"]))
        db.add(Organization(name="Doublon BE-186", slug=f"doublon-{uuid.uuid4().hex[:8]}", status="active", tenantId=organisation.tenantId))
        with pytest.raises(IntegrityError):
            await db.commit()


# ---------------------------------------------------------------------------
# CA-2 : PATCH avec expectedVersion obsolète renvoie 409
# ---------------------------------------------------------------------------


async def test_ca2_patch_avec_expected_version_obsolete_renvoie_409(client: AsyncClient, organization: dict, registered_user: dict):
    entetes = _entetes(registered_user, organization["id"])
    premier = await client.patch(
        f"/api/v1/organizations/{organization['id']}", json={"name": "Nom 1", "expectedVersion": 1}, headers=entetes
    )
    assert premier.status_code == 200, premier.text
    assert premier.json()["version"] == 2

    obsolete = await client.patch(
        f"/api/v1/organizations/{organization['id']}", json={"name": "Nom 2", "expectedVersion": 1}, headers=entetes
    )
    assert obsolete.status_code == 409, obsolete.text


# ---------------------------------------------------------------------------
# CA-3 : GET sur une organisation d'un autre tenant renvoie 404
# ---------------------------------------------------------------------------


async def test_ca3_get_sur_organisation_d_un_autre_tenant_renvoie_404(client: AsyncClient, organization: dict):
    autre = await _creer_utilisateur(client)
    res = await client.get(f"/api/v1/organizations/{organization['id']}", headers=_entetes(autre, organization["id"]))
    assert res.status_code == 404, res.text


async def test_ca3_get_sur_sa_propre_organisation_renvoie_200(client: AsyncClient, organization: dict, registered_user: dict):
    res = await client.get(
        f"/api/v1/organizations/{organization['id']}", headers=_entetes(registered_user, organization["id"])
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == organization["id"]
    assert res.json()["version"] == 1


# ---------------------------------------------------------------------------
# CA-4 : PATCH sans organization.update renvoie 403
# ---------------------------------------------------------------------------


async def test_ca4_patch_sans_organization_update_renvoie_403(client: AsyncClient, organization: dict):
    lecteur = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], lecteur["id"], ["organization.read"])

    res = await client.patch(
        f"/api/v1/organizations/{organization['id']}",
        json={"name": "Refus", "expectedVersion": 1},
        headers=_entetes(lecteur, organization["id"]),
    )
    assert res.status_code == 403, res.text


async def test_ca4_membre_sans_droit_de_lecture_renvoie_403_sur_get(client: AsyncClient, organization: dict):
    sans_droit = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], sans_droit["id"], None)

    res = await client.get(f"/api/v1/organizations/{organization['id']}", headers=_entetes(sans_droit, organization["id"]))
    assert res.status_code == 403, res.text


# ---------------------------------------------------------------------------
# CA-5 : identifiants légaux absents sans organization.legal.read
# ---------------------------------------------------------------------------


async def test_ca5_identifiants_legaux_absents_sans_organization_legal_read(client: AsyncClient, organization: dict):
    await _definir_identifiants_legaux(organization["id"], "RCS-186-XYZ", "FR-TVA-186")
    lecteur = await _creer_utilisateur(client)
    await _ajouter_membre(organization["id"], lecteur["id"], ["organization.read"])

    res = await client.get(f"/api/v1/organizations/{organization['id']}", headers=_entetes(lecteur, organization["id"]))
    assert res.status_code == 200, res.text
    assert "legalRegistrationNumber" not in res.json()
    assert "legalTaxNumber" not in res.json()
    assert "RCS-186-XYZ" not in res.text
    assert "FR-TVA-186" not in res.text


async def test_ca5_identifiants_legaux_visibles_avec_organization_legal_read(client: AsyncClient, organization: dict, registered_user: dict):
    """Le propriétaire détient `organization.legal.read` : les valeurs sont déchiffrées dans la réponse."""
    await _definir_identifiants_legaux(organization["id"], "RCS-186-XYZ", "FR-TVA-186")

    res = await client.get(
        f"/api/v1/organizations/{organization['id']}", headers=_entetes(registered_user, organization["id"])
    )
    assert res.status_code == 200, res.text
    assert res.json()["legalRegistrationNumber"] == "RCS-186-XYZ"
    assert res.json()["legalTaxNumber"] == "FR-TVA-186"


async def test_ca5_identifiants_stockes_chiffres_au_repos(organization: dict):
    await _definir_identifiants_legaux(organization["id"], "RCS-186-XYZ", "FR-TVA-186")
    async with AsyncSessionLocal() as db:
        ligne = (
            await db.execute(
                text('SELECT "legalRegistrationNumberChiffre" FROM organization WHERE id = :id'), {"id": uuid.UUID(organization["id"])}
            )
        ).scalar_one()
    assert ligne != "RCS-186-XYZ"
    assert "RCS-186-XYZ" not in ligne


async def test_aucune_route_workspace_en_v1(client: AsyncClient, organization: dict, registered_user: dict):
    """QE-API-05 : pas de workspace en v1."""
    res = await client.get("/api/v1/workspaces", headers=_entetes(registered_user, organization["id"]))
    assert res.status_code == 404
