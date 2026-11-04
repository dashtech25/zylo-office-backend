import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
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
from app.core.session_http import (
    METHODES_SURES,
    NOM_COOKIE_ACCES,
    transition_active,
    verifie_csrf_et_origine,
)
from app.identity.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(
    subject: uuid.UUID, expires_delta: timedelta, token_type: str, famille: uuid.UUID | None = None
) -> str:
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
    if famille is not None:
        # Revendication `fam` : famille de rotation de la session. Elle permet de
        # savoir, à chaque requête, si la session est encore ouverte (BE-005, CA-5).
        payload["fam"] = str(famille)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user_id: uuid.UUID, famille: uuid.UUID | None = None) -> str:
    """Jeton d'accès (JWT court). Intention : `famille` rattache le jeton à la session
    (famille de rotation du refresh token). Sans famille, le jeton n'est plus accepté
    par `_utilisateur_actif_du_jeton` : toute émission doit donc passer la famille."""
    return _create_token(
        user_id, timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES), "access", famille
    )


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


def famille_du_jeton_d_acces(token: str) -> uuid.UUID | None:
    """Famille de rotation portée par un jeton d'accès, ou None si absente ou invalide.

    Intention (BE-005, CA-5) : un jeton d'accès sans famille ne peut pas être rattaché
    à une session ; l'appelant le refuse alors (échec fermé). Le jeton a déjà été
    vérifié par `decode_token` ; cette fonction ne relit que la revendication `fam`.
    """
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
    valeur = payload.get("fam")
    try:
        return uuid.UUID(valeur) if valeur else None
    except (TypeError, ValueError):
        return None


def _jeton_d_acces(request: Request, credentials: HTTPAuthorizationCredentials | None) -> tuple[str | None, bool]:
    """Jeton d'accès de la requête et son origine (en-tête ou cookie).

    Intention (T-037a) : pendant la transition, l'en-tête `Authorization` reste
    prioritaire pour les clients existants. Après la date de fin, il est ignoré :
    seul le cookie `zylo_access` authentifie. Le booléen indique si le jeton vient
    d'un cookie, ce qui déclenche le contrôle CSRF (un en-tête n'est jamais envoyé
    automatiquement par un navigateur, donc il n'expose pas à CSRF).
    """
    if credentials is not None and transition_active():
        return credentials.credentials, False
    cookie = request.cookies.get(NOM_COOKIE_ACCES)
    if cookie:
        return cookie, True
    return None, False


async def _utilisateur_actif_du_jeton(request: Request, credentials: HTTPAuthorizationCredentials | None, db: AsyncSession) -> User:
    jeton, par_cookie = _jeton_d_acces(request, credentials)
    if jeton is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentification requise.")
    if par_cookie and request.method not in METHODES_SURES:
        verifie_csrf_et_origine(request)
    user_id = decode_token(jeton, expected_type="access")
    result = await db.execute(select(User).where(User.id == user_id, User.status == "active", User.deletedAt.is_(None)))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Utilisateur introuvable ou inactif.")
    await _verifie_session_ouverte(db, jeton)
    return user


async def _verifie_session_ouverte(db: AsyncSession, jeton: str) -> None:
    """Refuse (401) un jeton d'accès dont la session est révoquée (BE-005, CA-5).

    Intention : un JWT est sans état, donc sa seule signature ne prouve pas que la
    session existe encore. La session est ouverte tant qu'un refresh token non révoqué
    existe dans la famille du jeton. La déconnexion et la détection de réutilisation
    révoquent toute la famille : les jetons d'accès de cette session cessent alors
    d'être acceptés, sans attendre leur expiration. Échec fermé : sans famille, refus.
    """
    # Import local : app.auth.models dépend de app.core.database, pas de ce module,
    # mais garder le couplage ici évite un import circulaire via app.auth.service.
    from app.auth.models import RefreshToken

    famille = famille_du_jeton_d_acces(jeton)
    if famille is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session invalide.")
    ouvert = await db.execute(
        select(RefreshToken.id).where(
            RefreshToken.familyId == famille,
            RefreshToken.revokedAt.is_(None),
        ).limit(1)
    )
    if ouvert.first() is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session révoquée.")


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Utilisateur authentifié, sans restriction. Intention (T-013) : tant que
    `mustChangePassword` est vrai (mot de passe temporaire), le jeton ne donne
    accès à rien d'autre que le profil et le changement de mot de passe. La
    restriction est appliquée ici, côté backend, et non dans l'interface seule."""
    user = await _utilisateur_actif_du_jeton(request, credentials, db)
    if user.mustChangePassword:
        raise AppError(
            code="password_change_required",
            message="Un changement de mot de passe est requis avant d'accéder à l'application.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    return user


async def get_current_user_pour_changement_mot_de_passe(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Réservée à GET /auth/me et POST /auth/change-password : seuls endpoints
    accessibles tant que `mustChangePassword` est vrai. Ne pas l'utiliser ailleurs."""
    return await _utilisateur_actif_du_jeton(request, credentials, db)
