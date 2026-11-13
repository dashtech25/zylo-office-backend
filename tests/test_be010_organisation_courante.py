"""BE-010 : lecture de l'organisation courante (GET /api/v1/organizations/current).

Tests écrits d'après la définition `### BE-010` de
implementation-backend/tasks-socle-tenant-identite.md, avant le code.

Décisions (CA ou Droits ambigus dans la définition) :
- La ligne Droits écrit « Non-membre : 403 », mais la décision T-010
  (docs/questions/rbac/code-http-acces-interdit.md, appliquée par BE-009) impose
  404 `organization_not_found` pour une organisation hors appartenance, réponse
  uniforme sans énumération. Les tests suivent la décision T-010 (404). Le
  contradiction avec la définition BE-010 est signalée au rapport.
- Permission de lecture : NON DÉFINI (QE-SOC-06). Le test vérifie seulement
  qu'un membre authentifié, sans permission particulière, obtient 200.
- CA-4 : la définition exige une réponse d'erreur structurée au format BE-001
  avec `request_id`. Le fait de provoquer une erreur de lecture passe par un
  remplacement du modèle `Organization` dans le module du routeur, qui fait
  échouer `db.get` après la résolution du contexte.
"""

import uuid

import httpx
import pytest
from httpx import AsyncClient

from app.identity import router as identity_router
from app.main import app
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
URL_COURANTE = "/api/v1/organizations/current"
_SECRET_INTERNE = "NoInspectionAvailable"


def _entetes(session_token: str, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {session_token}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _nouvel_utilisateur(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-010"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    return {"token": login.json()["accessToken"]}


async def _nouvelle_organisation(client: AsyncClient, createur: dict, nom: str) -> dict:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": nom, "slug": f"be010-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(createur["token"]),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_be010_ca1_membre_recoit_l_organisation_active_avec_id_nom_et_statut(client: AsyncClient, registered_user: dict, organization: dict):
    res = await client.get(URL_COURANTE, headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["id"] == organization["id"]
    assert corps["name"] == organization["name"]
    assert corps["status"] == organization["status"]
    assert corps["status"]


async def test_be010_ca2_sans_session_la_route_est_refusee(client: AsyncClient, organization: dict):
    sans_jeton = await client.get(URL_COURANTE, headers={"X-Organization-Id": organization["id"]})
    jeton_invalide = await client.get(
        URL_COURANTE, headers=_entetes("jeton-invalide-be010", organization["id"])
    )

    assert sans_jeton.status_code == 401, sans_jeton.text
    assert jeton_invalide.status_code == 401, jeton_invalide.text
    assert organization["name"] not in sans_jeton.text


async def test_be010_ca3_organisation_d_un_autre_tenant_jamais_retournee_avec_identifiant_force(client: AsyncClient):
    alice = await _nouvel_utilisateur(client)
    org_alice = await _nouvelle_organisation(client, alice, "Org Alice BE-010")
    bob = await _nouvel_utilisateur(client)
    org_bob = await _nouvelle_organisation(client, bob, "Org Bob BE-010")

    # Session d'Alice, sélecteur forcé sur l'organisation de Bob : refus, aucune fuite de son nom.
    selecteur_etranger = await client.get(URL_COURANTE, headers=_entetes(alice["token"], org_bob["id"]))
    assert selecteur_etranger.status_code == 404, selecteur_etranger.text
    assert "Org Bob BE-010" not in selecteur_etranger.text
    assert org_bob["id"] not in selecteur_etranger.text

    # Identifiant de Bob glissé dans la requête (paramètre de requête) : ignoré, l'en-tête reste l'unique sélecteur.
    force = await client.get(
        URL_COURANTE + f"?organizationId={org_bob['id']}&id={org_bob['id']}",
        headers=_entetes(alice["token"], org_alice["id"]),
    )
    assert force.status_code == 200, force.text
    assert force.json()["id"] == org_alice["id"]
    assert "Org Bob BE-010" not in force.text


@pytest.fixture
def client_sans_relance():
    """Client HTTP qui rend les exceptions serveur en réponse 500, comme en production."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def test_be010_ca4_erreur_de_lecture_renvoie_une_erreur_structuree_avec_request_id(
    client_sans_relance: AsyncClient, registered_user: dict, organization: dict, monkeypatch
):
    # Le contexte est résolu (appartenance validée), puis la lecture de l'organisation échoue.
    monkeypatch.setattr(identity_router, "Organization", object)

    async with client_sans_relance as ac:
        res = await ac.get(URL_COURANTE, headers=_entetes(registered_user["accessToken"], organization["id"]))

    assert res.status_code == 500, res.text
    corps = res.json()
    assert set(corps) == {"error", "request_id"}
    assert set(corps["error"]) == {"code", "message", "field_errors", "details"}
    assert corps["error"]["code"] == "internal_error"
    assert corps["request_id"] == res.headers["X-Request-Id"]
    assert _SECRET_INTERNE not in res.text
    assert "Traceback" not in res.text
