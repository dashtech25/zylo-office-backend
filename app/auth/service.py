import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.auth.politique_mot_de_passe import MESSAGE_IDENTIQUE, PolitiqueMotDePasseErreur, erreur_api, verifie_mot_de_passe
from app.auth.schemas import LoginRequest, RegisterRequest
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.identity.models import User


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    from app.identity.service import build_user, check_email_available

    # Intention (T-013) : l'e-mail est stocké en minuscules. L'index unique sur
    # lower(email) empêche deux comptes qui ne diffèrent que par la casse.
    email = data.email.lower()
    await check_email_available(db, email)
    user = build_user(email=email, full_name=data.fullName, hashed_password=hash_password(data.password))
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


async def revoque_sessions(db: AsyncSession, user_id, *, sauf_refresh_token: str | None = None) -> None:
    """Révoque les refresh tokens ouverts de l'utilisateur, sauf celui fourni.
    Ne commite pas : l'appelant reste maître de la transaction.

    Limite connue : un jeton d'accès déjà émis reste valable jusqu'à son
    expiration (JWT_ACCESS_TOKEN_EXPIRE_MINUTES), car il est sans état."""
    maintenant = datetime.now(timezone.utc)
    requete = update(RefreshToken).where(RefreshToken.userId == user_id, RefreshToken.revokedAt.is_(None))
    if sauf_refresh_token is not None:
        requete = requete.where(RefreshToken.tokenHash != _hash_token(sauf_refresh_token))
    await db.execute(requete.values(revokedAt=maintenant))


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str, refresh_token: str | None = None
) -> User:
    """Vérifie le mot de passe actuel (temporaire ou non) avant de le
    remplacer — jamais un changement sans preuve de connaissance de
    l'ancien, même pour lever `mustChangePassword`. Applique la politique
    commune, puis révoque les sessions (le refresh_token fourni reste ouvert)."""
    if not verify_password(current_password, user.hashedPassword):
        raise AppError(code="invalid_credentials", message="Mot de passe actuel incorrect.", status_code=401)
    try:
        verifie_mot_de_passe(new_password, email=user.email, nom_complet=user.fullName)
    except PolitiqueMotDePasseErreur as exc:
        raise erreur_api(exc) from exc
    if verify_password(new_password, user.hashedPassword):
        raise AppError(
            code="password_policy_violation",
            message=MESSAGE_IDENTIQUE,
            status_code=422,
            details=[{"message": MESSAGE_IDENTIQUE}],
        )
    user.hashedPassword = hash_password(new_password)
    user.mustChangePassword = False
    await revoque_sessions(db, user.id, sauf_refresh_token=refresh_token)
    await db.commit()
    await db.refresh(user)
    return user


@lru_cache(maxsize=1)
def _hachage_factice() -> str:
    """Hachage d'un mot de passe aléatoire jamais communiqué.

    Intention (T-012, IAM-015) : compte inconnu et mauvais mot de passe doivent
    prendre le même temps de réponse. Sans cela, l'absence de hachage pour un
    email inconnu révèle l'existence du compte par la latence.
    """
    return hash_password(secrets.token_urlsafe(32))


async def authenticate_user(db: AsyncSession, data: LoginRequest) -> User:
    # Comparaison insensible à la casse : les comptes anciens peuvent avoir une
    # adresse saisie avec des majuscules (voir register_user).
    result = await db.execute(select(User).where(func.lower(User.email) == data.email.lower()))
    user = result.scalar_one_or_none()
    if user is None:
        verify_password(data.password, _hachage_factice())
        raise AppError(code="invalid_credentials", message="Email ou mot de passe incorrect.", status_code=401)
    if not verify_password(data.password, user.hashedPassword):
        raise AppError(code="invalid_credentials", message="Email ou mot de passe incorrect.", status_code=401)
    if user.status != "active":
        raise AppError(code="account_inactive", message="Ce compte n'est pas actif.", status_code=403)
    return user


async def issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    access_token = create_access_token(user.id)
    refresh_token = create_refresh_token(user.id)

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(RefreshToken(userId=user.id, tokenHash=_hash_token(refresh_token), expiresAt=expires_at))
    await db.commit()

    return access_token, refresh_token


async def rotate_refresh_token(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    user_id = decode_token(refresh_token, expected_type="refresh")
    token_hash = _hash_token(refresh_token)

    result = await db.execute(select(RefreshToken).where(RefreshToken.tokenHash == token_hash))
    stored = result.scalar_one_or_none()
    if stored is None or stored.revokedAt is not None or stored.expiresAt < datetime.now(timezone.utc):
        raise AppError(code="invalid_refresh_token", message="Refresh token invalide, expiré ou révoqué.", status_code=401)

    stored.revokedAt = datetime.now(timezone.utc)

    result = await db.execute(select(User).where(User.id == user_id, User.status == "active"))
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(code="invalid_refresh_token", message="Utilisateur introuvable ou inactif.", status_code=401)

    return await issue_tokens(db, user)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    token_hash = _hash_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.tokenHash == token_hash))
    stored = result.scalar_one_or_none()
    if stored is not None and stored.revokedAt is None:
        stored.revokedAt = datetime.now(timezone.utc)
        await db.commit()
