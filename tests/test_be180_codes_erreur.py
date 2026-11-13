"""Enveloppe d'erreur et codes HTTP stables (BE-180).

BE-180 ne redéfinit pas l'enveloppe : elle est celle de BE-001
(`app/core/errors.py`). Ces tests fixent le contrat transverse :

- CA-1 : toute erreur suit l'enveloppe BE-001 (jeu de 8 erreurs réelles) ;
- CA-2 : sans session, 401 ; authentifié sans permission, 403 ;
- CA-3 : hors scope tenant et ressource inexistante, même statut 404 et même
  corps hors `request_id` ;
- CA-4 : 429 porte `Retry-After`, et le corps n'ajoute ni `retryable` ni
  `retryAfter` (QE-API-31) ;
- CA-5 : une 5xx ne contient ni trace ni secret interne ;
- CA-6 : chaque code du mapping QE-API-03 (401, 403, 404, 409, 422, 429, 5xx)
  est couvert par exactement un cas du jeu CA-1.

Le jeu CA-1 réutilise les routes réelles ; seule la route témoin 500 est
montée pour le temps d'un test (comme dans BE-001 et BE-220).
"""

import collections
import uuid

import httpx
import pytest
from fastapi import APIRouter

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.main import app
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
_SECRET_INTERNE = "secret-interne-be180-93d2"
_PREFIXE_ROUTES_TEST = "/api/v1/_test_be180"
_CHAMPS_INTERDITS = {"retryable", "retryAfter"}
_CODES_MAPPING = {401, 403, 404, 409, 422, 429, 500}

_routes_test = APIRouter()


@_routes_test.get("/_test_be180/boom")
def _route_qui_leve() -> None:
    """Lève une exception non prévue contenant un détail à ne jamais exposer."""
    raise RuntimeError(_SECRET_INTERNE)


@pytest.fixture
def routes_de_test():
    """Monte la route témoin sur l'application réelle, puis la retire."""
    app.include_router(_routes_test, prefix="/api/v1")
    try:
        yield
    finally:
        app.router.routes = [
            route for route in app.router.routes if not getattr(route, "path", "").startswith(_PREFIXE_ROUTES_TEST)
        ]


@pytest.fixture
async def reponses(client, routes_de_test):
    """Client sur l'application réelle qui reçoit les 500 comme des réponses HTTP.
    Dépend de `client` (conftest) pour le seed des modules et des permissions."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _entetes(token: str, organisation_id: str | None = None) -> dict:
    entetes = {"Authorization": f"Bearer {token}"}
    if organisation_id is not None:
        entetes["X-Organization-Id"] = organisation_id
    return entetes


async def _creer_utilisateur(client: httpx.AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur BE-180"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers=_entetes(token))
    return {"id": me.json()["id"], "token": token, "email": email}


async def _creer_organisation(client: httpx.AsyncClient, proprietaire: dict) -> str:
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers=_entetes(proprietaire["token"]),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ajouter_membre_sans_droit(organisation_id: str, utilisateur_id: str) -> None:
    """Appartenance directe en base : le socle n'expose pas encore d'ajout de membre."""
    async with AsyncSessionLocal() as db:
        db.add(OrganizationUser(organizationId=uuid.UUID(organisation_id), userId=uuid.UUID(utilisateur_id)))
        await db.commit()


def _verifie_enveloppe(corps: dict, en_tete_request_id: str) -> None:
    """Forme commune de toute erreur BE-001 et égalité du request ID."""
    assert set(corps) == {"error", "request_id"}
    erreur = corps["error"]
    assert set(erreur) == {"code", "message", "field_errors", "details"}
    assert isinstance(erreur["code"], str) and erreur["code"]
    assert isinstance(erreur["message"], str) and erreur["message"]
    assert isinstance(erreur["field_errors"], dict)
    assert isinstance(erreur["details"], list)
    assert corps["request_id"] == en_tete_request_id


# --- Jeu de 8 erreurs réelles (CA-1, CA-2, CA-6) -----------------------------------
#
# Chaque cas est (statut attendu, code attendu, requête). Les statuts 401, 403,
# 404, 409, 422, 429 et 500 sont les codes du mapping QE-API-03 ; 405 complète le
# jeu à huit erreurs de CA-1.


async def _cas_401(reponses):
    return await reponses.get("/api/v1/auth/me")


async def _cas_403(reponses):
    proprietaire = await _creer_utilisateur(reponses)
    organisation_id = await _creer_organisation(reponses, proprietaire)
    membre = await _creer_utilisateur(reponses)
    await _ajouter_membre_sans_droit(organisation_id, membre["id"])
    return await reponses.get("/api/v1/organizations/current/members", headers=_entetes(membre["token"], organisation_id))


async def _cas_404(reponses):
    return await reponses.get("/api/v1/route-inexistante-be180")


async def _cas_405(reponses):
    return await reponses.post("/api/v1/health")


async def _cas_409(reponses):
    email = unique_email()
    corps = {"email": email, "password": MOT_DE_PASSE, "fullName": "Doublon BE-180"}
    premier = await reponses.post("/api/v1/auth/register", json=corps)
    assert premier.status_code == 201, premier.text
    return await reponses.post("/api/v1/auth/register", json=corps)


async def _cas_422(reponses):
    return await reponses.post("/api/v1/auth/register", json={"email": "pas-un-email"})


async def _cas_429(reponses):
    email = unique_email()
    await reponses.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Verrou BE-180"})
    dernier = None
    # Le seuil vient de la configuration : le test ne fixe pas de valeur codée en dur.
    for _ in range(settings.AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT + 1):
        dernier = await reponses.post("/api/v1/auth/login", json={"email": email, "password": "mauvais-mot-de-passe-be180"})
    return dernier


async def _cas_500(reponses):
    return await reponses.get("/api/v1/_test_be180/boom")


CAS_ERREUR = [
    pytest.param(401, "http_401", _cas_401, id="401-sans-session"),
    pytest.param(403, "permission_denied", _cas_403, id="403-sans-permission"),
    pytest.param(404, "http_404", _cas_404, id="404-route-inconnue"),
    pytest.param(405, "http_405", _cas_405, id="405-methode-non-permise"),
    pytest.param(409, "email_already_used", _cas_409, id="409-email-deja-utilise"),
    pytest.param(422, "validation_error", _cas_422, id="422-validation"),
    pytest.param(429, "rate_limited", _cas_429, id="429-verrou-authentification"),
    pytest.param(500, "internal_error", _cas_500, id="500-exception-imprevue"),
]


@pytest.mark.parametrize(("statut", "code", "cas"), CAS_ERREUR)
async def test_ca1_chaque_erreur_suit_l_enveloppe_be001(reponses, statut, code, cas):
    """CA-1 : chaque erreur du jeu suit l'enveloppe, avec le statut et le code attendus."""
    async with reponses:
        reponse = await cas(reponses)

    assert reponse.status_code == statut, reponse.text
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    assert corps["error"]["code"] == code


