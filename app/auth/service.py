import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.auth.models import RefreshToken
from app.auth.politique_mot_de_passe import MESSAGE_IDENTIQUE, PolitiqueMotDePasseErreur, erreur_api, verifie_mot_de_passe
from app.auth.schemas import LoginRequest, RegisterRequest
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.identity.models import OrganizationUser, User


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

    Effet sur les jetons d'accès : la révocation ferme la famille de la session.
    Le jeton d'accès d'une session révoquée est refusé immédiatement (vérification
    de la famille à chaque requête, voir `app.core.security`). La session conservée
    (`sauf_refresh_token`) garde sa famille ouverte."""
    maintenant = datetime.now(timezone.utc)
    requete = update(RefreshToken).where(RefreshToken.userId == user_id, RefreshToken.revokedAt.is_(None))
    if sauf_refresh_token is not None:
        requete = requete.where(RefreshToken.tokenHash != _hash_token(sauf_refresh_token))
    await db.execute(requete.values(revokedAt=maintenant))


ACTION_CHANGEMENT_MOT_DE_PASSE = "auth.password.change"


async def change_password(
    db: AsyncSession, user: User, current_password: str, new_password: str, refresh_token: str | None = None
) -> User:
    """Change le mot de passe du compte connecté (BE-018).

    Ordre des contrôles, chacun bloquant avant toute écriture :
    1. l'ancien mot de passe doit correspondre (401 `invalid_credentials`, sans
       modification : CA-2) ;
    2. le nouveau passe la politique commune (422 `password_policy_violation`) ;
    3. le nouveau ne peut pas être identique à l'ancien (422).

    Effets, dans une seule transaction :
    - le condensat bcrypt est remplacé et `mustChangePassword` repasse à faux ;
    - les refresh tokens ouverts sont révoqués, sauf celui de la session courante
      (`refresh_token`), qui reste ouverte ;
    - une entrée d'audit `auth.password.change` est écrite pour chaque organisation
      dont l'utilisateur est membre (BE-007, CA-4). L'entrée ne contient ni l'ancien
      ni le nouveau mot de passe : `changes` ne porte qu'un indicateur sans valeur de mot de passe.
      Un utilisateur sans appartenance n'a aucune organisation sous laquelle
      journaliser : aucune entrée n'est alors écrite (l'écriture d'audit exige une
      organisation, voir `app.audit.service.record_audit_event`).

    Cette fonction ne traite que le compte passé en paramètre : la route ne porte
    aucun identifiant de cible, donc un utilisateur ne peut pas changer le mot de
    passe d'un autre compte (CA-3). L'appelant fournit `user` déjà authentifié.
    """
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
    organisations = (
        await db.execute(select(OrganizationUser.organizationId).where(OrganizationUser.userId == user.id))
    ).scalars().all()
    for organization_id in organisations:
        await record_audit_event(
            db,
            organization_id,
            user.id,
            action=ACTION_CHANGEMENT_MOT_DE_PASSE,
            entity_type="User",
            entity_id=user.id,
            summary="Changement du mot de passe du compte",
            changes={"modificationEffectuee": True},
        )
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


async def issue_tokens(db: AsyncSession, user: User, *, famille: uuid.UUID | None = None) -> tuple[str, str]:
    """Émet un couple de jetons. Sans `famille`, ouvre une nouvelle famille (nouvelle connexion).

    Le jeton d'accès porte la famille : `_utilisateur_actif_du_jeton` le refuse dès
    que la famille n'a plus de refresh token ouvert (déconnexion, réutilisation).
    """
    famille_session = famille or uuid.uuid4()
    access_token = create_access_token(user.id, famille=famille_session)
    refresh_token = create_refresh_token(user.id)

    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    db.add(
        RefreshToken(
            userId=user.id,
            tokenHash=_hash_token(refresh_token),
            familyId=famille_session,
            expiresAt=expires_at,
        )
    )
    await db.commit()

    return access_token, refresh_token


async def revoque_famille(db: AsyncSession, famille: uuid.UUID) -> None:
    """Révoque tous les refresh tokens ouverts d'une famille. Ne commite pas."""
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.familyId == famille, RefreshToken.revokedAt.is_(None))
        .values(revokedAt=datetime.now(timezone.utc))
    )


async def rotate_refresh_token(db: AsyncSession, refresh_token: str) -> tuple[str, str]:
    """Rotation : le jeton présenté est révoqué et un nouveau couple est émis dans la même famille.

    Intention (T-020) :
    - `SELECT ... FOR UPDATE` sérialise deux renouvellements concurrents du même
      jeton : le second attend le commit du premier, puis voit le jeton révoqué.
    - Présenter un jeton déjà révoqué est traité comme une réutilisation (jeton
      volé, rejoué) : toute la famille est révoquée, y compris le jeton légitime
      suivant. Le commit est fait AVANT de lever l'erreur, pour que la révocation
      survive au rollback que fait le routeur sur un échec d'identifiants.
    """
    user_id = decode_token(refresh_token, expected_type="refresh")
    token_hash = _hash_token(refresh_token)

    result = await db.execute(
        select(RefreshToken).where(RefreshToken.tokenHash == token_hash).with_for_update()
    )
    stored = result.scalar_one_or_none()
    if stored is None:
        raise AppError(code="invalid_refresh_token", message="Refresh token invalide, expiré ou révoqué.", status_code=401)
    if stored.revokedAt is not None:
        await revoque_famille(db, stored.familyId)
        await db.commit()
        raise AppError(code="invalid_refresh_token", message="Refresh token invalide, expiré ou révoqué.", status_code=401)
    if stored.expiresAt < datetime.now(timezone.utc):
        raise AppError(code="invalid_refresh_token", message="Refresh token invalide, expiré ou révoqué.", status_code=401)

    stored.revokedAt = datetime.now(timezone.utc)

    result = await db.execute(select(User).where(User.id == user_id, User.status == "active"))
    user = result.scalar_one_or_none()
    if user is None:
        raise AppError(code="invalid_refresh_token", message="Utilisateur introuvable ou inactif.", status_code=401)

    return await issue_tokens(db, user, famille=stored.familyId)


async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
    token_hash = _hash_token(refresh_token)
    result = await db.execute(select(RefreshToken).where(RefreshToken.tokenHash == token_hash))
    stored = result.scalar_one_or_none()
    if stored is not None and stored.revokedAt is None:
        stored.revokedAt = datetime.now(timezone.utc)
        await db.commit()
