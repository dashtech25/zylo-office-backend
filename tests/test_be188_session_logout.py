"""BE-188 : session et authentification (déconnexion, refus de session, CSRF).

Chaque test correspond à un critère de la définition
`implementation-backend/tasks-donnees-api-contrats.md`, section BE-188.
Route propre à BE-188 : POST /api/v1/auth/logout. Les autres routes d'échange de
session (login, me, refresh) sont portées par BE-005 ; leurs tests sont réutilisés
ici lorsque le critère le demande (CA-1, CA-3, CA-5 de BE-188).

Droits (BE-188) : logout exige une session valide. Session absente, expirée ou
révoquée : 401 (code `invalid_refresh_token`, comme refresh). Mutation par cookie
sans origine valide ou sans jeton CSRF : 403, avant toute écriture.
"""

import ipaddress
import uuid

from httpx import AsyncClient

from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
URL_LOGIN = "/api/v1/auth/login"
URL_LOGOUT = "/api/v1/auth/logout"
URL_REFRESH = "/api/v1/auth/refresh"
URL_ME = "/api/v1/auth/me"
NOM_ACCES = "zylo_access"
NOM_RAFRAICHISSEMENT = "zylo_refresh"
NOM_CSRF = "zylo_csrf"
ENTETE_CSRF = "X-CSRF-Token"
ORIGINE_ETRANGERE = "https://attaquant.example"


def _ip_unique() -> dict:
    ip = str(ipaddress.IPv4Address(0x0A900000 | (uuid.uuid4().int & 0xFFFFFF)))
    return {"X-Forwarded-For": ip}


async def _connecter_par_corps(client: AsyncClient) -> dict:
    """Inscrit un utilisateur, le connecte et renvoie le corps JSON (jetons inclus)."""
    email = unique_email()
    res = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE188"}
    )
    assert res.status_code == 201, res.text
    login = await client.post(
        URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE}, headers=_ip_unique()
    )
    assert login.status_code == 200, login.text
    return login.json()


async def _connecter_par_cookies(client: AsyncClient) -> dict:
    """Connecte un utilisateur et renvoie les cookies de session et le jeton CSRF."""
    email = unique_email()
    await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "BE188"}
    )
    login = await client.post(
        URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE}, headers=_ip_unique()
    )
    assert login.status_code == 200, login.text
    return {
        NOM_ACCES: login.cookies[NOM_ACCES],
        NOM_RAFRAICHISSEMENT: login.cookies[NOM_RAFRAICHISSEMENT],
        NOM_CSRF: login.cookies[NOM_CSRF],
    }


def _entetes_cookies(session: dict, extra: dict | None = None) -> dict:
    """En-têtes d'une requête par cookie, avec le jeton CSRF en double soumission."""
    cookies = "; ".join(f"{nom}={valeur}" for nom, valeur in session.items())
    entetes = {"Cookie": cookies, ENTETE_CSRF: session[NOM_CSRF]}
    return {**entetes, **(extra or {})}


async def test_ca1_logout_puis_me_renvoie_401(client: AsyncClient):
    """CA-1 : une session révoquée par logout reçoit 401 sur GET /api/v1/auth/me."""
    corps = await _connecter_par_corps(client)
    entetes = {"Authorization": f"Bearer {corps['accessToken']}"}
    assert (await client.get(URL_ME, headers=entetes)).status_code == 200

    revocation = await client.post(URL_LOGOUT, json={"refreshToken": corps["refreshToken"]})
    assert revocation.status_code == 204

    apres = await client.get(URL_ME, headers=entetes)
    assert apres.status_code == 401


