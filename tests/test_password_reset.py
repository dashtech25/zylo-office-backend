"""Récupération de compte à jeton haché, usage unique et réponse neutre."""

import hashlib
import re
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from app.auth.models import PasswordResetToken, RefreshToken
from app.auth import ratelimit
from app.core.config import ConfigurationSecretError, Settings, settings
from app.core.database import AsyncSessionLocal
from app.identity.models import User
from app.shared.email import memory_outbox
from tests.conftest import unique_email


@pytest.fixture(autouse=True)
def _mailer_memoire(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "memory")
    monkeypatch.setattr(settings, "PASSWORD_RESET_URL_BASE", "http://localhost:3001/forgot-password")
    memory_outbox().clear()
    yield
    memory_outbox().clear()


async def _inscrire(client: AsyncClient, email: str | None = None) -> dict:
    email = email or unique_email()
    password = "InitialStrongPassword-553!"
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "fullName": "Reset Holder"},
    )
    assert register.status_code == 201, register.text
    login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"email": email, "password": password, **login.json()}


def _token_email(email: str) -> str:
    messages = [message for message in memory_outbox() if message.to == email]
    assert len(messages) == 1
    found = re.search(r"#token=([A-Za-z0-9_-]+)", messages[0].body)
    assert found is not None
    return found.group(1)


async def test_reset_compte_actif_reponse_neutre_token_hache_usage_unique_et_sessions_revoquees(client: AsyncClient):
    user = await _inscrire(client)

    response = await client.post("/api/v1/auth/password-reset/request", json={"email": user["email"]})
    assert response.status_code == 202
    assert response.json() == {
        "message": "Si un compte actif correspond à cette adresse et que le canal e-mail est configuré, des instructions seront envoyées."
    }
    assert "token" not in response.text.lower()

    token = _token_email(user["email"])
    delivered = next(message for message in memory_outbox() if message.to == user["email"])
    assert re.search(r"https?://[^\s]+/forgot-password#token=", delivered.body)
    async with AsyncSessionLocal() as db:
        user_row = await db.scalar(select(User).where(User.email == user["email"]))
        rows = list((await db.scalars(
            select(PasswordResetToken).where(PasswordResetToken.userId == user_row.id)
        )).all())
        assert len(rows) == 1
        row = rows[0]
        assert row.userId == user_row.id
        assert row.tokenHash == hashlib.sha256(token.encode()).hexdigest()
        assert row.tokenHash != token
        assert row.expiresAt > datetime.now(timezone.utc)
        refresh = await db.scalar(select(RefreshToken).where(RefreshToken.userId == user_row.id))
        assert refresh is not None and refresh.revokedAt is None

    confirm = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "newPassword": "FreshZyloPassword-934!"},
    )
    assert confirm.status_code == 204
    assert confirm.content == b""
    async with AsyncSessionLocal() as db:
        user_row = await db.scalar(select(User).where(User.email == user["email"]))
        row = (await db.scalars(
            select(PasswordResetToken).where(PasswordResetToken.userId == user_row.id)
        )).one()
        assert row.usedAt is not None
        refresh = await db.scalar(select(RefreshToken).where(RefreshToken.userId == user_row.id))
        assert refresh.revokedAt is not None

    old_refresh = await client.post(
        "/api/v1/auth/refresh", json={"refreshToken": user["refreshToken"]}
    )
    assert old_refresh.status_code == 401
    old_login = await client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": user["password"]}
    )
    assert old_login.status_code == 401
    new_login = await client.post(
        "/api/v1/auth/login", json={"email": user["email"], "password": "FreshZyloPassword-934!"}
    )
    assert new_login.status_code == 200

    reused = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "newPassword": "DifferentFreshPassword-445!"},
    )
    assert reused.status_code == 400
    assert reused.json()["error"]["code"] == "password_reset_invalid"


async def test_reset_reponse_identique_compte_absent_actif_et_canal_desactive(client: AsyncClient, monkeypatch):
    user = await _inscrire(client)
    active = await client.post("/api/v1/auth/password-reset/request", json={"email": user["email"]})
    absent = await client.post("/api/v1/auth/password-reset/request", json={"email": unique_email()})
    assert active.status_code == absent.status_code == 202
    assert active.json() == absent.json()

    memory_outbox().clear()
    monkeypatch.setattr(settings, "EMAIL_BACKEND", "none")
    disabled = await client.post("/api/v1/auth/password-reset/request", json={"email": user["email"]})
    assert disabled.status_code == 202
    assert disabled.json() == active.json()
    assert memory_outbox() == []
    async with AsyncSessionLocal() as db:
        user_row = await db.scalar(select(User).where(User.email == user["email"]))
        rows = list((await db.scalars(
            select(PasswordResetToken).where(PasswordResetToken.userId == user_row.id)
        )).all())
        assert len(rows) == 1  # Seule la demande précédente a créé un jeton.


