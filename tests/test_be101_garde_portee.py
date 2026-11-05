"""BE-101 : garde de portée organisation et autorisation par défaut.

Tests écrits d'après la définition `### BE-101` de
implementation-backend/tasks-portail-organisation.md, avant le code.

Périmètre : CA-1 (sans session, 401), CA-2 (organisation étrangère et
organisation inexistante : même réponse 404), CA-3 (membre sans permission : 403),
CA-4 (action absente de la politique : refus par défaut), CA-5 (organisation
désignée dans l'en-tête ou le corps : la portée reste celle du chemin).

Décisions :
- La route `GET /api/v1/organizations/{organization_id}/portal-summary` (BE-109)
  n'existe pas encore. Les tests utilisent une application FastAPI de test, avec des
  routes de test sous le même préfixe, qui ne sont pas montées sur l'application réelle.
- CA-3 demande de tester chaque permission listée dans les autres tâches. Ces tâches
  n'existent pas encore : le test couvre la permission d'une action de la politique
  fournie par le test (`identity.organization.settings.update`, accordée au propriétaire).
  Les permissions du portail s'ajouteront avec BE-102 et suivantes (écart consigné).
"""

import inspect
import uuid

import pytest
from fastapi import APIRouter, Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.core.errors import register_exception_handlers
from app.identity.models import OrganizationUser
from app.identity.permissions import ORGANIZATION_SETTINGS_UPDATE

MOT_DE_PASSE = "TestPassword123!"
ACTION_TEST = "test.reglages.modifier"
POLITIQUE_TEST = {ACTION_TEST: ORGANIZATION_SETTINGS_UPDATE}


def _application_de_test() -> FastAPI:
    """Application de test : routes sous le préfixe du portail, politique de test explicite."""
    from app.rbac.portee_organisation import OrgScope, exiger_action, require_org_scope

    application = FastAPI()
    register_exception_handlers(application)
    routeur = APIRouter(prefix="/api/v1/organizations/{organization_id}")

    @routeur.get("/portee-test")
    async def portee_test(scope: OrgScope = Depends(require_org_scope)):
        return {"organizationId": str(scope.organization_id)}

    @routeur.post("/portee-test")
    async def portee_test_corps(scope: OrgScope = Depends(require_org_scope)):
        return {"organizationId": str(scope.organization_id)}

    @routeur.get("/action-test", dependencies=[Depends(exiger_action(ACTION_TEST, politique=POLITIQUE_TEST))])
    async def action_test():
        return {"ok": True}

    @routeur.get(
        "/action-inconnue",
        dependencies=[Depends(exiger_action("test.inconnue.lire", politique=POLITIQUE_TEST))],
    )
    async def action_inconnue():
        return {"ok": True}

    application.include_router(routeur)
    return application


@pytest.fixture
async def portee_client(client: AsyncClient):
    """Client de l'application de test. Dépend de `client` pour les seeds et le pool neuf."""
    transport = ASGITransport(app=_application_de_test())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: AsyncClient) -> dict:
    email = f"test-{uuid.uuid4().hex[:12]}@zylo-office-test.example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-101"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: AsyncClient, proprietaire: dict, nom: str = "Org BE-101") -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be101-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre(organisation_id: str, utilisateur_id: str) -> None:
    """Appartenance sans rôle : insertion directe, comme dans tests/test_be009_garde_contexte.py."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


async def test_be101_fonctions_de_la_garde_exposees_et_documentees():
    from app.rbac import portee_organisation

    assert portee_organisation.__doc__, "doc de module de app/rbac/portee_organisation.py absente"
    for nom in ("require_org_scope", "evaluer_politique_portail", "exiger_action"):
        fonction = getattr(portee_organisation, nom)
        assert inspect.getdoc(fonction), f"{nom} sans docstring"


async def test_be101_ca1_requete_sans_session_refusee_401(portee_client: AsyncClient, client: AsyncClient):
    proprietaire = await _creer_utilisateur(client)
    organisation_id = await _creer_organisation(client, proprietaire)

    res = await portee_client.get(f"/api/v1/organizations/{organisation_id}/portee-test")

    assert res.status_code == 401, res.text


async def test_be101_ca2_organisation_etrangere_et_inexistante_donnent_la_meme_reponse_404(
    portee_client: AsyncClient, client: AsyncClient
):
    acteur = await _creer_utilisateur(client)
    await _creer_organisation(client, acteur, "Org A de l'acteur")
    autre = await _creer_utilisateur(client)
    organisation_b = await _creer_organisation(client, autre, "Org B étrangère")

    etrangere = await portee_client.get(f"/api/v1/organizations/{organisation_b}/portee-test", headers=_entetes(acteur))
    inexistante = await portee_client.get(
        f"/api/v1/organizations/{uuid.uuid4()}/portee-test", headers=_entetes(acteur)
    )
    mal_formee = await portee_client.get("/api/v1/organizations/pas-un-uuid/portee-test", headers=_entetes(acteur))

    assert etrangere.status_code == 404, etrangere.text
    assert etrangere.json()["error"]["code"] == "organization_not_found"
    assert etrangere.json() == inexistante.json() == mal_formee.json()
    assert mal_formee.status_code == 404, mal_formee.text


async def test_be101_ca3_membre_sans_permission_refuse_403_et_proprietaire_accepte(
    portee_client: AsyncClient, client: AsyncClient
):
    proprietaire = await _creer_utilisateur(client)
    organisation_id = await _creer_organisation(client, proprietaire)
    membre = await _creer_utilisateur(client)
    await _ajouter_membre(organisation_id, membre["id"])

    sans_droit = await portee_client.get(
        f"/api/v1/organizations/{organisation_id}/action-test", headers=_entetes(membre)
    )
    avec_droit = await portee_client.get(
        f"/api/v1/organizations/{organisation_id}/action-test", headers=_entetes(proprietaire)
    )

    assert sans_droit.status_code == 403, sans_droit.text
    assert sans_droit.json()["error"]["code"] == "permission_denied"
    assert avec_droit.status_code == 200, avec_droit.text


async def test_be101_ca4_action_absente_de_la_politique_refusee_par_defaut(
    portee_client: AsyncClient, client: AsyncClient
):
    proprietaire = await _creer_utilisateur(client)
    organisation_id = await _creer_organisation(client, proprietaire)

    res = await portee_client.get(
        f"/api/v1/organizations/{organisation_id}/action-inconnue", headers=_entetes(proprietaire)
    )

    assert res.status_code == 403, res.text
    assert res.json()["error"]["code"] == "policy_denied"


async def test_be101_ca5_organisation_designee_dans_l_entete_ou_le_corps_ne_change_pas_la_portee(
    portee_client: AsyncClient, client: AsyncClient
):
    proprietaire_a = await _creer_utilisateur(client)
    organisation_a = await _creer_organisation(client, proprietaire_a, "Org A")
    proprietaire_b = await _creer_utilisateur(client)
    organisation_b = await _creer_organisation(client, proprietaire_b, "Org B")

    par_entete = await portee_client.get(
        f"/api/v1/organizations/{organisation_a}/portee-test", headers=_entetes(proprietaire_a, organisation_b)
    )
    par_corps = await portee_client.post(
        f"/api/v1/organizations/{organisation_a}/portee-test",
        json={"organizationId": organisation_b},
        headers=_entetes(proprietaire_a),
    )

    assert par_entete.status_code == 200, par_entete.text
    assert par_entete.json()["organizationId"] == organisation_a
    assert par_corps.status_code == 200, par_corps.text
    assert par_corps.json()["organizationId"] == organisation_a
