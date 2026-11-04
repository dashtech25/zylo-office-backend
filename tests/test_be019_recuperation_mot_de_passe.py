"""BE-019 : récupération et réinitialisation du mot de passe (CA-3, CA-4, CA-5, table snake_case).

Les CA-1 (réponse identique, compte absent ou actif) et CA-2 (jeton consommé refusé)
sont couverts par `tests/test_password_reset.py`. Ce fichier couvre les compléments
demandés par la définition et la migration de la table `password_reset_token`.
"""

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text

import app.auth.router as auth_router
from app.auth.models import PasswordResetToken
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.shared.email import memory_outbox
from tests.conftest import unique_email
from tests.test_password_reset import _inscrire, _token_email

MESSAGE_PUBLIC = (
    "Si un compte actif correspond à cette adresse et que le canal e-mail est configuré, "
    "des instructions seront envoyées."
)


@pytest.fixture(autouse=True)
def _mailer_memoire(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    monkeypatch.setattr(settings, "PASSWORD_RESET_URL_BASE", "http://localhost:3001/forgot-password")
    memory_outbox().clear()
    yield
    memory_outbox().clear()


async def _demande(client: AsyncClient, email: str):
    return await client.post("/api/v1/auth/password-reset/request", json={"email": email})


async def _confirme(client: AsyncClient, token: str, nouveau: str):
    return await client.post(
        "/api/v1/auth/password-reset/confirm", json={"token": token, "newPassword": nouveau}
    )


async def test_be019_ca3_jeton_d_un_utilisateur_n_altere_jamais_le_compte_d_un_autre(client: AsyncClient):
    """CA-3 : l'API n'accepte aucun identifiant de compte ; un jeton n'agit que sur son propriétaire.

    Le jeton d'Alice ne doit ni modifier le mot de passe de Bob, ni consommer le jeton
    ouvert de Bob. Le jeton de Bob reste utilisable, mais seulement pour Bob.
    """
    alice = await _inscrire(client)
    bob = await _inscrire(client)
    assert (await _demande(client, alice["email"])).status_code == 202
    token_alice = _token_email(alice["email"])
    assert (await _demande(client, bob["email"])).status_code == 202
    token_bob = _token_email(bob["email"])

    assert (await _confirme(client, token_alice, "AliceNouveau-Passe-611!")).status_code == 204

    bob_ancien = await client.post("/api/v1/auth/login", json={"email": bob["email"], "password": bob["password"]})
    assert bob_ancien.status_code == 200, "le compte de Bob ne doit pas changer"
    alice_nouveau = await client.post(
        "/api/v1/auth/login", json={"email": alice["email"], "password": "AliceNouveau-Passe-611!"}
    )
    assert alice_nouveau.status_code == 200
    alice_ancien = await client.post("/api/v1/auth/login", json={"email": alice["email"], "password": alice["password"]})
    assert alice_ancien.status_code == 401

    async with AsyncSessionLocal() as db:
        ouverts_bob = await db.scalar(
            select(PasswordResetToken.id).where(
                PasswordResetToken.tokenHash.is_not(None),
                PasswordResetToken.usedAt.is_(None),
                PasswordResetToken.revokedAt.is_(None),
            )
        )
        assert ouverts_bob is not None, "le jeton ouvert de Bob ne doit pas être consommé par celui d'Alice"

    assert (await _confirme(client, token_bob, "BobNouveau-Passe-822!")).status_code == 204
    bob_nouveau = await client.post(
        "/api/v1/auth/login", json={"email": bob["email"], "password": "BobNouveau-Passe-822!"}
    )
    assert bob_nouveau.status_code == 200
    alice_toujours = await client.post(
        "/api/v1/auth/login", json={"email": alice["email"], "password": "AliceNouveau-Passe-611!"}
    )
    assert alice_toujours.status_code == 200


async def test_be019_ca4_echec_livraison_smtp_ne_change_pas_la_reponse(client: AsyncClient, monkeypatch):
    """CA-4 : une panne SMTP n'est jamais visible du demandeur (réponse identique au succès)."""
    user = await _inscrire(client)
    succes = await _demande(client, user["email"])
    memory_outbox().clear()

    class SmtpEnPanne:
        async def send(self, message):
            raise ConnectionError("smtp.test.invalid: connexion refusée")

    monkeypatch.setattr(auth_router, "get_email_sender", lambda: SmtpEnPanne())
    echec = await _demande(client, user["email"])

    assert echec.status_code == succes.status_code == 202
    assert echec.json() == succes.json() == {"message": MESSAGE_PUBLIC}
    assert "smtp" not in echec.text.lower()
    assert "refus" not in echec.text.lower()


async def test_be019_ca5_reinitialisation_ecrit_un_audit_sans_mot_de_passe(
    client: AsyncClient, registered_user: dict, organization: dict
):
    """CA-5 : la réinitialisation réussie écrit une entrée d'audit, sans mot de passe ni jeton."""
    nouveau = "AuditZylo-Passe-740!"
    assert (await _demande(client, registered_user["email"])).status_code == 202
    token = _token_email(registered_user["email"])
    assert (await _confirme(client, token, nouveau)).status_code == 204

    async with AsyncSessionLocal() as db:
        lignes = (
            await db.execute(
                text(
                    "SELECT * FROM audit_event WHERE action = :action AND \"organizationId\" = :org"
                ),
                {"action": "auth.password_reset.completed", "org": organization["id"]},
            )
        ).mappings().all()
    assert len(lignes) == 1, "une entrée d'audit par organisation de l'utilisateur"
    contenu = json.dumps([dict(ligne) for ligne in lignes], default=str)
    assert nouveau not in contenu
    assert token not in contenu
    assert "hashedPassword" not in contenu
    assert "passwordHash" not in contenu


async def test_be019_table_password_reset_token_renommee_en_snake_case(client: AsyncClient):
    """Décision propriétaire : la table est `password_reset_token` (snake_case), plus `passwordResetToken`."""
    assert PasswordResetToken.__tablename__ == "password_reset_token"
    async with AsyncSessionLocal() as db:
        noms = set(
            (await db.scalars(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))).all()
        )
    assert "password_reset_token" in noms
    assert "passwordResetToken" not in noms
