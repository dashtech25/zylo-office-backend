import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
# PyJWT (T-015) remplace python-jose : format HS256 identique, donc les jetons
# déjà émis restent valides. Voir docs/architecture/securite/surface-api.md.
import jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.identity.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(subject: uuid.UUID, expires_delta: timedelta, token_type: str) -> str:
    now = datetime.now(timezone.utc)
    # jti garantit un token unique même si deux émissions surviennent dans la
    # même seconde pour le même utilisateur (ex: login puis refresh immédiat) —
    # sans ça, deux JWT identiques produiraient le même tokenHash et violeraient
    # la contrainte unique de refreshToken.
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES), "access")


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(user_id, timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS), "refresh")


def decode_token(token: str, expected_type: str) -> uuid.UUID:
    # Intention : `algorithms` est toujours explicite (jamais déduit du jeton) ;
    # c'est la défense contre la confusion d'algorithme (CVE-2024-33663 et suite).
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalide.") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Type de token invalide.")
    return uuid.UUID(payload["sub"])


async def _utilisateur_actif_du_jeton(credentials: HTTPAuthorizationCredentials | None, db: AsyncSession) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    user_id = decode_token(credentials.credentials, expected_type="access")
    result = await db.execute(select(User).where(User.id == user_id, User.status == "active"))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable ou inactif.")
    return user


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Utilisateur authentifié, sans restriction. Intention (T-013) : tant que
    `mustChangePassword` est vrai (mot de passe temporaire), le jeton ne donne
    accès à rien d'autre que le profil et le changement de mot de passe. La
    restriction est appliquée ici, côté backend, et non dans l'interface seule."""
    user = await _utilisateur_actif_du_jeton(credentials, db)
    if user.mustChangePassword:
        raise AppError(
            code="password_change_required",
            message="Un changement de mot de passe est requis avant d'accéder à l'application.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return user


async def get_current_user_pour_changement_mot_de_passe(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Réservée à GET /auth/me et POST /auth/change-password : seuls endpoints
    accessibles tant que `mustChangePassword` est vrai. Ne pas l'utiliser ailleurs."""
    return await _utilisateur_actif_du_jeton(credentials, db)
