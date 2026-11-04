from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import ratelimit, service
from app.auth.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.auth import password_reset
from app.core.config import settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user_pour_changement_mot_de_passe
from app.core.session_http import (
    NOM_COOKIE_RAFRAICHISSEMENT,
    efface_sessions,
    pose_sessions,
    transition_active,
    verifie_csrf_et_origine,
)
from app.identity import invitations
from app.identity.models import User
from app.identity.schemas import AccountActivatedResponse, ActivateAccountRequest
from app.shared.email import get_email_sender

router = APIRouter()

# Intention (T-012) : seuls les échecs d'identifiants sont comptés pour la
# limitation de débit. Une erreur serveur ou une validation n'est jamais comptée.
_CODES_ECHEC_IDENTIFIANTS = {"invalid_credentials", "invalid_refresh_token", "email_already_used"}


def _est_echec_identifiants(exc: Exception) -> bool:
    if isinstance(exc, AppError):
        return exc.code in _CODES_ECHEC_IDENTIFIANTS
    return isinstance(exc, HTTPException) and exc.status_code == 401


def _reponse_de_session(response: Response, acces: str, rafraichissement: str) -> TokenResponse:
    """Pose les cookies de session et construit le corps.

    Pendant la transition, le corps garde les jetons (clients existants). Après,
    il ne contient plus aucun jeton : le navigateur les reçoit uniquement en cookies.
    `Cache-Control: no-store` : une réponse porteuse de session ne doit être mise
    en cache par aucun intermédiaire.
    """
    pose_sessions(response, acces, rafraichissement)
    response.headers["Cache-Control"] = "no-store"
    if transition_active():
        return TokenResponse(accessToken=acces, refreshToken=rafraichissement)
    return TokenResponse(tokenType=None)


def _jeton_de_rafraichissement(request: Request, data: RefreshRequest | None) -> tuple[str | None, bool]:
    """Jeton de rafraîchissement et son origine. Le cookie est prioritaire ; le corps
    n'est accepté que pendant la transition. Le booléen déclenche le contrôle CSRF."""
    cookie = request.cookies.get(NOM_COOKIE_RAFRAICHISSEMENT)
    if cookie:
        return cookie, True
    if data is not None and data.refreshToken and transition_active():
        return data.refreshToken, False
    return None, False


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)) -> User:
    if not settings.AUTH_PUBLIC_REGISTRATION_ENABLED:
        # Ne pas exposer le libre-service tant que l'inscription et la
        # vérification e-mail n'ont pas été approuvées. Les invitations restent
        # gérées par le parcours séparé d'activation.
        raise AppError(code="registration_disabled", message="Inscription publique désactivée.", status_code=404)
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_REGISTER, data.email)
    try:
        return await service.register_user(db, data)
    except AppError as exc:
        if _est_echec_identifiants(exc):
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_REGISTER, data.email)
        raise


@router.post("/login", response_model=TokenResponse, response_model_exclude_none=True)
async def login(
    data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
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
    return _reponse_de_session(response, access_token, refresh_token)


@router.post("/refresh", response_model=TokenResponse, response_model_exclude_none=True)
async def refresh(
    request: Request, response: Response, data: RefreshRequest | None = None, db: AsyncSession = Depends(get_db)
) -> TokenResponse:
    jeton, par_cookie = _jeton_de_rafraichissement(request, data)
    if jeton is None:
        raise AppError(code="invalid_refresh_token", message="Refresh token invalide, expiré ou révoqué.", status_code=401)
    if par_cookie:
        # Le cookie part tout seul : sans ce contrôle, un site tiers pourrait
        # faire tourner la session de la victime à son insu.
        verifie_csrf_et_origine(request)
    # Pas d'email dans une requête de refresh : la limite porte sur l'IP seule.
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_REFRESH, None)
    try:
        access_token, refresh_token = await service.rotate_refresh_token(db, jeton)
    except (AppError, HTTPException) as exc:
        if _est_echec_identifiants(exc):
            # Rollback avant de compter : rotate_refresh_token a pu marquer un jeton
            # comme révoqué avant de constater que l'utilisateur est inactif.
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_REFRESH, None)
        raise
    return _reponse_de_session(response, access_token, refresh_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, data: RefreshRequest | None = None, db: AsyncSession = Depends(get_db)
) -> None:
    """Révoque le refresh token de la session et efface les cookies.

    Sans jeton (cookie absent, corps absent), la réponse reste 204 : une déconnexion
    déjà faite n'est pas une erreur. Une requête portée par cookie sans CSRF valide
    est refusée AVANT toute écriture, cookies compris.
    """
    jeton, par_cookie = _jeton_de_rafraichissement(request, data)
    if par_cookie:
        verifie_csrf_et_origine(request)
    if jeton is not None:
        await service.revoke_refresh_token(db, jeton)
    efface_sessions(response)
    response.headers["Cache-Control"] = "no-store"


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user_pour_changement_mot_de_passe)) -> User:
    # Accessible même si un changement de mot de passe est requis : le frontend
    # lit `mustChangePassword` ici pour afficher l'écran de changement.
    return current_user