async def test_ca2_logout_par_cookie_origine_invalide_renvoie_403(client: AsyncClient):
    """CA-2 : une mutation par cookie avec origine invalide renvoie 403, sans rien révoquer."""
    session = await _connecter_par_cookies(client)

    refuse = await client.post(
        URL_LOGOUT, headers=_entetes_cookies(session, {"Origin": ORIGINE_ETRANGERE}), json={}
    )
    assert refuse.status_code == 403
    assert refuse.json()["error"]["code"] == "origin_refused"

    # Rien n'a été révoqué : le refresh par cookie fonctionne encore.
    rafraichi = await client.post(URL_REFRESH, headers=_entetes_cookies(session), json={})
    assert rafraichi.status_code == 200, rafraichi.text


async def test_ca2_logout_par_cookie_sans_jeton_csrf_renvoie_403(client: AsyncClient):
    """CA-2 (complément) : logout par cookie sans en-tête CSRF renvoie 403 csrf_invalid."""
    session = await _connecter_par_cookies(client)
    cookies = "; ".join(f"{nom}={valeur}" for nom, valeur in session.items())

    refuse = await client.post(URL_LOGOUT, headers={"Cookie": cookies}, json={})
    assert refuse.status_code == 403
    assert refuse.json()["error"]["code"] == "csrf_invalid"


async def test_ca3_refresh_deja_tourne_renvoie_401(client: AsyncClient):
    """CA-3 : un refresh token déjà utilisé après rotation renvoie 401 invalid_refresh_token."""
    corps = await _connecter_par_corps(client)
    ancien = corps["refreshToken"]

    rotation = await client.post(URL_REFRESH, json={"refreshToken": ancien})
    assert rotation.status_code == 200, rotation.text

    rejeu = await client.post(URL_REFRESH, json={"refreshToken": ancien})
    assert rejeu.status_code == 401
    assert rejeu.json()["error"]["code"] == "invalid_refresh_token"


async def test_droits_logout_sans_jeton_renvoie_401(client: AsyncClient):
    """Droits : logout sans session (ni cookie ni corps) renvoie 401, pas 204."""
    res = await client.post(URL_LOGOUT, json={})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_refresh_token"


async def test_droits_logout_jeton_inconnu_renvoie_401(client: AsyncClient):
    """Droits : logout avec un refresh token inconnu renvoie 401."""
    res = await client.post(URL_LOGOUT, json={"refreshToken": "jeton.inconnu.invalide"})
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "invalid_refresh_token"


async def test_droits_logout_deja_revoque_renvoie_401(client: AsyncClient):
    """Droits : une session déjà révoquée (second logout) renvoie 401, pas 204."""
    corps = await _connecter_par_corps(client)
    premier = await client.post(URL_LOGOUT, json={"refreshToken": corps["refreshToken"]})
    assert premier.status_code == 204

    second = await client.post(URL_LOGOUT, json={"refreshToken": corps["refreshToken"]})
    assert second.status_code == 401
    assert second.json()["error"]["code"] == "invalid_refresh_token"


async def test_isolation_logout_ne_coupe_pas_une_autre_session(client: AsyncClient):
    """Isolation : le logout d'une session ne révoque pas la session ouverte à côté."""
    premiere = await _connecter_par_corps(client)
    email_seconde = None
    # Même utilisateur, seconde session : on reconnecte le compte de la première.
    me = await client.get(URL_ME, headers={"Authorization": f"Bearer {premiere['accessToken']}"})
    assert me.status_code == 200
    email_seconde = me.json()["email"]
    seconde = await client.post(
        URL_LOGIN, json={"email": email_seconde, "password": MOT_DE_PASSE}, headers=_ip_unique()
    )
    assert seconde.status_code == 200, seconde.text
    corps_seconde = seconde.json()

    assert (await client.post(URL_LOGOUT, json={"refreshToken": premiere["refreshToken"]})).status_code == 204

    assert (
        await client.get(URL_ME, headers={"Authorization": f"Bearer {premiere['accessToken']}"})
    ).status_code == 401
    assert (
        await client.get(URL_ME, headers={"Authorization": f"Bearer {corps_seconde['accessToken']}"})
    ).status_code == 200
