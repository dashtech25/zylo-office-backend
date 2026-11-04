"""Enveloppe d'erreur homogène et request_id (BE-220).

BE-220 ne redéfinit pas l'enveloppe : elle est celle de BE-001
(`{"error": {"code", "message", "field_errors", "details"}, "request_id"}`,
format de `app/core/errors.py`). Ces tests vérifient que cette enveloppe
s'applique à toutes les routes, y compris les refus d'accès réels :

- CA-1 : une erreur 422, 403 et 500 suit l'enveloppe complète ;
- CA-2 : le `request_id` du corps égale `X-Request-Id`, et un `X-Request-Id`
  client valide est réutilisé ;
- CA-3 : une erreur 500 ne contient ni trace ni secret interne ;
- CA-4 : une erreur de validation décrit chaque champ invalide (`loc` et
  `type` dans `details`) ;
- CA-5 : un accès hors organisation renvoie le même corps qu'une ressource
  inexistante (pas de fuite d'existence).
"""

import logging
import uuid

import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.main import app
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
_SECRET_INTERNE = "secret-interne-be220-41c9"
_PREFIXE_ROUTES_TEST = "/api/v1/_test_be220"


class _Formulaire(BaseModel):
    """Formulaire témoin à deux champs, pour le cas CA-4."""

    prenom: str
    age: int


_routes_test = APIRouter()


@_routes_test.post("/_test_be220/formulaire")
def _route_formulaire(formulaire: _Formulaire) -> dict:
    return {"ok": True}


@_routes_test.get("/_test_be220/boom")
def _route_qui_leve() -> None:
    raise RuntimeError(_SECRET_INTERNE)


@pytest.fixture
def routes_de_test():
    """Monte les routes témoins sur l'application réelle, puis les retire."""
    app.include_router(_routes_test, prefix="/api/v1")
    try:
        yield
    finally:
        app.router.routes = [
            route for route in app.router.routes if not getattr(route, "path", "").startswith(_PREFIXE_ROUTES_TEST)
        ]


@pytest.fixture
def client_sans_relance():
    """Client sur l'application réelle : un 500 arrive comme une réponse HTTP."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes(utilisateur: dict, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {utilisateur['token']}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: httpx.AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-220"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "token": token}


async def _creer_organisation(client: httpx.AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre_sans_droit(organisation_id: str, utilisateur_id: str) -> None:
    """Appartenance directe en base : le socle n'expose pas encore d'ajout de membre (IAM-006)."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


def _verifie_enveloppe_complete(corps: dict, en_tete_request_id: str) -> None:
    """Forme commune de toute erreur (CA-1) et égalité du request ID (CA-2)."""
    assert set(corps) == {"error", "request_id"}
    erreur = corps["error"]
    assert set(erreur) == {"code", "message", "field_errors", "details"}
    assert isinstance(erreur["code"], str) and erreur["code"]
    assert isinstance(erreur["message"], str) and erreur["message"]
    assert isinstance(erreur["field_errors"], dict)
    assert isinstance(erreur["details"], list)
    assert corps["request_id"] == en_tete_request_id
    assert corps["request_id"]


async def test_erreur_422_suit_l_enveloppe_complete(client_sans_relance, routes_de_test):
    async with client_sans_relance as client:
        reponse = await client.post("/api/v1/_test_be220/formulaire", json={"prenom": "A"})

    assert reponse.status_code == 422
    corps = reponse.json()
    _verifie_enveloppe_complete(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "validation_error"


async def test_erreur_403_suit_l_enveloppe_complete(client_sans_relance, test_city):
    """Refus de permission réel : membre sans droit, route de station."""
    async with client_sans_relance as client:
        proprietaire = await _creer_utilisateur(client)
        org = await _creer_organisation(client, proprietaire)
        await client.post(
            f"/api/v1/modules/organizations/{org}/activate",
            json={"moduleCode": "zylo_liquid"},
            headers=_entetes(proprietaire, org),
        )
        membre = await _creer_utilisateur(client)
        await _ajouter_membre_sans_droit(org, membre["id"])

        reponse = await client.post(
            "/api/v1/zylo-liquid/stations",
            json={"name": "Refusée", "code": f"R-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
            headers=_entetes(membre, org),
        )

    assert reponse.status_code == 403
    corps = reponse.json()
    _verifie_enveloppe_complete(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "permission_denied"


async def test_erreur_500_suit_l_enveloppe_et_ne_fuit_rien(client_sans_relance, routes_de_test, caplog):
    caplog.set_level(logging.ERROR, logger="zylo_office.errors")
    async with client_sans_relance as client:
        reponse = await client.get("/api/v1/_test_be220/boom")

    assert reponse.status_code == 500
    corps = reponse.json()
    _verifie_enveloppe_complete(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "internal_error"
    assert corps["error"]["details"] == []
    # CA-3 : ni trace, ni secret interne, ni nom d'exception dans la réponse.
    assert _SECRET_INTERNE not in reponse.text
    assert "Traceback" not in reponse.text
    assert "RuntimeError" not in reponse.text
    # CA-2 : le request ID de la réponse désigne l'entrée de journal correspondante.
    journal = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    assert journal and getattr(journal[-1], "request_id", None) == corps["request_id"]


async def test_request_id_client_est_reutilise_sur_une_erreur(client_sans_relance, test_city):
    """CA-2 : un X-Request-Id client valide est repris dans l'enveloppe d'erreur."""
    identifiant = f"be220-{uuid.uuid4().hex[:12]}"
    async with client_sans_relance as client:
        reponse = await client.get("/api/v1/route-inexistante-be220", headers={"X-Request-Id": identifiant})

    assert reponse.status_code == 404
    corps = reponse.json()
    assert reponse.headers["X-Request-Id"] == identifiant
    assert corps["request_id"] == identifiant


async def test_validation_decrit_chaque_champ_invalide(client_sans_relance, routes_de_test):
    """CA-4 : deux champs invalides, chacun décrit par `loc` (champ) et `type` (code)."""
    async with client_sans_relance as client:
        reponse = await client.post("/api/v1/_test_be220/formulaire", json={"prenom": {"x": 1}, "age": "pas un nombre"})

    assert reponse.status_code == 422
    erreur = reponse.json()["error"]
    champs = {tuple(d["loc"])[-1]: d["type"] for d in erreur["details"] if d.get("loc")}
    assert set(champs) == {"prenom", "age"}
    assert all(isinstance(code, str) and code for code in champs.values())
    assert set(erreur["field_errors"]) == {"prenom", "age"}


async def test_acces_hors_organisation_identique_a_ressource_inexistante(client_sans_relance, test_city):
    """CA-5 : un non-membre de l'organisation A reçoit le même corps d'erreur
    pour une organisation existante et pour une organisation inexistante."""
    async with client_sans_relance as client:
        proprietaire = await _creer_utilisateur(client)
        org_existante = await _creer_organisation(client, proprietaire)
        etranger = await _creer_utilisateur(client)

        existante = await client.post(
            "/api/v1/zylo-liquid/stations",
            json={"name": "x", "code": f"N-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
            headers=_entetes(etranger, org_existante),
        )
        inexistante = await client.post(
            "/api/v1/zylo-liquid/stations",
            json={"name": "x", "code": f"N-{uuid.uuid4().hex[:6]}", "cityId": test_city["id"]},
            headers=_entetes(etranger, str(uuid.uuid4())),
        )

    assert existante.status_code == inexistante.status_code == 404
    assert existante.json()["error"] == inexistante.json()["error"]
