"""BE-109 : résumé du portail filtré par permission.

Intention : prouver par des tests les critères d'acceptation de BE-109
(implementation-backend/tasks-portail-organisation.md, section BE-109) :
- CA-1 : un utilisateur avec la seule permission du portail reçoit une réponse sans sections
  billing, usage ni entitlements (test de filtrage) ;
- CA-2 : sans la permission du portail, 403 (test de refus de droit) ;
- CA-3 : organisation hors portée, 404 (test d'isolation tenant) ;
- CA-4 : aucune donnée d'une autre organisation n'apparaît dans la réponse (test d'isolation tenant).

Route testée : GET /api/v1/organizations/{organization_id}/portal-summary.
Écarts (consignés dans docs/portail-organisation/resume-portail.md) : la permission du portail
est `portal.summary.read` (format `domaine.entite.action`, comme BE-108) et non `portal:read` ;
la section membres exige `organization.members.read` (lecture déjà utilisée par BE-106) et non
`members:manage`.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.billing.models import UsageSnapshot
from app.core.database import AsyncSessionLocal, engine
from app.identity.models import OrganizationUser
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission

MOT_DE_PASSE = "TestPassword123!"
PERMISSION_PORTAIL = "portal.summary.read"
SECTIONS = {"entitlements", "usage", "members", "billing"}
VALEUR_AUTRE_ORG = 987654


@pytest.fixture(autouse=True)
async def _pool_propre_a_chaque_test():
    """Chaque test a sa propre boucle asyncio : le pool de connexions est vidé après lui."""
    yield
    await engine.dispose()


def _entete(token: str, organization_id: str) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Organization-Id": organization_id}


def _url(organization_id: str) -> str:
    return f"/api/v1/organizations/{organization_id}/portal-summary"


async def _membre_avec_permissions(client: AsyncClient, organization_id: uuid.UUID, codes: list[str]) -> str:
    """Utilisateur rattaché à l'organisation, porteur d'un rôle qui ne donne que `codes`.

    Retourne son jeton d'accès. Sans code, l'utilisateur n'a aucun rôle.
    """
    membre = await client.post("/api/v1/auth/register", json={
        "email": f"be109-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Membre BE-109",
    })
    login = await client.post("/api/v1/auth/login", json={"email": membre.json()["email"], "password": MOT_DE_PASSE})
    utilisateur_id = uuid.UUID(membre.json()["id"])
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=organization_id, userId=utilisateur_id))
        if codes:
            role = Role(organizationId=organization_id, code=f"be109-{uuid.uuid4().hex[:8]}", name="Rôle de test BE-109")
            db.add(role)
            await db.flush()
            for code in codes:
                permission = await get_or_create_permission(db, code, "portal", "Permission de test BE-109")
                db.add(RolePermission(roleId=role.id, permissionId=permission.id))
            db.add(UserRole(userId=utilisateur_id, organizationId=organization_id, roleId=role.id))
        await db.commit()
    return login.json()["accessToken"]


async def _snapshot_usage(organization_id: uuid.UUID, sites_actifs: int) -> None:
    """Snapshot d'usage publié pour une organisation (la valeur sert de marqueur dans les réponses)."""
    async with AsyncSessionLocal() as db:
        db.add(UsageSnapshot(
            organizationId=organization_id,
            measuredAt=datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc),
            granularity="mensuelle",
            aggregates={"sitesActifs": sites_actifs},
            limits={"sitesMax": 5},
        ))
        await db.commit()


async def _organisation_etrangere(client: AsyncClient) -> dict:
    """Organisation d'un autre utilisateur, hors de portée de l'utilisateur de test."""
    autre = await client.post("/api/v1/auth/register", json={
        "email": f"be109-b-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com",
        "password": MOT_DE_PASSE, "fullName": "Autre BE-109",
    })
    login = await client.post("/api/v1/auth/login", json={"email": autre.json()["email"], "password": MOT_DE_PASSE})
    res = await client.post(
        "/api/v1/organizations", json={"name": "Org B BE-109", "slug": f"be109-b-{uuid.uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {login.json()['accessToken']}"},
    )
    return res.json()


async def test_be109_ca1_portail_seul_ne_recoit_aucune_section_protegee(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 : avec `portal.summary.read` seul, la réponse ne contient ni billing, ni usage, ni entitlements."""
    org_id = uuid.UUID(organization["id"])
    jeton = await _membre_avec_permissions(client, org_id, [PERMISSION_PORTAIL])

    reponse = await client.get(_url(organization["id"]), headers=_entete(jeton, organization["id"]))

    assert reponse.status_code == 200, reponse.text
    corps = reponse.json()
    assert not ({"billing", "usage", "entitlements", "members"} & set(corps.keys())), corps


async def test_be109_ca1_proprietaire_recoit_les_quatre_sections(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-1 (contrepartie) : le propriétaire, qui détient toutes les permissions de lecture, reçoit les quatre sections."""
    await _snapshot_usage(uuid.UUID(organization["id"]), 3)

    reponse = await client.get(
        _url(organization["id"]), headers=_entete(registered_user["accessToken"], organization["id"])
    )

    assert reponse.status_code == 200, reponse.text
    assert set(reponse.json().keys()) == SECTIONS


async def test_be109_ca2_sans_permission_portail_retourne_403(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-2 : sans `portal.summary.read`, 403 `permission_denied`, même si d'autres lectures sont accordées."""
    org_id = uuid.UUID(organization["id"])
    jeton = await _membre_avec_permissions(client, org_id, ["organization.usage.read"])

    reponse = await client.get(_url(organization["id"]), headers=_entete(jeton, organization["id"]))

    assert reponse.status_code == 403, reponse.text
    assert reponse.json()["error"]["code"] == "permission_denied"


async def test_be109_ca3_organisation_hors_portee_retourne_404(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-3 : une organisation dont l'utilisateur n'est pas membre donne 404 `organization_not_found`."""
    autre = await _organisation_etrangere(client)

    reponse = await client.get(
        _url(autre["id"]), headers=_entete(registered_user["accessToken"], organization["id"])
    )

    assert reponse.status_code == 404, reponse.text
    assert reponse.json()["error"]["code"] == "organization_not_found"


async def test_be109_ca4_aucune_donnee_d_une_autre_organisation(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-4 : la réponse de l'organisation A ne contient ni l'identifiant de B ni le snapshot de B."""
    autre = await _organisation_etrangere(client)
    await _snapshot_usage(uuid.UUID(autre["id"]), VALEUR_AUTRE_ORG)
    await _snapshot_usage(uuid.UUID(organization["id"]), 3)

    reponse = await client.get(
        _url(organization["id"]), headers=_entete(registered_user["accessToken"], organization["id"])
    )

    assert reponse.status_code == 200, reponse.text
    assert autre["id"] not in reponse.text
    assert str(VALEUR_AUTRE_ORG) not in reponse.text
