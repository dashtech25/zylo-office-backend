"""Surface de l'API et jetons (T-015).

Intention : vérifier, sans changer le comportement métier, que
- la documentation OpenAPI n'existe qu'en ENVIRONMENT=development (404 ailleurs) ;
- les en-têtes de sécurité sont posés, sans écraser ceux d'une route ;
- CORS refuse une méthode ou un en-tête non listés ;
- les jetons émis avant la migration de bibliothèque (python-jose -> PyJWT)
  restent valides, et les jetons falsifiés restent rejetés.
"""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.config import settings
from app.core.securite_http import EnTetesSecuriteMiddleware, options_documentation
from app.core.security import decode_token

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Secret de test (même valeur que tests/conftest.py).
SECRET_TEST = "test-only-jwt-secret-" + "0123456789abcdef" * 2

# Jetons émis avec python-jose 3.3.0 (avant T-015), secret ci-dessus, exp en 2100.
# Sujet fictif : ils servent à vérifier le décodage, pas une identité réelle.
JETON_ANCIEN_ACCESS = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3ZjNjMmExZS01YjRkLTRjOGUtOWExMC0yZDZmOGU5YjBjMTEiLCJpYXQiOjE3OTAwMDAwMDAsImV4cCI6NDEwMjQ0NDgwMCwianRpIjoibGVnYWN5LWp0aS0xIiwidHlwZSI6ImFjY2VzcyJ9.uWiuj6KU-BEW1_A8L2NOGo2Z5Mgt4IpEv-JVc6fNepE"
)
JETON_ANCIEN_REFRESH = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI3ZjNjMmExZS01YjRkLTRjOGUtOWExMC0yZDZmOGU5YjBjMTEiLCJpYXQiOjE3OTAwMDAwMDAsImV4cCI6NDEwMjQ0NDgwMCwianRpIjoibGVnYWN5LWp0aS0yIiwidHlwZSI6InJlZnJlc2gifQ.FS0VC25v4w7xI3gd3C86JubTyaWIJR9wBLnRZzE0GvI"
)
SUB_ANCIEN = uuid.UUID("7f3c2a1e-5b4d-4c8e-9a10-2d6f8e9b0c11")


def _b64url(donnees: bytes) -> str:
    return base64.urlsafe_b64encode(donnees).rstrip(b"=").decode()


def _jeton_hs256(payload: dict, secret: str) -> str:
    """Jeton JWS HS256 construit à la main : le format du fil, indépendant de la bibliothèque."""
    entete = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    corps = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{entete}.{corps}".encode(), hashlib.sha256).digest()
    return f"{entete}.{corps}.{_b64url(signature)}"


# ---------------------------------------------------------------- documentation

def test_options_documentation_ouverte_uniquement_en_developpement():
    assert options_documentation("development") == {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


@pytest.mark.parametrize("environnement", ["production", "test", "staging", "", "DEVELOPMENT"])
def test_options_documentation_fermee_hors_developpement(environnement: str):
    # Fail-closed : toute valeur autre que la valeur exacte « development » ferme la documentation.
    assert options_documentation(environnement) == {"docs_url": None, "redoc_url": None, "openapi_url": None}


@pytest.mark.asyncio
async def test_openapi_et_docs_404_sous_environnement_de_test(client: AsyncClient):
    # Les tests tournent avec ENVIRONMENT=test : la documentation doit être absente.
    assert settings.ENVIRONMENT == "test"
    for chemin in ("/openapi.json", "/docs", "/redoc"):
        assert (await client.get(chemin)).status_code == 404, chemin


def _verifie_documentation_dans_un_processus(environnement: str, extra_env: dict[str, str]) -> list[int]:
    """Importe app.main dans un processus neuf avec la configuration demandée et
    interroge les trois routes de documentation (sans base de données)."""
    code = (
        "import asyncio, httpx\n"
        "from app.main import app\n"
        "async def main():\n"
        "    t = httpx.ASGITransport(app=app)\n"
        "    async with httpx.AsyncClient(transport=t, base_url='http://test') as c:\n"
        "        for p in ('/openapi.json', '/docs', '/redoc'):\n"
        "            print((await c.get(p)).status_code)\n"
        "asyncio.run(main())\n"
    )
    env = {k: v for k, v in os.environ.items() if k not in {"JWT_SECRET", "STORAGE_SIGNED_URL_SECRET", "DATABASE_URL"}}
    env.update({"ENVIRONMENT": environnement, **extra_env})
    resultat = subprocess.run(
        [sys.executable, "-c", code],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert resultat.returncode == 0, resultat.stderr[-2000:]
    # Le démarrage journalise en JSON sur stdout : on ne garde que les codes HTTP.
    return [int(ligne) for ligne in resultat.stdout.splitlines() if ligne.strip().isdigit()]


def test_openapi_200_en_developpement_dans_un_processus_reel():
    codes = _verifie_documentation_dans_un_processus("development", {})
    assert codes == [200, 200, 200]


def test_openapi_404_en_production_dans_un_processus_reel():
    # Configuration de production complète : secrets propres, aucun repli.
    extra = {
        "JWT_SECRET": "prod-" + "a1b2c3d4e5f6" * 4,
        "STORAGE_SIGNED_URL_SECRET": "prod-storage-" + "f6e5d4c3b2a1" * 3,
        "APP_FIELD_ENCRYPTION_KEY": "prod-field-" + "0f1e2d3c4b5a" * 3,
        "DATABASE_URL": "postgresql+asyncpg://zylo_office:mot-de-passe-prod-unique@db.interne:5432/zylo",
    }
    codes = _verifie_documentation_dans_un_processus("production", extra)
    assert codes == [404, 404, 404]


# ---------------------------------------------------------------- en-têtes

@pytest.mark.asyncio
async def test_en_tetes_de_securite_presents_sur_une_reponse(client: AsyncClient):
    reponse = await client.get("/api/v1/health")
    assert reponse.status_code == 200
    assert reponse.headers["x-content-type-options"] == "nosniff"
    assert reponse.headers["x-frame-options"] == "DENY"
    assert reponse.headers["referrer-policy"] == "strict-origin-when-cross-origin"


@pytest.mark.asyncio
async def test_middleware_ne_remplace_pas_un_en_tete_deja_pose():
    async def route(request):
        return PlainTextResponse("ok", headers={"X-Frame-Options": "SAMEORIGIN"})

    app = EnTetesSecuriteMiddleware(Starlette(routes=[Route("/", route)]))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        reponse = await c.get("/")
    assert reponse.headers["x-frame-options"] == "SAMEORIGIN"
    assert reponse.headers["x-content-type-options"] == "nosniff"


# ---------------------------------------------------------------- CORS

@pytest.mark.asyncio
async def test_cors_refuse_une_methode_non_listee(client: AsyncClient):
    origine = settings.CORS_ORIGINS[0]
    reponse = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": origine,
            "Access-Control-Request-Method": "TRACE",
        },
    )
    # Le navigateur refuse la requête : statut 400 au préflight, et la méthode
    # n'apparaît pas parmi les méthodes autorisées.
    assert reponse.status_code == 400
    assert "TRACE" not in reponse.headers.get("access-control-allow-methods", "")


