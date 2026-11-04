"""Contexte tenant serveur et validation des identifiants (BE-225).

Intention : le tenant d'une requête est résolu côté serveur depuis l'adhésion
active de l'utilisateur, jamais depuis une valeur fournie par le navigateur
(en-tête `X-Organization-Id`, identifiant de chemin, champ du corps).

Critères testés :
- CA-1 : un tenantId sans adhésion active répond 404 uniforme (test de refus) ;
- CA-2 : le tenant cité dans le corps est revalidé contre le contexte serveur
  (le corps cite B alors que le contexte est A) ;
- CA-3 : isolation tenant bidirectionnelle par identifiant direct ;
- CA-4 : le contexte est invalidé après retrait d'adhésion (test de révocation).
"""

import uuid

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.tenant_context import TenantContext, get_tenant_context, valider_tenant_du_corps
from app.identity.models import OrganizationUser
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur test"}
    )
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Le socle n'expose pas encore d'ajout de membre (IAM-006) : insertion
    directe, comme dans les autres tests d'isolation."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def _retirer_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Retrait d'adhésion (CA-4) : suppression directe de la ligne d'appartenance."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(OrganizationUser).where(
                OrganizationUser.organizationId == uuid.UUID(organisation_id),
                OrganizationUser.userId == uuid.UUID(utilisateur_id),
            )
        )
        await db.commit()


async def _id_role_proprietaire(client: AsyncClient, proprietaire: dict, organisation_id: str) -> str:
    res = await client.get(
        f"/api/v1/rbac/organizations/{organisation_id}/roles",
        headers=_entetes(proprietaire, organisation_id),
    )
    assert res.status_code == 200, res.text
    return next(r["id"] for r in res.json() if r["code"] == "owner")


class CorpsAvecTenant(BaseModel):
    organizationId: uuid.UUID | None = None


def _application_de_test(application_reelle: FastAPI) -> FastAPI:
    """Mini-application portant une route tenant qui reçoit un tenant dans son
    corps. Aucune route de production n'accepte aujourd'hui un tel champ : cette
    route de test isole la revalidation (CA-2) sans toucher à l'API publique ni
    à l'inventaire des routes. Les gestionnaires d'erreurs de l'application
    réelle sont repris pour que les `AppError` produisent les mêmes réponses."""
    application = FastAPI()
    application.exception_handlers.update(application_reelle.exception_handlers)

    @application.post("/tenant-corps")
    async def route_avec_tenant_dans_corps(
        corps: CorpsAvecTenant,
        contexte: TenantContext = Depends(get_tenant_context),
    ) -> dict:
        valider_tenant_du_corps(contexte, corps.organizationId)
        return {"organizationId": str(contexte.organization_id)}

    return application


@pytest.fixture
async def acteurs(client: AsyncClient) -> dict:
    """A : `admin_a` est propriétaire de A. B : `owner_b` est propriétaire de B.
    `intrus` n'appartient à aucune des deux organisations."""
    admin_a = await _creer_utilisateur(client)
    org_a = await _creer_organisation(client, admin_a)
    owner_b = await _creer_utilisateur(client)
    org_b = await _creer_organisation(client, owner_b)
    intrus = await _creer_utilisateur(client)
    return {
        "admin_a": admin_a,
        "org_a": org_a,
        "owner_b": owner_b,
        "org_b": org_b,
        "intrus": intrus,
    }


# ---------------------------------------------------------------------------
# CA-1 : tenantId sans adhésion active -> 404 uniforme
# ---------------------------------------------------------------------------


async def test_ca1_tenant_sans_adhesion_active_repond_404(client: AsyncClient, acteurs: dict) -> None:
    """Un utilisateur sans adhésion à A qui présente A comme tenant reçoit 404
    `organization_not_found`, sur une route à chemin et sur une route à en-tête seul."""
    org_a = acteurs["org_a"]
    chemin = await client.get(
        f"/api/v1/rbac/organizations/{org_a}/roles",
        headers=_entetes(acteurs["intrus"], org_a),
    )
    entete_seul = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(acteurs["intrus"], org_a),
    )
    for res in (chemin, entete_seul):
        assert res.status_code == 404, res.text
        assert res.json()["error"]["code"] == "organization_not_found"


async def test_ca1_tenant_inexistant_et_interdit_repondent_identiquement(client: AsyncClient, acteurs: dict) -> None:
    """Une organisation inexistante et une organisation sans adhésion donnent la
    même réponse : aucune énumération de tenants possible."""
    org_a = acteurs["org_a"]
    interdit = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(acteurs["intrus"], org_a),
    )
    inexistant = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(acteurs["intrus"], str(uuid.uuid4())),
    )
    assert interdit.status_code == inexistant.status_code == 404
    assert interdit.json()["error"] == inexistant.json()["error"]


# ---------------------------------------------------------------------------
# CA-2 : tenant du corps revalidé contre le contexte
# ---------------------------------------------------------------------------