async def test_ca2_sans_session_renvoie_401(reponses):
    """CA-2 : une requête sans jeton reçoit 401 au format d'erreur."""
    async with reponses:
        reponse = await _cas_401(reponses)

    assert reponse.status_code == 401
    _verifie_enveloppe(reponse.json(), reponse.headers["X-Request-Id"])


async def test_ca2_authentifie_sans_permission_renvoie_403(reponses):
    """CA-2 : un membre sans permission reçoit 403, pas 404 ni 200."""
    async with reponses:
        reponse = await _cas_403(reponses)

    assert reponse.status_code == 403
    _verifie_enveloppe(reponse.json(), reponse.headers["X-Request-Id"])


async def test_ca3_hors_scope_et_inexistant_renvoient_le_meme_404(reponses):
    """CA-3 : un non-membre voit le même statut et le même corps pour une
    organisation existante et pour une organisation inexistante, hors request_id."""
    async with reponses:
        proprietaire = await _creer_utilisateur(reponses)
        organisation_existante = await _creer_organisation(reponses, proprietaire)
        etranger = await _creer_utilisateur(reponses)
        charge = {"name": "Station BE-180", "code": f"B180-{uuid.uuid4().hex[:6]}", "cityId": str(uuid.uuid4())}

        existante = await reponses.post(
            "/api/v1/zylo-liquid/stations", json=charge, headers=_entetes(etranger["token"], organisation_existante)
        )
        inexistante = await reponses.post(
            "/api/v1/zylo-liquid/stations", json=charge, headers=_entetes(etranger["token"], str(uuid.uuid4()))
        )

    assert existante.status_code == inexistante.status_code == 404
    corps_existante = existante.json()
    corps_inexistante = inexistante.json()
    _verifie_enveloppe(corps_existante, existante.headers["X-Request-Id"])
    _verifie_enveloppe(corps_inexistante, inexistante.headers["X-Request-Id"])
    corps_existante.pop("request_id")
    corps_inexistante.pop("request_id")
    assert corps_existante == corps_inexistante


async def test_ca4_429_porte_retry_after_sans_champs_ajoutes(reponses):
    """CA-4 : le 429 porte `Retry-After` (entier >= 1) ; le corps garde l'enveloppe
    BE-001 et n'ajoute ni `retryable` ni `retryAfter` (QE-API-31)."""
    async with reponses:
        reponse = await _cas_429(reponses)

    assert reponse.status_code == 429
    assert int(reponse.headers["Retry-After"]) >= 1
    corps = reponse.json()
    _verifie_enveloppe(corps, reponse.headers["X-Request-Id"])
    assert not _CHAMPS_INTERDITS & set(corps)
    assert not _CHAMPS_INTERDITS & set(corps["error"])


async def test_ca5_erreur_5xx_ne_contient_ni_trace_ni_secret(reponses, caplog):
    """CA-5 : une 5xx ne contient ni trace d'exécution, ni nom d'exception, ni secret
    interne ; le détail reste dans le journal serveur."""
    async with reponses:
        reponse = await _cas_500(reponses)

    assert reponse.status_code == 500
    texte = reponse.text
    for interdit in (_SECRET_INTERNE, "Traceback", "RuntimeError", "boom", "File \""):
        assert interdit not in texte
    for valeur in reponse.headers.values():
        assert _SECRET_INTERNE not in valeur


async def test_ca6_chaque_code_du_mapping_est_couvert_une_fois():
    """CA-6 : chaque statut du mapping QE-API-03 apparaît dans exactement un cas du
    jeu CA-1 ; aucun cas hors mapping ne sert à couvrir un de ces codes."""
    statuts = [case.values[0] for case in CAS_ERREUR]
    compte = collections.Counter(statuts)
    for statut in _CODES_MAPPING:
        assert compte[statut] == 1, f"statut {statut} couvert {compte[statut]} fois"