@router.post("/change-password", response_model=UserResponse)
async def change_password(
    data: ChangePasswordRequest,
    request: Request,
    current_user: User = Depends(get_current_user_pour_changement_mot_de_passe),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Session courante : le corps l'indique, sinon le cookie de rafraîchissement.
    # Elle reste ouverte ; toutes les autres sessions sont révoquées (T-013, T-020).
    session_courante = data.refreshToken or request.cookies.get(NOM_COOKIE_RAFRAICHISSEMENT)
    return await service.change_password(
        db, current_user, data.currentPassword, data.newPassword, refresh_token=session_courante
    )


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestResponse,
    status_code=202,
    summary="Demander la réinitialisation du mot de passe (réponse anti-énumération)",
)
async def request_password_reset(
    data: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> PasswordResetRequestResponse:
    email = str(data.email).strip().lower()
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_PASSWORD_RESET, email)
    sender = get_email_sender()
    prepared = await password_reset.prepare_password_reset(db, email, sender_available=sender is not None)
    # Chaque demande est comptée (compte connu ou non) afin de conserver un
    # comportement anti-énumération et de limiter IP + adresse sans stocker l'e-mail.
    await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_PASSWORD_RESET, email)
    if prepared is not None and sender is not None:
        message, _user_id = prepared
        background_tasks.add_task(password_reset.deliver_reset_message, sender, message)
    return PasswordResetRequestResponse(message=password_reset.MESSAGE_PUBLIC)


@router.post(
    "/password-reset/confirm",
    status_code=204,
    summary="Confirmer une réinitialisation avec un jeton à usage unique",
)
async def confirm_password_reset(
    data: PasswordResetConfirmRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_PASSWORD_RESET_CONFIRM, None)
    try:
        await password_reset.confirm_password_reset(db, data.token, data.newPassword)
    except AppError as exc:
        if exc.code == "password_reset_invalid":
            await db.rollback()
            await ratelimit.enregistre_echec(
                db, request, ratelimit.ACTION_PASSWORD_RESET_CONFIRM, None
            )
        raise
    await ratelimit.enregistre_succes_ip(db, request, ratelimit.ACTION_PASSWORD_RESET_CONFIRM)
    return Response(status_code=204)


@router.post("/activate", response_model=AccountActivatedResponse, summary="Activer un compte créé par une organisation (lien à usage unique)")
async def activate(
    data: ActivateAccountRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AccountActivatedResponse:
    """T-049 : le titulaire choisit son mot de passe avec le jeton reçu hors API.
    Sans authentification : le jeton est la seule preuve. Un jeton inconnu,
    expiré, révoqué ou déjà utilisé répond `400 invitation_invalid` sans détail;
    les échecs répétés par IP reçoivent `429 rate_limited`."""
    await ratelimit.verifie_limites(db, request, ratelimit.ACTION_ACTIVATE, None)
    try:
        user = await invitations.activate_account(db, data.token, data.password)
    except AppError as exc:
        if exc.code == "invitation_invalid":
            # Le jeton ne doit pas permettre un essai illimité. Les erreurs de
            # politique de mot de passe (422) ne sont pas comptées : le titulaire
            # a déjà prouvé qu'il possède un jeton valide.
            await db.rollback()
            await ratelimit.enregistre_echec(db, request, ratelimit.ACTION_ACTIVATE, None)
        raise
    await ratelimit.enregistre_succes_ip(db, request, ratelimit.ACTION_ACTIVATE)
    return AccountActivatedResponse(id=user.id, email=user.email, status=user.status)