@pytest.mark.asyncio
async def test_cors_accepte_les_methodes_du_frontend(client: AsyncClient):
    origine = settings.CORS_ORIGINS[0]
    for methode in ("PATCH", "PUT", "DELETE", "POST"):
        reponse = await client.options(
            "/api/v1/auth/me",
            headers={
                "Origin": origine,
                "Access-Control-Request-Method": methode,
                "Access-Control-Request-Headers": "authorization,content-type,x-organization-id",
            },
        )
        assert reponse.status_code == 200, methode
        assert reponse.headers["access-control-allow-origin"] == origine


@pytest.mark.asyncio
async def test_cors_refuse_un_en_tete_non_liste(client: AsyncClient):
    reponse = await client.options(
        "/api/v1/auth/me",
        headers={
            "Origin": settings.CORS_ORIGINS[0],
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-en-tete-inconnu",
        },
    )
    assert reponse.status_code == 400


# ---------------------------------------------------------------- jetons

def test_jeton_emis_avant_la_migration_reste_valide():
    assert decode_token(JETON_ANCIEN_ACCESS, expected_type="access") == SUB_ANCIEN
    assert decode_token(JETON_ANCIEN_REFRESH, expected_type="refresh") == SUB_ANCIEN


def test_jeton_ancien_refuse_si_type_inattendu():
    with pytest.raises(HTTPException) as info:
        decode_token(JETON_ANCIEN_REFRESH, expected_type="access")
    assert info.value.status_code == 401


@pytest.mark.asyncio
async def test_jeton_au_format_historique_accepte_par_l_api(client: AsyncClient):
    # Création réelle d'un utilisateur, puis jeton au format HS256 historique
    # pour cet utilisateur : l'API doit l'accepter comme avant la migration.
    email = f"compat-{uuid.uuid4().hex[:10]}@zylo-office-test.example.com"
    creation = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "TestPassword123!", "fullName": "Compat"},
    )
    assert creation.status_code == 201
    user_id = creation.json()["id"]
    jeton = _jeton_hs256(
        {"sub": user_id, "type": "access", "iat": 1790000000, "exp": 4102444800, "jti": "compat-1"},
        settings.JWT_SECRET,
    )
    reponse = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert reponse.status_code == 200
    assert reponse.json()["email"] == email


def test_jeton_signe_avec_un_autre_secret_est_refuse():
    faux = _jeton_hs256(
        {"sub": str(SUB_ANCIEN), "type": "access", "iat": 1790000000, "exp": 4102444800, "jti": "x"},
        "secret-de-l-attaquant-" + "z" * 40,
    )
    with pytest.raises(HTTPException) as info:
        decode_token(faux, expected_type="access")
    assert info.value.status_code == 401


def test_jeton_alg_none_est_refuse():
    entete = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    corps = _b64url(json.dumps({"sub": str(SUB_ANCIEN), "type": "access", "exp": 4102444800}).encode())
    with pytest.raises(HTTPException) as info:
        decode_token(f"{entete}.{corps}.", expected_type="access")
    assert info.value.status_code == 401


def test_jeton_expire_est_refuse():
    expire = _jeton_hs256(
        {"sub": str(SUB_ANCIEN), "type": "access", "iat": 1600000000, "exp": 1600000600, "jti": "old"},
        settings.JWT_SECRET,
    )
    with pytest.raises(HTTPException) as info:
        decode_token(expire, expected_type="access")
    assert info.value.status_code == 401
