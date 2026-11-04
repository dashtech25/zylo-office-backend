"""Activation d'une invitation à rejoindre une organisation (BE-013).

Définition : implementation-backend/tasks-socle-tenant-identite.md, section BE-013.
Route : POST /api/v1/auth/activate, jeton reçu par e-mail (BE-012, table
`organizationInvitation`). Aucune permission requise : le jeton est la seule preuve.

Critères testés :
- CA-1 : un jeton valide crée ou active l'utilisateur et l'appartenance à l'organisation de l'invitation ;
- CA-2 (refus) : un jeton réutilisé est refusé et ne crée rien ;
- CA-3 (refus) : un jeton expiré est refusé ;
- CA-4 (isolation) : un jeton émis pour O1 n'octroie aucune appartenance à O2 ;
- CA-5 : l'activation ouvre une entrée d'audit.

Le jeton est lu dans le message envoyé (boîte mémoire), jamais dans une réponse d'API.
"""

import hashlib
import re
import uuid

from httpx import AsyncClient
from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.shared.email import memory_outbox
from tests.conftest import unique_email

MOT_DE_PASSE = "TestPassword123!"
MOT_DE_PASSE_NOUVEAU = "NouveauMotDePasse456!"
URL_INVITATIONS = "/api/v1/organizations/current/invitations"
URL_ACTIVATION = "/api/v1/auth/activate"
REGEX_JETON = re.compile(r"#token=([A-Za-z0-9_\-]+)")
ACTION_ACCEPTATION = "identity.organization.invitation.accept"


def _entetes(utilisateur: dict, organisation_id: str) -> dict:
    return {"Authorization": f"Bearer {utilisateur['token']}", "X-Organization-Id": organisation_id}


