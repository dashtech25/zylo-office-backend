"""BE-008 : modèle RBAC (rôles, permissions, grants, affectations scopées).

Couvre les critères d'acceptation de la définition BE-008
(implementation-backend/tasks-socle-tenant-identite.md) :
- CA-1 : une affectation de rôle avec portée ressource ne s'applique qu'à la
  ressource indiquée ;
- CA-2 (refus) : un utilisateur sans rôle sur une ressource est refusé (403) ;
- CA-3 : un grant `deny` l'emporte sur un `allow` pour la même permission ;
- CA-4 (isolation) : un rôle défini pour O1 n'est pas applicable à O2.

Les tests passent par le moteur de résolution (`app/rbac/service.py`) et,
pour CA-2, par un endpoint HTTP réel exigeant une permission d'organisation.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import OrganizationUser, User
from app.identity.schemas import CreateOrganizationRequest
from app.identity.service import create_organization
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import assign_role, create_grant, get_or_create_permission, user_has_permission

# Permission de test, hors de tout module réel : le moteur ne l'interprète pas.
PERMISSION_TEST = "be008.dossier.lire"


async def _utilisateur(db, label: str) -> User:
    user = User(email=f"be008-{label}-{uuid.uuid4().hex[:8]}@example.com", hashedPassword=hash_password("x"), fullName=label)
    db.add(user)
    await db.flush()
    return user


async def _organisation(db, owner: User, label: str):
    return await create_organization(
        db, owner, CreateOrganizationRequest(name=f"BE008 {label}", slug=f"be008-{label}-{uuid.uuid4().hex[:8]}")
    )


async def _membre(db, organization_id: uuid.UUID, user: User) -> None:
    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    await db.flush()


async def _role_avec_permission(db, organization_id: uuid.UUID, code: str) -> Role:
    permission = await get_or_create_permission(db, PERMISSION_TEST, "be008", "Permission de test BE-008")
    role = Role(organizationId=organization_id, code=code, name=f"Rôle {code}")
    db.add(role)
    await db.flush()
    db.add(RolePermission(roleId=role.id, permissionId=permission.id))
    await db.flush()
    return role


async def _donner_permission_au_proprietaire(db, organization_id: uuid.UUID, owner: User) -> None:
    """Le propriétaire détient la permission de test (il peut ainsi accorder un rôle qui la contient)."""
    permission = await get_or_create_permission(db, PERMISSION_TEST, "be008", "Permission de test BE-008")
    owner_role = (
        await db.execute(
            select(Role).join(UserRole, UserRole.roleId == Role.id).where(
                UserRole.userId == owner.id, UserRole.organizationId == organization_id, Role.code == "owner"
            )
        )
    ).scalar_one()
    db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
    await db.flush()


async def test_ca1_affectation_scopee_ne_s_applique_qu_a_la_ressource(client: AsyncClient):
    """CA-1 : un rôle attribué avec portée (station, A) ne donne la permission
    que sur A ; ni sur une autre station B, ni à portée organisation entière."""
    station_a, station_b = uuid.uuid4(), uuid.uuid4()
    async with AsyncSessionLocal() as db:
        owner = await _utilisateur(db, "owner-ca1")
        org = await _organisation(db, owner, "ca1")
        cible = await _utilisateur(db, "cible-ca1")
        await _membre(db, org.id, cible)
        await _donner_permission_au_proprietaire(db, org.id, owner)
        role = await _role_avec_permission(db, org.id, "gerant_ca1")
        await assign_role(db, org.id, owner.id, cible.id, role.id, "station", station_a)
        await db.commit()

        assert await user_has_permission(db, cible.id, org.id, PERMISSION_TEST, "station", station_a) is True
        assert await user_has_permission(db, cible.id, org.id, PERMISSION_TEST, "station", station_b) is False
        assert await user_has_permission(db, cible.id, org.id, PERMISSION_TEST) is False


async def test_ca2_utilisateur_sans_role_sur_la_ressource_est_refuse_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : membre de l'organisation sans aucun rôle, appelant un endpoint
    protégé par permission d'organisation -> 403 (permission_denied)."""
    email = f"be008-sans-role-{uuid.uuid4().hex[:8]}@example.com"
    password = "TestPassword123!"
    await client.post("/api/v1/auth/register", json={"email": email, "password": password, "fullName": "Sans rôle"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    token = login.json()["accessToken"]

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one()
        await _membre(db, uuid.UUID(organization["id"]), user)
        await db.commit()
        assert await user_has_permission(db, user.id, uuid.UUID(organization["id"]), PERMISSION_TEST, "station", uuid.uuid4()) is False

    headers = {"Authorization": f"Bearer {token}", "X-Organization-Id": organization["id"]}
    res = await client.get(f"/api/v1/organizations/{organization['id']}/protected-demo", headers=headers)
    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "permission_denied"


async def test_ca3_grant_deny_l_emporte_sur_allow_du_role(client: AsyncClient):
    """CA-3 : un utilisateur qui obtient la permission par son rôle la perd
    dès qu'un grant `deny` existe pour la même permission (même portée)."""
    async with AsyncSessionLocal() as db:
        owner = await _utilisateur(db, "owner-ca3")
        org = await _organisation(db, owner, "ca3")
        cible = await _utilisateur(db, "cible-ca3")
        await _membre(db, org.id, cible)
        await _donner_permission_au_proprietaire(db, org.id, owner)
        role = await _role_avec_permission(db, org.id, "lecteur_ca3")
        await assign_role(db, org.id, owner.id, cible.id, role.id)
        await db.commit()

        assert await user_has_permission(db, cible.id, org.id, PERMISSION_TEST) is True

        await create_grant(db, org.id, owner.id, cible.id, PERMISSION_TEST, "deny")
        await db.commit()

        assert await user_has_permission(db, cible.id, org.id, PERMISSION_TEST) is False


async def test_ca4_role_de_l_organisation_1_refuse_dans_l_organisation_2(client: AsyncClient):
    """CA-4 : un rôle défini pour O1 ne peut pas être affecté dans O2 (refus
    role_not_found, 404), et ne donne aucun droit à un membre de O2."""
    async with AsyncSessionLocal() as db:
        owner_1 = await _utilisateur(db, "owner-ca4a")
        org_1 = await _organisation(db, owner_1, "ca4a")
        owner_2 = await _utilisateur(db, "owner-ca4b")
        org_2 = await _organisation(db, owner_2, "ca4b")
        membre_2 = await _utilisateur(db, "membre-ca4b")
        await _membre(db, org_2.id, membre_2)
        await _donner_permission_au_proprietaire(db, org_1.id, owner_1)
        role_o1 = await _role_avec_permission(db, org_1.id, "gerant_ca4")
        await db.commit()

        with pytest.raises(AppError) as erreur:
            await assign_role(db, org_2.id, owner_2.id, membre_2.id, role_o1.id)
        assert erreur.value.status_code == 404
        await db.rollback()

        affectations = (
            await db.execute(select(UserRole).where(UserRole.userId == membre_2.id, UserRole.organizationId == org_2.id))
        ).scalars().all()
        assert affectations == []
        assert await user_has_permission(db, membre_2.id, org_2.id, PERMISSION_TEST) is False
