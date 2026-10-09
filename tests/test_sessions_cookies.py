"""Sessions par cookies, rotation, réutilisation et révocation (T-020, T-037a).

Intention : les cookies sont relus dans `Set-Cookie` puis renvoyés à la main.
Le client httpx n'envoie pas les cookies `Secure` sur `http://test`, et le test
doit décider lui-même quels cookies accompagnent chaque requête, comme un
navigateur le ferait.
"""

import asyncio
from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.config import settings
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
MOT_DE_PASSE_NOUVEAU = "Nouveau-Mot-2026-Solide!"
FIN_DE_TRANSITION_PASSEE = datetime(2000, 1, 1, tzinfo=timezone.utc)

NOM_ACCES = "zylo_access"
NOM_RAFRAICHISSEMENT = "zylo_refresh"
NOM_CSRF = "zylo_csrf"
ENTETE_CSRF = "X-CSRF-Token"
URL_LOGIN = "/api/v1/auth/login"
URL_REFRESH = "/api/v1/auth/refresh"
URL_LOGOUT = "/api/v1/auth/logout"
URL_ME = "/api/v1/auth/me"
URL_CHANGE_MDP = "/api/v1/auth/change-password"


def _cookie_brut(res, nom: str) -> str | None:
    """Ligne `Set-Cookie` complète pour `nom` (valeur et attributs), ou None."""
    for brut in res.headers.get_list("set-cookie"):
        if brut.startswith(f"{nom}="):
            return brut
    return None


def _fusionne(session: dict, res) -> dict:
    """Met à jour les valeurs de cookies de `session` avec les `Set-Cookie` de `res`."""
    nouvelle = dict(session)
    for nom in (NOM_ACCES, NOM_RAFRAICHISSEMENT, NOM_CSRF):
        brut = _cookie_brut(res, nom)
        if brut is not None:
            nouvelle[nom] = brut.split(";", 1)[0].split("=", 1)[1]
    return nouvelle


def _cookies(session: dict) -> dict:
    return {"Cookie": "; ".join(f"{nom}={valeur}" for nom, valeur in session.items())}


def _avec_csrf(session: dict, extra: dict | None = None) -> dict:
    entetes = {**_cookies(session), ENTETE_CSRF: session[NOM_CSRF]}
    return {**entetes, **(extra or {})}


async def _connexion(client: AsyncClient) -> tuple[str, dict, dict]:
    """Inscrit et connecte un utilisateur. Renvoie (email, session, corps JSON)."""
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Session Test"})
    res = await client.post(URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE})
    assert res.status_code == 200, res.text
    return email, _fusionne({}, res), res.json()


async def test_login_pose_les_cookies_httponly_secure_samesite(client: AsyncClient):
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Cookies Test"})
    res = await client.post(URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE})
    assert res.status_code == 200, res.text

    acces = _cookie_brut(res, NOM_ACCES).lower()
    assert "httponly" in acces and "secure" in acces and "samesite=lax" in acces and "path=/;" in acces

    rafraichissement = _cookie_brut(res, NOM_RAFRAICHISSEMENT).lower()
    assert "httponly" in rafraichissement and "secure" in rafraichissement and "samesite=lax" in rafraichissement
    assert "path=/api/v1/auth" in rafraichissement

    # Le jeton CSRF doit être lisible par l'interface : il ne porte aucun secret d'accès.
    csrf = _cookie_brut(res, NOM_CSRF).lower()
    assert "httponly" not in csrf and "secure" in csrf and "samesite=lax" in csrf

    assert res.headers["cache-control"] == "no-store"


async def test_pendant_la_transition_les_jetons_restent_dans_le_json(client: AsyncClient):
    # Clients existants : le corps garde accessToken et refreshToken jusqu'à la date de fin.
    _, _, corps = await _connexion(client)
    assert corps["accessToken"] and corps["refreshToken"]


async def test_fin_de_transition_retire_les_jetons_du_json(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_HEADER_ACCEPTED_UNTIL", FIN_DE_TRANSITION_PASSEE)
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Fin Transition"})
    res = await client.post(URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE})
    assert res.status_code == 200
    assert "accessToken" not in res.json()
    assert "refreshToken" not in res.json()
    assert _cookie_brut(res, NOM_ACCES) is not None
    assert _cookie_brut(res, NOM_RAFRAICHISSEMENT) is not None


async def test_me_accepte_le_seul_cookie_d_acces(client: AsyncClient):
    _, session, _ = await _connexion(client)
    res = await client.get(URL_ME, headers=_cookies(session))
    assert res.status_code == 200


async def test_fin_de_transition_refuse_l_en_tete_authorization(client: AsyncClient, monkeypatch):
    _, session, corps = await _connexion(client)
    monkeypatch.setattr(settings, "AUTH_HEADER_ACCEPTED_UNTIL", FIN_DE_TRANSITION_PASSEE)
    assert (await client.get(URL_ME, headers={"Authorization": f"Bearer {corps['accessToken']}"})).status_code == 401
    assert (await client.get(URL_ME, headers=_cookies(session))).status_code == 200


