"""BE-018 : changement de mot de passe du compte.

Chaque test correspond à un critère d'acceptation CA-n de la définition
`implementation-backend/tasks-socle-tenant-identite.md`, section BE-018.

Route testée : POST /api/v1/auth/change-password. La définition indique la route
`POST /api/v1/account/password` comme NON DÉFINI ; la route existante est reprise
(pas de doublon). Dépendances : BE-005 (session, connexion), BE-007 (journal d'audit).
"""

import ipaddress
import json
import uuid

from httpx import AsyncClient
from sqlalchemy import select

from app.audit.models import AuditEvent
from app.core.database import AsyncSessionLocal
from tests.conftest import unique_email

ANCIEN = "Lune-Verte-2026"
NOUVEAU = "Soleil-Rouge-2027"
URL_CHANGEMENT = "/api/v1/auth/change-password"
ACTION_AUDIT = "auth.password.change"


def _ip_unique() -> dict:
    ip = str(ipaddress.IPv4Address(0x0A900000 | (uuid.uuid4().int & 0xFFFFFF)))
    return {"X-Forwarded-For": ip}


async def _inscrire_et_connecter(client: AsyncClient, email: str, mot_de_passe: str) -> dict:
    res = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": mot_de_passe, "fullName": "BE018"}
    )
    assert res.status_code == 201, res.text
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": mot_de_passe}, headers=_ip_unique()
    )
    assert login.status_code == 200, login.text
    return login.json()


async def _connexion_possible(client: AsyncClient, email: str, mot_de_passe: str) -> bool:
    res = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": mot_de_passe}, headers=_ip_unique()
    )
    return res.status_code == 200


async def test_ca1_bon_ancien_mot_de_passe_accepte_et_nouveau_relu_valide(client: AsyncClient):
    """CA-1 : avec le bon ancien mot de passe, le nouveau est accepté (200) et
    la connexion avec le nouveau mot de passe réussit ; l'ancien est refusé."""
    email = unique_email()
    session = await _inscrire_et_connecter(client, email, ANCIEN)

    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": ANCIEN, "newPassword": NOUVEAU},
        headers={"Authorization": f"Bearer {session['accessToken']}"},
    )
    assert res.status_code == 200, res.text

    assert await _connexion_possible(client, email, NOUVEAU)
    assert not await _connexion_possible(client, email, ANCIEN)


async def test_ca2_mauvais_ancien_mot_de_passe_refuse_sans_modification(client: AsyncClient):
    """CA-2 (refus) : un mauvais ancien mot de passe renvoie 401 invalid_credentials ;
    le mot de passe reste inchangé (l'ancien fonctionne encore, le nouveau non)."""
    email = unique_email()
    session = await _inscrire_et_connecter(client, email, ANCIEN)

    res = await client.post(
        URL_CHANGEMENT,
        json={"currentPassword": "mauvais-mot-de-passe-42", "newPassword": NOUVEAU},
        headers={"Authorization": f"Bearer {session['accessToken']}"},
    )
    assert res.status_code == 401, res.text
    assert res.json()["error"]["code"] == "invalid_credentials"

    assert await _connexion_possible(client, email, ANCIEN)
    assert not await _connexion_possible(client, email, NOUVEAU)


async def test_ca2_sans_session_le_changement_est_refuse_401(client: AsyncClient):
    """Refus sans session : POST sans jeton renvoie 401 (recommandation QE-SOC-05)."""
    res = await client.post(URL_CHANGEMENT, json={"currentPassword": ANCIEN, "newPassword": NOUVEAU})
    assert res.status_code == 401, res.text


async def test_ca3_isolation_un_utilisateur_ne_change_pas_le_mot_de_passe_d_un_autre(client: AsyncClient):
    """CA-3 (isolation) : la route n'accepte aucun identifiant de cible. Un corps qui
    désigne le compte d'un autre (userId, email) est ignoré : seul le compte de la
    session change, le compte visé garde son mot de passe."""
    email_a, email_b = unique_email(), unique_email()
    session_a = await _inscrire_et_connecter(client, email_a, ANCIEN)
    await _inscrire_et_connecter(client, email_b, ANCIEN)
    b_id = (
        await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {session_a['accessToken']}"})
    ).json()["id"]

    res = await client.post(
        URL_CHANGEMENT,
        json={
            "currentPassword": ANCIEN,
            "newPassword": NOUVEAU,
            "userId": str(uuid.uuid4()),
            "email": email_b,
        },
        headers={"Authorization": f"Bearer {session_a['accessToken']}"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["id"] == b_id

    assert await _connexion_possible(client, email_b, ANCIEN)
    assert not await _connexion_possible(client, email_b, NOUVEAU)
    assert await _connexion_possible(client, email_a, NOUVEAU)


async def test_ca4_audit_une_entree_sans_ancien_ni_nouveau_mot_de_passe(client: AsyncClient, organization: dict):
    """CA-4 : le changement produit exactement une entrée d'audit dans l'organisation
    de l'utilisateur, et aucune valeur de mot de passe (ancien ni nouveau) n'y figure."""
    email = unique_email()
    session = await _inscrire_et_connecter(client, email, ANCIEN)
    headers = {"Authorization": f"Bearer {session['accessToken']}", "X-Organization-Id": organization["id"]}

    res = await client.post(URL_CHANGEMENT, json={"currentPassword": ANCIEN, "newPassword": NOUVEAU}, headers=headers)
    assert res.status_code == 200, res.text

    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                select(AuditEvent).where(
                    AuditEvent.organizationId == uuid.UUID(organization["id"]),
                    AuditEvent.action == ACTION_AUDIT,
                )
            )
        ).scalars().all()

    assert len(lignes) == 1
    contenu = json.dumps(
        {"summary": lignes[0].summary, "changes": lignes[0].changes, "action": lignes[0].action},
        ensure_ascii=False,
    )
    assert ANCIEN not in contenu
    assert NOUVEAU not in contenu