async def test_ca2_corps_citant_un_autre_tenant_est_refuse(client: AsyncClient, acteurs: dict) -> None:
    """Le contexte est A (en-tête) mais le corps cite B : refus 404, aucune
    exécution de la route au nom de B."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=_application_de_test(app)), base_url="http://test") as ac:
        res = await ac.post(
            "/tenant-corps",
            json={"organizationId": acteurs["org_b"]},
            headers=_entetes(acteurs["admin_a"], acteurs["org_a"]),
        )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "organization_not_found"


async def test_ca2_corps_citant_le_meme_tenant_est_accepte(client: AsyncClient, acteurs: dict) -> None:
    """Témoin positif : un corps qui cite le tenant du contexte, ou n'en cite
    aucun, passe la revalidation."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=_application_de_test(app)), base_url="http://test") as ac:
        identique = await ac.post(
            "/tenant-corps",
            json={"organizationId": acteurs["org_a"]},
            headers=_entetes(acteurs["admin_a"], acteurs["org_a"]),
        )
        absent = await ac.post(
            "/tenant-corps",
            json={},
            headers=_entetes(acteurs["admin_a"], acteurs["org_a"]),
        )
    assert identique.status_code == 200, identique.text
    assert absent.status_code == 200, absent.text
    assert identique.json()["organizationId"] == acteurs["org_a"]


# ---------------------------------------------------------------------------
# CA-3 : isolation tenant bidirectionnelle par identifiant direct
# ---------------------------------------------------------------------------


async def test_ca3_isolation_bidirectionnelle_par_identifiant_direct(client: AsyncClient, acteurs: dict) -> None:
    """Un utilisateur de A ne lit jamais un rôle de B, et réciproquement, qu'il
    passe l'identifiant de l'autre organisation dans le chemin, dans l'en-tête,
    ou les deux à la fois."""
    role_b = await _id_role_proprietaire(client, acteurs["owner_b"], acteurs["org_b"])
    role_a = await _id_role_proprietaire(client, acteurs["admin_a"], acteurs["org_a"])

    tentatives = [
        # A lit le rôle de B
        (acteurs["admin_a"], acteurs["org_a"], acteurs["org_a"], role_b),
        (acteurs["admin_a"], acteurs["org_b"], acteurs["org_b"], role_b),
        (acteurs["admin_a"], acteurs["org_b"], acteurs["org_a"], role_b),
        # B lit le rôle de A
        (acteurs["owner_b"], acteurs["org_b"], acteurs["org_b"], role_a),
        (acteurs["owner_b"], acteurs["org_a"], acteurs["org_a"], role_a),
        (acteurs["owner_b"], acteurs["org_a"], acteurs["org_b"], role_a),
    ]
    for utilisateur, chemin_org, entete_org, role_id in tentatives:
        res = await client.get(
            f"/api/v1/rbac/organizations/{chemin_org}/roles/{role_id}",
            headers=_entetes(utilisateur, entete_org),
        )
        assert res.status_code == 404, (chemin_org, entete_org, res.text)
        assert "owner" not in res.text


async def test_ca3_membre_de_b_ne_lit_pas_les_membres_de_a(client: AsyncClient, acteurs: dict) -> None:
    """Le chemin ne suffit pas : un utilisateur de B qui demande les membres de A
    avec l'en-tête de B est refusé (incohérence chemin/en-tête)."""
    res = await client.get(
        f"/api/v1/rbac/organizations/{acteurs['org_a']}/members",
        headers=_entetes(acteurs["owner_b"], acteurs["org_b"]),
    )
    assert res.status_code == 404, res.text
    assert res.json()["error"]["code"] == "organization_not_found"


# ---------------------------------------------------------------------------
# CA-4 : contexte invalidé après retrait d'adhésion
# ---------------------------------------------------------------------------


async def test_ca4_retrait_d_adhesion_revoque_le_contexte(client: AsyncClient, acteurs: dict) -> None:
    """Un membre de A accède à A ; après retrait de son adhésion, la même requête
    avec le même jeton reçoit 404, y compris sur la route de test qui résout le
    contexte tenant. Aucun cache : chaque requête relit l'adhésion active."""
    from app.main import app

    membre = await _creer_utilisateur(client)
    await _ajouter_membre(acteurs["org_a"], membre["id"])

    avant = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(membre, acteurs["org_a"]),
    )
    assert avant.status_code == 200, avant.text

    await _retirer_membre(acteurs["org_a"], membre["id"])

    apres = await client.get(
        "/api/v1/organizations/current",
        headers=_entetes(membre, acteurs["org_a"]),
    )
    assert apres.status_code == 404, apres.text
    assert apres.json()["error"]["code"] == "organization_not_found"

    async with AsyncClient(transport=ASGITransport(app=_application_de_test(app)), base_url="http://test") as ac:
        corps = await ac.post(
            "/tenant-corps",
            json={},
            headers=_entetes(membre, acteurs["org_a"]),
        )
    assert corps.status_code == 404, corps.text