async def _inscrire(client: AsyncClient) -> dict:
    email = unique_email()
    await client.post("/api/v1/auth/register", json={"email": email, "password": MOT_DE_PASSE, "fullName": "Acteur test"})
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": MOT_DE_PASSE})
    token = login.json()["accessToken"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return {"id": me.json()["id"], "email": email, "token": token}


async def _administrateur(client: AsyncClient) -> dict:
    acteur = await _inscrire(client)
    res = await client.post(
        "/api/v1/organizations",
        json={"name": f"Org {uuid.uuid4().hex[:6]}", "slug": f"org-{uuid.uuid4().hex[:10]}"},
        headers={"Authorization": f"Bearer {acteur['token']}"},
    )
    assert res.status_code == 201, res.text
    acteur["organisation"] = res.json()["id"]
    return acteur


async def _inviter(client: AsyncClient, admin: dict, email: str) -> None:
    res = await client.post(
        URL_INVITATIONS,
        json={"email": email, "roleId": None},
        headers=_entetes(admin, admin["organisation"]),
    )
    assert res.status_code == 201, res.text


def _jeton_envoye(email: str) -> str:
    message = [m for m in memory_outbox() if m.to == email][-1]
    correspondance = REGEX_JETON.search(message.body)
    assert correspondance is not None, "le message d'invitation doit contenir le lien avec le jeton"
    return correspondance.group(1)


async def _activer(client: AsyncClient, jeton: str, **donnees):
    return await client.post(URL_ACTIVATION, json={"token": jeton, **donnees})


async def _sql(requete: str, **params) -> list[dict]:
    """Lit la base directement : c'est elle qui fait foi, pas la réponse de l'API."""
    async with AsyncSessionLocal() as db:
        resultat = await db.execute(text(requete), params)
        return [dict(ligne._mapping) for ligne in resultat]


async def _appartenances(user_id: str) -> list[str]:
    lignes = await _sql('SELECT "organizationId" FROM "organizationUser" WHERE "userId" = :u', u=uuid.UUID(user_id))
    return [str(ligne["organizationId"]) for ligne in lignes]


async def _invitation(email: str, organisation_id: str) -> dict:
    lignes = await _sql(
        'SELECT * FROM "organizationInvitation" WHERE email = :e AND "organizationId" = :o',
        e=email,
        o=uuid.UUID(organisation_id),
    )
    assert len(lignes) == 1
    return lignes[0]


async def _utilisateur_par_email(email: str) -> dict | None:
    lignes = await _sql('SELECT * FROM "user" WHERE email = :e', e=email)
    return lignes[0] if lignes else None


async def _nombre_appartenances_totales() -> int:
    return (await _sql('SELECT COUNT(*) AS n FROM "organizationUser"'))[0]["n"]


async def test_jeton_valide_cree_le_compte_et_l_appartenance(client: AsyncClient, monkeypatch):
    """CA-1 : un destinataire sans compte active son compte et rejoint l'organisation."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin, email)
    jeton = _jeton_envoye(email)

    res = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "active"

    utilisateur = await _utilisateur_par_email(email)
    assert utilisateur is not None
    assert utilisateur["status"] == "active"
    assert admin["organisation"] in await _appartenances(str(utilisateur["id"]))
    invitation = await _invitation(email, admin["organisation"])
    assert invitation["status"] == "accepted"


async def test_jeton_valide_active_un_compte_existant_sans_nouveau_mot_de_passe(client: AsyncClient, monkeypatch):
    """CA-1 : une personne ayant déjà un compte rejoint l'organisation sans créer de doublon."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    existant = await _inscrire(client)
    await _inviter(client, admin, existant["email"])
    jeton = _jeton_envoye(existant["email"])

    res = await _activer(client, jeton)
    assert res.status_code == 200, res.text

    assert admin["organisation"] in await _appartenances(existant["id"])
    lignes = await _sql('SELECT COUNT(*) AS n FROM "user" WHERE email = :e', e=existant["email"])
    assert lignes[0]["n"] == 1


async def test_jeton_reutilise_est_refuse_et_ne_cree_rien(client: AsyncClient, monkeypatch):
    """CA-2 : le second usage du même jeton répond 400 et ne modifie aucune appartenance."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin, email)
    jeton = _jeton_envoye(email)
    premier = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    assert premier.status_code == 200, premier.text

    appartenances_avant = await _nombre_appartenances_totales()
    second = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Autre Personne")
    assert second.status_code == 400, second.text
    assert second.json()["error"]["code"] == "invitation_invalid"
    assert await _nombre_appartenances_totales() == appartenances_avant


async def test_jeton_expire_est_refuse(client: AsyncClient, monkeypatch):
    """CA-3 : un jeton dont l'échéance est passée répond 400 et ne crée rien."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin, email)
    jeton = _jeton_envoye(email)
    async with AsyncSessionLocal() as db:
        await db.execute(
            text('UPDATE "organizationInvitation" SET "expiresAt" = now() - interval \'1 hour\' WHERE email = :e'),
            {"e": email},
        )
        await db.commit()

    appartenances_avant = await _nombre_appartenances_totales()
    res = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    assert res.status_code == 400, res.text
    assert res.json()["error"]["code"] == "invitation_invalid"
    assert await _utilisateur_par_email(email) is None
    assert await _nombre_appartenances_totales() == appartenances_avant


async def test_jeton_d_une_organisation_n_ouvre_aucune_appartenance_ailleurs(client: AsyncClient, monkeypatch):
    """CA-4 : le jeton émis pour O1 ne donne aucune appartenance à O2."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin_o1 = await _administrateur(client)
    admin_o2 = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin_o1, email)
    jeton = _jeton_envoye(email)

    res = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    assert res.status_code == 200, res.text

    utilisateur = await _utilisateur_par_email(email)
    appartenances = await _appartenances(str(utilisateur["id"]))
    assert appartenances == [admin_o1["organisation"]]
    assert admin_o2["organisation"] not in appartenances


async def test_activation_ouvre_une_entree_d_audit(client: AsyncClient, monkeypatch):
    """CA-5 : l'acceptation écrit une entrée d'audit pour l'organisation de l'invitation."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin, email)
    jeton = _jeton_envoye(email)

    res = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    assert res.status_code == 200, res.text

    utilisateur = await _utilisateur_par_email(email)
    entrees = await _sql(
        'SELECT "organizationId", "actorUserId" FROM audit_event WHERE action = :a AND "entityId" = :e',
        a=ACTION_ACCEPTATION,
        e=utilisateur["id"],
    )
    assert len(entrees) == 1
    assert str(entrees[0]["organizationId"]) == admin["organisation"]


async def test_jeton_inconnu_et_jeton_utilise_repondent_de_la_meme_facon(client: AsyncClient, monkeypatch):
    """Réponse uniforme : un jeton inconnu et un jeton déjà consommé ne se distinguent pas."""
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    memory_outbox().clear()
    admin = await _administrateur(client)
    email = unique_email()
    await _inviter(client, admin, email)
    jeton = _jeton_envoye(email)
    await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")

    utilise = await _activer(client, jeton, password=MOT_DE_PASSE_NOUVEAU, fullName="Nouvelle Personne")
    inconnu = await _activer(client, "jeton-inconnu-" + uuid.uuid4().hex, password=MOT_DE_PASSE_NOUVEAU, fullName="X Y")
    assert utilise.status_code == inconnu.status_code == 400
    assert utilise.json() == inconnu.json()
    assert hashlib.sha256(jeton.encode()).hexdigest() != jeton
