"""Tests du contrat d'erreurs, du request ID et du format de succès (BE-001).

Ces tests fixent le contrat décrit dans `app/core/errors.py` et
`app/core/middleware.py` :

- toute erreur HTTP (404, 405, 500, 422) suit l'enveloppe
  `{"error": {"code", "message", "field_errors", "details"}, "request_id"}` ;
- `request_id` du corps = en-tête `X-Request-Id` = en-tête `X-Correlation-Id` ;
- un 500 ne livre ni trace ni détail interne, et son `request_id` figure dans
  le journal serveur (événement `unhandled_error`) ;
- un 422 n'expose jamais `input` ni `ctx` (secrets soumis, objets Python) ;
- le succès `GET /api/v1/health` garde son format `{"status": "ok"}` ;
- un identifiant client n'est repris que s'il respecte le motif
  `^[A-Za-z0-9._:-]{1,128}$`, sinon un UUID est généré.

Les routes de test (`/api/v1/_test_be001/...`) ne sont montées que le temps
d'un test, et retirées ensuite : l'application de production n'en garde aucune.
"""

import logging
import re
import uuid

import httpx
import pytest
from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from app.main import app

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_PREFIXE_ROUTES_TEST = "/api/v1/_test_be001"
_SECRET_INTERNE = "secret-interne-be001-7f3a"


class _Charge(BaseModel):
    """Corps de test : un validateur métier lève une ValueError, ce qui place
    l'objet exception dans `ctx` de l'erreur Pydantic (cas qui faisait échouer
    la sérialisation de la réponse 422, voir `_jsonable_validation_errors`)."""

    montant: int

    @field_validator("montant")
    @classmethod
    def _montant_positif(cls, valeur: int) -> int:
        if valeur <= 0:
            raise ValueError("le montant doit être positif")
        return valeur


_routes_test = APIRouter()


@_routes_test.get("/_test_be001/boom")
def _route_qui_leve() -> None:
    """Lève une exception non gérée contenant un détail interne à ne jamais exposer."""
    raise RuntimeError(_SECRET_INTERNE)


@_routes_test.post("/_test_be001/charge")
def _route_avec_corps(charge: _Charge) -> dict[str, int]:
    """Route témoin de validation : le corps est un `_Charge`."""
    return {"montant": charge.montant}


@pytest.fixture
def routes_de_test():
    """Monte les routes de test sur l'application réelle, puis les retire."""
    app.include_router(_routes_test, prefix="/api/v1")
    try:
        yield
    finally:
        app.router.routes = [
            route
            for route in app.router.routes
            if not getattr(route, "path", "").startswith(_PREFIXE_ROUTES_TEST)
        ]


@pytest.fixture
def client():
    """Client HTTP sur l'application réelle, sans relancer les exceptions serveur
    (un 500 doit arriver comme une réponse HTTP, comme en production)."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _verifie_enveloppe(corps: dict, en_tete_request_id: str | None) -> None:
    """Vérifie la forme commune de toute réponse d'erreur."""
    assert set(corps) == {"error", "request_id"}
    erreur = corps["error"]
    assert set(erreur) == {"code", "message", "field_errors", "details"}
    assert isinstance(erreur["code"], str) and erreur["code"]
    assert isinstance(erreur["message"], str) and erreur["message"]
    assert isinstance(erreur["field_errors"], dict)
    assert isinstance(erreur["details"], list)
    assert isinstance(corps["request_id"], str) and corps["request_id"]
    if en_tete_request_id is not None:
        assert corps["request_id"] == en_tete_request_id


async def test_route_inconnue_renvoie_404_au_format_erreur(client):
    async with client:
        reponse = await client.get("/api/v1/route-inexistante-be001")

    assert reponse.status_code == 404
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "http_404"


async def test_methode_non_permise_renvoie_405_au_format_erreur(client):
    async with client:
        reponse = await client.post("/api/v1/health")

    assert reponse.status_code == 405
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "http_405"


async def test_erreur_inattendue_renvoie_500_sans_detail_interne(client, routes_de_test, caplog):
    caplog.set_level(logging.ERROR, logger="zylo_office.errors")
    async with client:
        reponse = await client.get("/api/v1/_test_be001/boom")

    assert reponse.status_code == 500
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == "internal_error"

    texte = reponse.text
    assert _SECRET_INTERNE not in texte
    assert "Traceback" not in texte
    assert "RuntimeError" not in texte

    # Le request ID de la réponse doit désigner l'entrée de journal "unhandled_error".
    journal = [r for r in caplog.records if r.getMessage() == "unhandled_error"]
    assert journal, "l'événement unhandled_error doit être journalisé"
    assert getattr(journal[-1], "request_id", None) == corps["request_id"]


async def test_erreur_de_validation_renvoie_422_sans_input_ni_ctx(client, routes_de_test):
    async with client:
        reponse = await client.post("/api/v1/_test_be001/charge", json={"montant": -1})

    assert reponse.status_code == 422
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    erreur = corps["error"]
    assert erreur["code"] == "validation_error"
    assert "montant" in erreur["field_errors"]
    assert isinstance(erreur["field_errors"]["montant"], list) and erreur["field_errors"]["montant"]

    assert erreur["details"], "details doit décrire l'erreur de validation"
    for detail in erreur["details"]:
        assert "input" not in detail
        assert "ctx" not in detail


async def test_succes_health_garde_son_format(client):
    async with client:
        reponse = await client.get("/api/v1/health")

    assert reponse.status_code == 200
    assert reponse.json() == {"status": "ok"}
    assert reponse.headers["X-Request-Id"]
    assert reponse.headers["X-Correlation-Id"] == reponse.headers["X-Request-Id"]


async def test_request_id_client_valide_est_repris(client):
    identifiant = "req.abc-123:x_9"
    async with client:
        reponse = await client.get("/api/v1/health", headers={"X-Request-Id": identifiant})

    assert reponse.headers["X-Request-Id"] == identifiant
    assert reponse.headers["X-Correlation-Id"] == identifiant


async def test_correlation_id_client_valide_est_repris(client):
    identifiant = "corr-client-42"
    async with client:
        reponse = await client.get("/api/v1/health", headers={"X-Correlation-Id": identifiant})

    assert reponse.headers["X-Request-Id"] == identifiant
    assert reponse.headers["X-Correlation-Id"] == identifiant


@pytest.mark.parametrize("identifiant_invalide", ["x" * 129, "espace interdit", "accent-é"])
async def test_request_id_client_invalide_remplace_par_uuid(client, identifiant_invalide):
    async with client:
        reponse = await client.get("/api/v1/health", headers={"X-Request-Id": identifiant_invalide})

    genere = reponse.headers["X-Request-Id"]
    assert genere != identifiant_invalide
    assert _UUID.match(genere), f"identifiant généré attendu au format UUID : {genere}"
    assert reponse.headers["X-Correlation-Id"] == genere


async def test_request_id_invalide_puis_correlation_valide_est_repris(client):
    """Un X-Request-Id invalide ne doit pas écarter un X-Correlation-Id valide."""
    async with client:
        reponse = await client.get(
            "/api/v1/health",
            headers={"X-Request-Id": "espace interdit", "X-Correlation-Id": "corr-valide-7"},
        )

    assert reponse.headers["X-Request-Id"] == "corr-valide-7"
    assert reponse.headers["X-Correlation-Id"] == "corr-valide-7"
