"""BE-020 : profil de compte en lecture seule.

Chaque test correspond à un critère d'acceptation CA-n de la définition
`implementation-backend/tasks-socle-tenant-identite.md`, section BE-020.
Route couverte : GET /api/v1/account/profile (aucune route d'édition).
"""

import ipaddress
import uuid

from httpx import AsyncClient

from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
PROFIL = "/api/v1/account/profile"


def _ip_unique() -> dict:
    ip = str(ipaddress.IPv4Address(0x0A900000 | (uuid.uuid4().int & 0xFFFFFF)))
    return {"X-Forwarded-For": ip}


async def _inscrire(client: AsyncClient, email: str, nom: str) -> str:
    res = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": nom}
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _jeton(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE}, headers=_ip_unique()
    )
    assert res.status_code == 200, res.text
    return res.json()["accessToken"]


async def test_be020_ca1_profil_renvoye_est_celui_de_la_session(client: AsyncClient):
    """CA-1 : GET /account/profile renvoie le profil de l'utilisateur de la session."""
    email = unique_email()
    user_id = await _inscrire(client, email, "Profil Session")
    jeton = await _jeton(client, email)

    res = await client.get(PROFIL, headers={"Authorization": f"Bearer {jeton}"})

    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["id"] == user_id
    assert corps["email"] == email
    assert corps["fullName"] == "Profil Session"
    # Le profil ne doit jamais exposer le condensat du mot de passe.
    assert "hashedPassword" not in corps
    assert "password" not in corps


async def test_be020_ca2_sans_session_la_route_est_refusee_401(client: AsyncClient):
    """CA-2 (refus) : sans session, ou avec un jeton invalide, la route renvoie 401."""
    res_sans_jeton = await client.get(PROFIL)
    assert res_sans_jeton.status_code == 401, res_sans_jeton.text

    res_jeton_faux = await client.get(PROFIL, headers={"Authorization": "Bearer jeton-falsifie"})
    assert res_jeton_faux.status_code == 401, res_jeton_faux.text


async def test_be020_ca3_profil_d_un_autre_utilisateur_jamais_renvoye(client: AsyncClient):
    """CA-3 (isolation) : même si la requête désigne un autre utilisateur (paramètre
    ou en-tête), la réponse reste le profil de la session et jamais celui de l'autre."""
    email_a, email_b = unique_email(), unique_email()
    await _inscrire(client, email_a, "Utilisateur A")
    id_b = await _inscrire(client, email_b, "Utilisateur B")
    jeton_a = await _jeton(client, email_a)

    res = await client.get(
        f"{PROFIL}?user_id={id_b}&userId={id_b}",
        headers={"Authorization": f"Bearer {jeton_a}", "X-User-Id": id_b},
    )

    assert res.status_code == 200, res.text
    corps = res.json()
    assert corps["email"] == email_a
    assert corps["id"] != id_b
    assert email_b not in res.text


async def test_be020_ca4_put_et_patch_renvoient_405(client: AsyncClient):
    """CA-4 : aucune route d'édition du profil. PUT et PATCH renvoient 405."""
    email = unique_email()
    await _inscrire(client, email, "Lecture Seule")
    jeton = await _jeton(client, email)
    entetes = {"Authorization": f"Bearer {jeton}"}

    res_put = await client.put(PROFIL, json={"fullName": "Modifie"}, headers=entetes)
    res_patch = await client.patch(PROFIL, json={"fullName": "Modifie"}, headers=entetes)

    assert res_put.status_code == 405, res_put.text
    assert res_patch.status_code == 405, res_patch.text
