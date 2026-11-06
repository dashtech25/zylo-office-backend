"""BE-102 : création d'organisation (POST /api/v1/organizations).

Tests écrits d'après la définition `### BE-102` de
implementation-backend/tasks-portail-organisation.md, avant le code.

Périmètre : CA-1 (création valide : 201, organisation et tenant, aucun rôle
Owner), CA-2 (doublon même nom normalisé et même créateur : 409, sans ligne
créée), CA-3 (401 sans session, 403 sans `org:create`), CA-4 (un champ `owner`
dans le corps ne crée aucun rôle Owner). Décision QE-POR-04 : aucun rôle Owner
à la création.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.identity import permissions as permissions_identite
from app.identity.models import Organization, OrganizationUser, Tenant, User
from app.rbac.models import Role, UserRole

ROUTE = "/api/v1/organizations"
MOT_DE_PASSE = "TestPassword123!"


def _entetes(jeton: str) -> dict:
    return {"Authorization": f"Bearer {jeton}"}


def _slug() -> str:
    return f"be102-{uuid.uuid4().hex[:10]}"


async def _inscrit(client: AsyncClient) -> tuple[str, str]:
    """Inscrit un utilisateur, le connecte et renvoie (jeton d'accès, identifiant)."""
    email = f"be102-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE-102"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    async with AsyncSessionLocal() as db:
        utilisateur = (await db.execute(select(User).where(User.email == email))).scalar_one()
        return login.json()["accessToken"], str(utilisateur.id)


async def _roles_attribues(organization_id: str) -> list[str]:
    """Codes de tous les rôles attribués à un membre de l'organisation (vide si aucun)."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(
            select(Role.code)
            .join(UserRole, UserRole.roleId == Role.id)
            .where(UserRole.organizationId == uuid.UUID(organization_id))
        )
        return list(res.scalars().all())


async def _nombre_organisations(nom_exact: str) -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(func.count()).select_from(Organization).where(Organization.name == nom_exact))
        return res.scalar_one()


async def test_ca1_creation_valide_cree_organisation_tenant_sans_role_owner(client: AsyncClient):
    jeton, createur_id = await _inscrit(client)
    nom = f"Org BE-102 CA1 {uuid.uuid4().hex[:8]}"

    res = await client.post(ROUTE, json={"name": nom, "slug": _slug()}, headers=_entetes(jeton))

    assert res.status_code == 201, res.text
    organization_id = res.json()["id"]
    async with AsyncSessionLocal() as db:
        organisation = await db.get(Organization, uuid.UUID(organization_id))
        assert organisation is not None
        assert organisation.tenantId is not None
        assert await db.get(Tenant, organisation.tenantId) is not None
        appartenance = (
            await db.execute(
                select(OrganizationUser).where(
                    OrganizationUser.organizationId == uuid.UUID(organization_id),
                    OrganizationUser.userId == uuid.UUID(createur_id),
                )
            )
        ).scalar_one_or_none()
    assert appartenance is not None, "le créateur doit être membre de l'organisation"
    assert await _roles_attribues(organization_id) == [], "aucun rôle, et donc aucun Owner, à la création"


async def test_ca2_doublon_meme_nom_normalise_meme_createur_refuse_409(client: AsyncClient):
    jeton, _ = await _inscrit(client)
    nom_initial = f"Transports Dupont {uuid.uuid4().hex[:6]}"
    premier = await client.post(ROUTE, json={"name": nom_initial, "slug": _slug()}, headers=_entetes(jeton))
    assert premier.status_code == 201, premier.text

    # Même nom après normalisation (casse, espaces de bord, espaces multiples) : doublon.
    variante = "  " + nom_initial.upper().replace(" ", "   ") + "  "
    second = await client.post(ROUTE, json={"name": variante, "slug": _slug()}, headers=_entetes(jeton))

    assert second.status_code == 409, second.text
    assert await _nombre_organisations(nom_initial) == 1
    assert await _nombre_organisations(variante) == 0


async def test_ca2_meme_nom_autre_createur_accepte(client: AsyncClient):
    jeton_a, _ = await _inscrit(client)
    jeton_b, _ = await _inscrit(client)
    nom = f"Nom partagé BE-102 {uuid.uuid4().hex[:6]}"
    premier = await client.post(ROUTE, json={"name": nom, "slug": _slug()}, headers=_entetes(jeton_a))
    assert premier.status_code == 201, premier.text

    autre = await client.post(ROUTE, json={"name": nom, "slug": _slug()}, headers=_entetes(jeton_b))

    assert autre.status_code == 201, autre.text


async def test_ca3_sans_session_retourne_401(client: AsyncClient):
    res = await client.post(ROUTE, json={"name": "Sans session BE-102", "slug": _slug()})

    assert res.status_code == 401, res.text


async def test_ca3_sans_org_create_retourne_403(client: AsyncClient, monkeypatch):
    jeton, _ = await _inscrit(client)
    nom = f"Sans droit BE-102 {uuid.uuid4().hex[:6]}"
    # Utilisateur authentifié qui ne détient pas `org:create` : la garde doit refuser.
    monkeypatch.setattr(permissions_identite, "permissions_globales", lambda utilisateur: frozenset())

    res = await client.post(ROUTE, json={"name": nom, "slug": _slug()}, headers=_entetes(jeton))

    assert res.status_code == 403, res.text
    assert await _nombre_organisations(nom) == 0


async def test_ca4_champ_owner_dans_le_corps_ne_cree_aucun_membership_owner(client: AsyncClient):
    jeton, _ = await _inscrit(client)
    _, autre_id = await _inscrit(client)
    nom = f"Champ owner BE-102 {uuid.uuid4().hex[:6]}"

    res = await client.post(
        ROUTE,
        json={
            "name": nom,
            "slug": _slug(),
            "owner": autre_id,
            "ownerUserId": autre_id,
            "roles": ["owner"],
        },
        headers=_entetes(jeton),
    )

    assert res.status_code == 201, res.text
    organization_id = res.json()["id"]
    assert await _roles_attribues(organization_id) == [], "le corps ne doit attribuer aucun rôle"
    async with AsyncSessionLocal() as db:
        appartenance_autre = (
            await db.execute(
                select(OrganizationUser).where(
                    OrganizationUser.organizationId == uuid.UUID(organization_id),
                    OrganizationUser.userId == uuid.UUID(autre_id),
                )
            )
        ).scalar_one_or_none()
    assert appartenance_autre is None, "le champ owner ne doit ajouter aucun membre"
