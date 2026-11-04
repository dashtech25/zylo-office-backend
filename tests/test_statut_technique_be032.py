"""Tests du statut technique du service : health et readiness (BE-032).

Ces tests fixent le contrat décrit dans `app/core/health.py` et
`app/api/v1/endpoints/health.py` :

- `GET /api/v1/health` garde son format `{"status": "ok"}` et ne touche pas la base ;
- `GET /api/v1/health/ready` répond `{"status": "ready"}` quand la base répond,
  et `{"status": "not ready"}` avec HTTP 503 quand elle ne répond pas ;
- les deux routes sont publiques : aucune session, aucun en-tête d'authentification ;
- les réponses ne contiennent ni secret, ni URL de base, ni courriel ;
- seul GET est accepté : les autres méthodes renvoient 405.

La base indisponible est simulée par surcharge de la dépendance `get_db`,
sans couper réellement la base de test.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.exc import OperationalError

from app.core.database import get_db
from app.main import app


class _SessionEnPanne:
    """Session factice dont toute requête échoue comme une base injoignable."""

    async def execute(self, *args, **kwargs):
        raise OperationalError("SELECT 1", {}, OSError("connexion refusée"))

    async def rollback(self) -> None:
        return None


class _SessionOSErrorEnPanne:
    """Session factice qui échoue au niveau réseau (connexion refusée côté OS)."""

    async def execute(self, *args, **kwargs):
        raise ConnectionRefusedError("connexion refusée")

    async def rollback(self) -> None:
        return None


async def _fournit_session(session_factice) -> AsyncGenerator:
    yield session_factice


@pytest.fixture
def base_en_panne(request):
    """Remplace `get_db` par une session qui échoue, le temps d'un test."""
    session_factice = request.param()

    async def _dependance() -> AsyncGenerator:
        async for session in _fournit_session(session_factice):
            yield session

    app.dependency_overrides[get_db] = _dependance
    try:
        yield session_factice
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_health_reste_ok_et_ne_touche_pas_la_base(client):
    async with client:
        reponse = await client.get("/api/v1/health")

    assert reponse.status_code == 200
    assert reponse.json() == {"status": "ok"}


async def test_ready_repond_ready_quand_la_base_repond(client):
    async with client:
        reponse = await client.get("/api/v1/health/ready")

    assert reponse.status_code == 200
    assert reponse.json() == {"status": "ready"}


@pytest.mark.parametrize("base_en_panne", [_SessionEnPanne, _SessionOSErrorEnPanne], indirect=True)
async def test_ready_repond_not_ready_quand_la_base_est_indisponible(client, base_en_panne):
    async with client:
        reponse = await client.get("/api/v1/health/ready")

    assert reponse.status_code == 503
    assert reponse.json() == {"status": "not ready"}


async def test_reponses_sans_secret_ni_url_ni_courriel(client):
    # CA-1 : la réponse ne contient aucun secret, aucune URL de base et aucun courriel.
    # On vérifie le corps brut, pour couvrir toute clé ajoutée plus tard.
    async with client:
        sante = await client.get("/api/v1/health")
        pret = await client.get("/api/v1/health/ready")

    for reponse in (sante, pret):
        corps = reponse.text
        assert set(reponse.json().keys()) == {"status"}
        assert "postgresql" not in corps
        assert "@" not in corps
        assert "://" not in corps
        assert "password" not in corps.lower()
        assert "secret" not in corps.lower()


@pytest.mark.parametrize("base_en_panne", [_SessionEnPanne], indirect=True)
async def test_base_indisponible_ne_fuit_ni_url_ni_detail_d_erreur(client, base_en_panne):
    # CA-1 et CA-2 : même quand la base échoue, le message d'erreur interne n'est pas renvoyé.
    async with client:
        reponse = await client.get("/api/v1/health/ready")

    corps = reponse.text
    assert reponse.json() == {"status": "not ready"}
    assert "connexion refusée" not in corps
    assert "SELECT" not in corps
    assert "postgresql" not in corps


async def test_routes_publiques_sans_session_ni_authentification(client):
    # CA-3 : aucune session, aucun cookie, aucun en-tête d'authentification.
    async with client:
        sante = await client.get("/api/v1/health", headers={})
        pret = await client.get("/api/v1/health/ready", headers={})

    assert sante.status_code == 200
    assert pret.status_code == 200


@pytest.mark.parametrize("chemin", ["/api/v1/health", "/api/v1/health/ready"])
@pytest.mark.parametrize("methode", ["POST", "PUT", "PATCH", "DELETE"])
async def test_methodes_autres_que_get_refusees_avec_405(client, chemin, methode):
    # CA-4 : seul GET est accepté.
    async with client:
        reponse = await client.request(methode, chemin)

    assert reponse.status_code == 405
