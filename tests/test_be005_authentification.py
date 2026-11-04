"""BE-005 : authentification (connexion, session, limitation des tentatives).

Chaque test correspond à un critère d'acceptation CA-n de la définition
`implementation-backend/tasks-socle-tenant-identite.md`, section BE-005.
Les routes couvertes : POST /api/v1/auth/login, GET /api/v1/auth/me,
POST /api/v1/auth/refresh. La déconnexion (POST /api/v1/auth/logout) relève de
BE-188 : elle n'est utilisée ici que pour révoquer une session de test.

Les en-têtes X-Forwarded-For donnent une IP propre à chaque test, pour ne pas
partager de compteur de limitation avec les autres tests de la base.
"""

import ipaddress
import uuid

from httpx import AsyncClient

from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
MAUVAIS_MOT_DE_PASSE = "mauvais-mot-de-passe-42"


def _ip_unique() -> dict:
    ip = str(ipaddress.IPv4Address(0x0A800000 | (uuid.uuid4().int & 0xFFFFFF)))
    return {"X-Forwarded-For": ip}


async def _inscrire(client: AsyncClient, email: str) -> None:
    res = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE005"}
    )
    assert res.status_code == 201, res.text


async def _connecter(client: AsyncClient, email: str, mot_de_passe: str, entetes: dict):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": mot_de_passe}, headers=entetes
    )


async def test_ca1_connexion_valide_puis_me_renvoie_utilisateur_de_la_session(client: AsyncClient):
    """CA-1 : une connexion valide renvoie 200 ; GET /me renvoie 200 avec l'utilisateur de la session."""
    email, entetes = unique_email(), _ip_unique()
    await _inscrire(client, email)

    login = await _connecter(client, email, MOT_DE_PASSE, entetes)
    assert login.status_code == 200, login.text
    jeton = login.json()["accessToken"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == email


async def test_ca2_mauvais_mot_de_passe_et_compte_inconnu_repondent_pareil(client: AsyncClient):
    """CA-2 : mauvais mot de passe et compte inexistant renvoient le même statut et le même corps d'erreur.

    Le délai approximatif n'est pas mesuré ici (test de temps non fiable en CI) ;
    seule l'indistinguabilité de la réponse est vérifiée.
    """
    existant, inconnu, entetes = unique_email(), unique_email(), _ip_unique()
    await _inscrire(client, existant)

    mauvais = await _connecter(client, existant, MAUVAIS_MOT_DE_PASSE, entetes)
    absent = await _connecter(client, inconnu, MAUVAIS_MOT_DE_PASSE, entetes)

    assert mauvais.status_code == absent.status_code == 401
    assert mauvais.json()["error"] == absent.json()["error"]
    assert mauvais.json()["error"]["code"] == "invalid_credentials"


async def test_ca3_me_sans_session_est_refuse_401(client: AsyncClient):
    """CA-3 (refus) : GET /me sans session est refusé ; code 401 (recommandation BE-005)."""
    res = await client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.json()["error"]["code"]


async def test_ca3_me_avec_jeton_invalide_est_refuse_401(client: AsyncClient):
    """CA-3 (refus, variante) : un jeton d'accès falsifié n'ouvre aucune session."""
    res = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer jeton-falsifie"})
    assert res.status_code == 401


async def test_ca3_connexion_compte_inconnu_ne_donne_aucune_session(client: AsyncClient):
    """CA-3 (refus) : un utilisateur inexistant n'obtient ni jeton ni cookie de session."""
    res = await _connecter(client, unique_email(), MOT_DE_PASSE, _ip_unique())
    assert res.status_code == 401
    assert "accessToken" not in res.json()
    assert "refreshToken" not in res.json()


async def test_ca4_au_dela_du_seuil_la_connexion_est_bloquee_pour_la_fenetre(client: AsyncClient, monkeypatch):
    """CA-4 (refus) : au-delà du seuil d'échecs, la connexion est bloquée (429) pour la fenêtre définie.

    Le seuil est abaissé à 3 pour rester rapide ; le détail du verrou progressif
    est couvert par tests/test_auth_rate_limit.py.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT", 3)
    email, entetes = unique_email(), _ip_unique()
    await _inscrire(client, email)

    for _ in range(3):
        assert (await _connecter(client, email, MAUVAIS_MOT_DE_PASSE, entetes)).status_code == 401

    bloque = await _connecter(client, email, MOT_DE_PASSE, entetes)
    assert bloque.status_code == 429
    assert bloque.json()["error"]["code"] == "rate_limited"
    assert int(bloque.headers["Retry-After"]) >= 1


async def test_ca5_session_revoquee_ne_permet_plus_me(client: AsyncClient):
    """CA-5 : une session révoquée ne permet plus GET /me.

    La révocation passe par la rotation / révocation du refresh token (la
    déconnexion, BE-188, n'est utilisée ici que comme moyen de révocation).
    """
    email, entetes = unique_email(), _ip_unique()
    await _inscrire(client, email)
    login = await _connecter(client, email, MOT_DE_PASSE, entetes)
    assert login.status_code == 200, login.text
    corps = login.json()
    refresh = corps["refreshToken"]
    jeton = corps["accessToken"]

    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})).status_code == 200

    revocation = await client.post("/api/v1/auth/logout", json={"refreshToken": refresh})
    assert revocation.status_code == 204

    apres = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton}"})
    assert apres.status_code == 401


async def test_ca5_refresh_revoque_ne_renouvelle_plus_la_session(client: AsyncClient):
    """CA-5 (complément) : un refresh token révoqué ne produit plus de session."""
    email, entetes = unique_email(), _ip_unique()
    await _inscrire(client, email)
    refresh = (await _connecter(client, email, MOT_DE_PASSE, entetes)).json()["refreshToken"]
    await client.post("/api/v1/auth/logout", json={"refreshToken": refresh})

    res = await client.post("/api/v1/auth/refresh", json={"refreshToken": refresh})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_refresh_token"


async def test_ca6_deux_sessions_simultanees_renvoient_chacune_leur_utilisateur(client: AsyncClient):
    """CA-6 (isolation) : deux sessions simultanées renvoient chacune uniquement leur utilisateur."""
    email_a, email_b = unique_email(), unique_email()
    await _inscrire(client, email_a)
    await _inscrire(client, email_b)
    jeton_a = (await _connecter(client, email_a, MOT_DE_PASSE, _ip_unique())).json()["accessToken"]
    jeton_b = (await _connecter(client, email_b, MOT_DE_PASSE, _ip_unique())).json()["accessToken"]

    me_a = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton_a}"})
    me_b = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {jeton_b}"})

    assert me_a.json()["email"] == email_a
    assert me_b.json()["email"] == email_b
    assert me_a.json()["id"] != me_b.json()["id"]
