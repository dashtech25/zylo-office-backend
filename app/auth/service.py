import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import RefreshToken
from app.auth.schemas import LoginRequest, RegisterRequest
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.identity.models import User


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="email_already_used", message="Cet email est déjà utilisé.", status_code=409)

    user = User(email=data.email, hashedPassword=hash_password(data.password), fullName=data.fullName)
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, data: LoginRequest) -> User:
    result = await db.execute(select(User).where(User.email == data.email))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(data.password, user.hashedPassword):
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