async def test_reset_remplace_ancien_jeton_et_refuse_jeton_expire(client: AsyncClient):
    user = await _inscrire(client)
    for _ in range(2):
        response = await client.post("/api/v1/auth/password-reset/request", json={"email": user["email"]})
        assert response.status_code == 202
    messages = [message for message in memory_outbox() if message.to == user["email"]]
    assert len(messages) == 2
    first = re.search(r"#token=([A-Za-z0-9_-]+)", messages[0].body).group(1)
    second = re.search(r"#token=([A-Za-z0-9_-]+)", messages[1].body).group(1)
    assert first != second
    async with AsyncSessionLocal() as db:
        user_row = await db.scalar(select(User).where(User.email == user["email"]))
        rows = list((await db.scalars(
            select(PasswordResetToken)
            .where(PasswordResetToken.userId == user_row.id)
            .order_by(PasswordResetToken.createdAt)
        )).all())
        assert len(rows) == 2
        assert rows[0].revokedAt is not None
        assert rows[1].revokedAt is None

    stale = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": first, "newPassword": "FreshZyloPassword-934!"},
    )
    assert stale.status_code == 400
    assert stale.json()["error"]["code"] == "password_reset_invalid"


async def test_reset_requests_limitent_ip_et_compte_sans_conserver_email(client: AsyncClient, monkeypatch):
    email = unique_email()
    client_ip = f"10.25.{uuid.uuid4().int % 255}.{uuid.uuid4().int % 255}"
    monkeypatch.setattr(ratelimit, "adresse_client", lambda _request: client_ip)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT", 2)
    for _ in range(2):
        response = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
        assert response.status_code == 202
    limited = await client.post("/api/v1/auth/password-reset/request", json={"email": email})
    assert limited.status_code == 429

    # Le limiteur ne conserve que les hash IP/compte, jamais l'adresse en clair.
    from app.auth.models import LoginAttempt

    async with AsyncSessionLocal() as db:
        assert await db.scalar(select(LoginAttempt.id).where(LoginAttempt.action == "password_reset")) is not None
        rows = list((await db.scalars(select(LoginAttempt).where(LoginAttempt.action == "password_reset"))).all())
        assert all(email not in row.keyHash for row in rows)


def test_smtp_sender_utilise_starttls_sans_reseau_reel(monkeypatch):
    from app.shared import email as email_module

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self, context):
            calls.append(("starttls", isinstance(context, type(email_module.ssl.create_default_context()))))

        def login(self, username, password):
            calls.append(("login", username, password))

        def send_message(self, mime):
            calls.append(("message", mime["To"], mime["Subject"], mime.get_content()))

    monkeypatch.setattr(settings, "EMAIL_SMTP_HOST", "smtp.test.invalid")
    monkeypatch.setattr(settings, "EMAIL_SMTP_PORT", 587)
    monkeypatch.setattr(settings, "EMAIL_SMTP_USERNAME", "smtp-user")
    monkeypatch.setattr(settings, "EMAIL_SMTP_PASSWORD", SecretStr("smtp-password-test"))
    monkeypatch.setattr(settings, "EMAIL_SMTP_FROM_ADDRESS", "security@example.com")
    monkeypatch.setattr(settings, "EMAIL_SMTP_TIMEOUT_SECONDS", 8)
    monkeypatch.setattr(email_module.smtplib, "SMTP", FakeSMTP)

    sender = email_module.SmtpEmailSender()
    sender._send_sync(email_module.EmailMessage("person@example.com", "Sujet", "Contenu"))
    assert calls[0] == ("connect", "smtp.test.invalid", 587, 8)
    assert calls[1] == ("ehlo",)
    assert calls[2] == ("starttls", True)
    assert calls[3] == ("ehlo",)
    assert calls[4] == ("login", "smtp-user", "smtp-password-test")
    assert calls[5][1:] == ("person@example.com", "Sujet", "Contenu\n")


def test_configuration_smtp_refuse_une_route_frontend_inexistante_et_accepte_un_prefixe():
    base = {
        "_env_file": None,
        "ENVIRONMENT": "production",
        "AUTH_PUBLIC_REGISTRATION_ENABLED": False,
        "JWT_SECRET": "password-reset-test-jwt-secret-0123456789abcdef",
        "STORAGE_SIGNED_URL_SECRET": "password-reset-test-storage-0123456789abcdef",
        "DATABASE_URL": "postgresql+asyncpg://zylo:dedicated-test-secret@localhost:5432/zylo_test",
        "APP_FIELD_ENCRYPTION_KEY": "password-reset-test-field-key-0123456789abcdef",
        "EMAIL_BACKEND": "smtp",
        "EMAIL_SMTP_HOST": "smtp.example.test",
        "EMAIL_SMTP_USERNAME": "zylo-test",
        "EMAIL_SMTP_PASSWORD": "not-a-real-secret",
        "EMAIL_SMTP_FROM_ADDRESS": "security@example.test",
    }
    with pytest.raises(ConfigurationSecretError, match="terminer par /forgot-password"):
        Settings(**base, PASSWORD_RESET_URL_BASE="https://example.test/account/reset")

    accepted = Settings(
        **base,
        PASSWORD_RESET_URL_BASE="https://example.test/zylo/forgot-password",
    )
    assert accepted.PASSWORD_RESET_URL_BASE.endswith("/zylo/forgot-password")
