from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ratelimit, service
from app.auth.schemas import ChangePasswordRequest, LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, UserResponse
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User

router = APIRouter()

# Intention (T-012) : seuls les échecs d'identifiants sont comptés pour la
# limitation de débit. Une erreur serveur ou une validation n'est jamais comptée.
_CODES_ECHEC_IDENTIFIANTS = {"invalid_credentials", "invalid_refresh_token", "email_already_used"}


def _est_echec_identifiants(exc: Exception) -> bool:
    if isinstance(exc, AppError):
        return exc.code in _CODES_ECHEC_IDENTIFIANTS
    return isinstance(exc, HTTPException) and exc.status_code == 401


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> User:
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_REGISTER, data.email)
    try:
        return await service.register_user(db, data)
    except AppError as exc:
        if _est_echec_identifiants(exc):
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_REGISTER, data.email)
        raise


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_LOGIN, data.email)
    try:
        user = await service.authenticate_user(db, data)
    except (AppError, HTTPException) as exc:
        if _est_echec_identifiants(exc):
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_LOGIN, data.email)
        raise
    await ratelimit.enregistre_succes(db, request, ratelimit.ACTION_LOGIN, data.email)
    access_token, refresh_token = await service.issue_tokens(db, user)
    return TokenResponse(accessToken=access_token, refreshToken=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    # Pas d'email dans une requête de refresh : la limite porte sur l'IP seule.
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_REFRESH, None)
    try:
        access_token, refresh_token = await service.rotate_refresh_token(db, data.refreshToken)
    except (AppError, HTTPException) as exc:
        if _est_echec_identifiants(exc):
            # Rollback avant de compter : rotate_refresh_token a pu marquer un jeton
            # comme révoqué avant de constater que l'utilisateur est inactif.
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_REFRESH, None)
        raise
    return TokenResponse(accessToken=access_token, refreshToken=refresh_token)


@router.post("/logout", status_code=204)
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    await service.revoke_refresh_token(db, data.refreshToken)


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/change-password", response_model=UserResponse)
async def change_password(
    data: ChangePasswordRequest, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> User:
    return await service.change_password(db, current_user, data.currentPassword, data.newPassword)
