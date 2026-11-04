"""Flux de récupération de compte par jeton e-mail à usage unique."""

import hashlib
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import PasswordResetToken
from app.auth.politique_mot_de_passe import PolitiqueMotDePasseErreur, erreur_api, verifie_mot_de_passe
from app.auth.service import revoque_sessions
from app.core.config import settings
from app.core.errors import AppError
from app.identity.models import User
from app.shared.email import EmailMessage, EmailSender

logger = logging.getLogger("zylo_office.security")

MESSAGE_PUBLIC = (
    "Si un compte actif correspond à cette adresse et que le canal e-mail est configuré, "
    "des instructions seront envoyées."
)
MESSAGE_EMAIL = "Réinitialisation du mot de passe Zylo Office"


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode("utf-8")).hexdigest()


def _message_reinitialisation(email: str, jeton: str, expire: datetime) -> EmailMessage:
    lien = f"{settings.PASSWORD_RESET_URL_BASE}#token={jeton}"
    body = (
        "Une demande de réinitialisation du mot de passe a été faite pour ce compte.\n\n"
        f"Si vous êtes à l'origine de la demande, choisissez un nouveau mot de passe avant le "
        f"{expire.strftime('%d/%m/%Y %H:%M')} UTC :\n\n{lien}\n\n"
        "Ce lien est à usage unique. Si vous n'avez pas demandé la réinitialisation, ignorez ce message.\n"
    )
    return EmailMessage(to=email, subject=MESSAGE_EMAIL, body=body)


async def prepare_password_reset(
    db: AsyncSession, email: str, *, sender_available: bool
) -> tuple[EmailMessage, uuid.UUID] | None:
    """Prépare et persiste le jeton si le compte et le canal sont disponibles.

    Toujours retourner None pour compte absent/inactif ou canal désactivé permet
    au routeur de garder le même contrat public. Aucun e-mail réel n'est envoyé
    dans cette fonction : l'appelant planifie le transport après le commit.
    """
    if not sender_available:
        return None

    normalized = email.strip().lower()
    user = await db.scalar(
        select(User).where(func.lower(User.email) == normalized, User.status == "active", User.deletedAt.is_(None))
    )
    if user is None:
        return None

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES)

    # Une demande récente remplace les jetons encore ouverts, sans supprimer
    # l'historique d'usage/révocation utile pour audit opérationnel.
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.userId == user.id,
            PasswordResetToken.usedAt.is_(None),
            PasswordResetToken.revokedAt.is_(None),
        )
        .values(revokedAt=now)
    )
    db.add(
        PasswordResetToken(
            userId=user.id,
            tokenHash=_empreinte(token),
            expiresAt=expires_at,
        )
    )
    await db.commit()
    return _message_reinitialisation(user.email, token, expires_at), user.id


async def deliver_reset_message(sender: EmailSender, message: EmailMessage) -> None:
    """Envoi différé et logs sans e-mail, token, corps de message ou secret SMTP."""
    try:
        await sender.send(message)
    except Exception:  # noqa: BLE001 - ne jamais retourner le détail SMTP au demandeur
        logger.warning("password_reset_email_delivery_failed")


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str) -> None:
    now = datetime.now(timezone.utc)
    token_row = await db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.tokenHash == _empreinte(token),
            PasswordResetToken.usedAt.is_(None),
            PasswordResetToken.revokedAt.is_(None),
            PasswordResetToken.expiresAt > now,
        )
    )
    invalid = AppError(
        code="password_reset_invalid",
        message="Le lien de réinitialisation est invalide ou expiré.",
        status_code=400,
    )
    if token_row is None:
        raise invalid

    user = await db.get(User, token_row.userId)
    if user is None or user.status != "active" or user.deletedAt is not None:
        raise invalid

    try:
        verifie_mot_de_passe(new_password, email=user.email, nom_complet=user.fullName)
    except PolitiqueMotDePasseErreur as exc:
        raise erreur_api(exc) from exc

    # La condition d'usage unique est appliquée atomiquement afin que deux
    # confirmations concurrentes ne puissent réussir toutes les deux.
    result = await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.id == token_row.id,
            PasswordResetToken.usedAt.is_(None),
            PasswordResetToken.revokedAt.is_(None),
            PasswordResetToken.expiresAt > now,
        )
        .values(usedAt=now)
        .returning(PasswordResetToken.userId)
    )
    user_id = result.scalar_one_or_none()
    if user_id is None:
        await db.rollback()
        raise invalid

    user = await db.get(User, user_id)
    if user is None or user.status != "active" or user.deletedAt is not None:
        await db.rollback()
        raise invalid

    from app.core.security import hash_password

    user.hashedPassword = hash_password(new_password)
    user.mustChangePassword = False
    await revoque_sessions(db, user.id)
    await db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.userId == user.id,
            PasswordResetToken.id != token_row.id,
            PasswordResetToken.usedAt.is_(None),
            PasswordResetToken.revokedAt.is_(None),
        )
        .values(revokedAt=now)
    )
    await db.commit()