async def test_refresh_par_cookie_exige_le_jeton_csrf(client: AsyncClient):
    _, session, _ = await _connexion(client)

    sans_csrf = await client.post(URL_REFRESH, headers=_cookies(session), json={})
    assert sans_csrf.status_code == 403
    assert sans_csrf.json()["error"]["code"] == "csrf_invalid"

    avec_csrf = await client.post(URL_REFRESH, headers=_avec_csrf(session), json={})
    assert avec_csrf.status_code == 200, avec_csrf.text
    assert _cookie_brut(avec_csrf, NOM_RAFRAICHISSEMENT) is not None


async def test_rejeu_d_un_refresh_revoque_toute_la_famille(client: AsyncClient):
    _, session_1, _ = await _connexion(client)

    rotation = await client.post(URL_REFRESH, headers=_avec_csrf(session_1), json={})
    assert rotation.status_code == 200
    session_2 = _fusionne(session_1, rotation)

    # Rejeu du jeton déjà tourné : refusé, et la chaîne entière est coupée.
    rejeu = await client.post(URL_REFRESH, headers=_avec_csrf(session_1), json={})
    assert rejeu.status_code == 401
    assert rejeu.json()["error"]["code"] == "invalid_refresh_token"

    # Le jeton légitime suivant est lui aussi refusé.
    suivant = await client.post(URL_REFRESH, headers=_avec_csrf(session_2), json={})
    assert suivant.status_code == 401


async def test_renouvellements_concurrents_un_seul_reussit(client: AsyncClient):
    _, session, _ = await _connexion(client)

    reponses = await asyncio.gather(
        client.post(URL_REFRESH, headers=_avec_csrf(session), json={}),
        client.post(URL_REFRESH, headers=_avec_csrf(session), json={}),
    )
    assert sorted(r.status_code for r in reponses) == [200, 401]


async def test_logout_efface_les_cookies_et_revoque_le_refresh(client: AsyncClient):
    _, session, _ = await _connexion(client)

    res = await client.post(URL_LOGOUT, headers=_avec_csrf(session), json={})
    assert res.status_code == 204
    for nom in (NOM_ACCES, NOM_RAFRAICHISSEMENT):
        brut = _cookie_brut(res, nom)
        assert brut is not None and "max-age=0" in brut.lower()

    apres = await client.post(URL_REFRESH, headers=_avec_csrf(session), json={})
    assert apres.status_code == 401


async def test_logout_sans_jeton_csrf_refuse_et_ne_revoque_rien(client: AsyncClient):
    _, session, _ = await _connexion(client)

    res = await client.post(URL_LOGOUT, headers=_cookies(session), json={})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf_invalid"

    # La session reste ouverte : un refresh légitime passe encore.
    assert (await client.post(URL_REFRESH, headers=_avec_csrf(session), json={})).status_code == 200


async def test_requete_non_sure_par_cookie_sans_csrf_refusee(client: AsyncClient):
    _, session, _ = await _connexion(client)
    corps = {"currentPassword": MOT_DE_PASSE, "newPassword": MOT_DE_PASSE_NOUVEAU}
    res = await client.post(URL_CHANGE_MDP, headers=_cookies(session), json=corps)
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "csrf_invalid"


async def test_origine_etrangere_refusee_sur_requete_par_cookie(client: AsyncClient):
    _, session, _ = await _connexion(client)

    etrangere = await client.post(
        URL_REFRESH, headers=_avec_csrf(session, {"Origin": "https://attaquant.example"}), json={}
    )
    assert etrangere.status_code == 403
    assert etrangere.json()["error"]["code"] == "origin_refused"

    autorisee = await client.post(
        URL_REFRESH, headers=_avec_csrf(session, {"Origin": "http://localhost:3001"}), json={}
    )
    assert autorisee.status_code == 200, autorisee.text


async def test_changement_de_mot_de_passe_garde_la_session_courante_et_coupe_les_autres(client: AsyncClient):
    email, session_a, _ = await _connexion(client)
    res_b = await client.post(URL_LOGIN, json={"email": email, "password": MOT_DE_PASSE})
    session_b = _fusionne({}, res_b)

    res = await client.post(
        URL_CHANGE_MDP,
        headers=_avec_csrf(session_a),
        json={"currentPassword": MOT_DE_PASSE, "newPassword": MOT_DE_PASSE_NOUVEAU},
    )
    assert res.status_code == 200, res.text

    autre = await client.post(URL_REFRESH, headers=_avec_csrf(session_b), json={})
    assert autre.status_code == 401
    courante = await client.post(URL_REFRESH, headers=_avec_csrf(session_a), json={})
    assert courante.status_code == 200
