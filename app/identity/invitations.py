"""Création d'un compte par une organisation, invitation et activation (T-021, T-049, T-048).

Flux :
1. `create_user_account` : un utilisateur doté de `identity.user.manage` crée un
   compte `pending` dans SON organisation. Le mot de passe de ce compte est une
   valeur aléatoire jamais communiquée : aucun secret ne circule entre le
   créateur et le titulaire.
2. Un jeton d'activation (256 bits) est envoyé au titulaire via `app/shared/email.py`.
   Seule son empreinte SHA-256 est stockée. Il expire après
   `USER_INVITATION_TTL_HOURS` et ne sert qu'une fois.
3. `activate_account` : le titulaire choisit son mot de passe avec le jeton ;
   le compte passe `active`. Le créateur ne reçoit jamais le jeton.
4. `update_user_status` : désactivation réversible (sessions révoquées) et
   réactivation. Aucune suppression physique.

Décision de sécurité : un compte `User` est global (une seule identité pour
toutes les organisations). Une désactivation décidée par une organisation
atteindrait donc aussi les autres organisations de la personne. Elle est
refusée lorsque la personne appartient à une autre organisation (409) : la
désactivation inter-organisations relève d'une décision distincte.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.auth.models import RefreshToken
from app.auth.politique_mot_de_passe import PolitiqueMotDePasseErreur, erreur_api, verifie_mot_de_passe
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.identity.models import Organization, OrganizationUser, User, UserInvitation
from app.identity.schemas import CreateUserRequest, CreatedUserResponse, ReissuedInvitationResponse, UserStatusResponse
from app.rbac.models import Role, UserRole
from app.shared.email import EmailMessage, get_email_sender

ACTION_CREATE = "identity.user.create"
ACTION_INVITATION = "identity.user.invitation.reissue"
ACTION_ACTIVATE = "identity.user.activate"
ACTION_SUSPEND = "identity.user.suspend"
ACTION_REACTIVATE = "identity.user.reactivate"


def _empreinte(jeton: str) -> str:
    return hashlib.sha256(jeton.encode()).hexdigest()


def _sans_envoi_configure() -> AppError:
    return AppError(
        code="user_creation_disabled",
        message="La création de compte est désactivée : l'envoi des invitations n'est pas configuré.",
        status_code=503,
    )


def _corps_du_message(nom_complet: str, nom_organisation: str, jeton: str, expire: datetime) -> str:
    lien = f"{settings.ACTIVATION_URL_BASE}#token={jeton}"
    return (
        f"Bonjour {nom_complet},\n\n"
        f"Un compte vous a été créé dans l'organisation « {nom_organisation} » sur Zylo Office.\n"
        f"Activez-le et choisissez votre mot de passe avant le {expire.strftime('%d/%m/%Y %H:%M')} (UTC) :\n\n"
        f"{lien}\n\n"
        "Ce lien ne fonctionne qu'une fois. Si vous n'attendiez pas ce message, ignorez-le.\n"
    )


async def _emet_invitation(db: AsyncSession, organization_id: uuid.UUID, user: User, createur_id: uuid.UUID) -> tuple[str, datetime]:
    """Révoque les jetons ouverts du compte, puis en crée un nouveau. Retourne le jeton
    en clair (à transmettre à l'envoi uniquement) et son échéance."""
    maintenant = datetime.now(timezone.utc)
    await db.execute(
        update(UserInvitation)
        .where(UserInvitation.userId == user.id, UserInvitation.usedAt.is_(None), UserInvitation.revokedAt.is_(None))
        .values(revokedAt=maintenant)
    )
    jeton = secrets.token_urlsafe(32)
    expire = maintenant + timedelta(hours=settings.USER_INVITATION_TTL_HOURS)
    db.add(
        UserInvitation(
            organizationId=organization_id,
            userId=user.id,
            createdByUserId=createur_id,
            tokenHash=_empreinte(jeton),
            expiresAt=expire,
        )
    )
    await db.flush()
    return jeton, expire


async def _envoie_invitation(nom_complet: str, email: str, nom_organisation: str, jeton: str, expire: datetime) -> None:
    """Envoi avant le commit : un échec d'envoi annule la création (rien n'est à
    rattraper à la main). Lève une AppError si l'envoi échoue."""
    sender = get_email_sender()
    if sender is None:
        raise _sans_envoi_configure()
    try:
        await sender.send(
            EmailMessage(
                to=email,
                subject="Activation de votre compte Zylo Office",
                body=_corps_du_message(nom_complet, nom_organisation, jeton, expire),
            )
        )
    except Exception as exc:  # noqa: BLE001 - tout échec de transport est traité de la même façon
        raise AppError(
            code="email_delivery_failed",
            message="L'invitation n'a pas pu être envoyée. Aucun compte n'a été créé.",
            status_code=503,
        ) from exc


async def _membre(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
    """Cible membre de l'organisation (sinon 404 uniforme, sans énumération)."""
    appartenance = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == user_id
        )
    )
    user = await db.get(User, user_id) if appartenance is not None else None
    if user is None or user.deletedAt is not None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable dans cette organisation.", status_code=404)
    return user


async def create_user_account(
    db: AsyncSession, actor: User, organization_id: uuid.UUID, data: CreateUserRequest
) -> CreatedUserResponse:
    if get_email_sender() is None:
        # Refus avant toute écriture : pas de compte sans canal d'activation.
        raise _sans_envoi_configure()

    organisation = await db.get(Organization, organization_id)
    email = str(data.email).lower()
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        # Message générique : ne dit pas si le compte existe ailleurs (voir docs/architecture/securite/creation-utilisateurs.md).
        raise AppError(
            code="email_already_used",
            message="Un compte ne peut pas être créé avec cette adresse.",
            status_code=409,
        )

    user = User(
        email=email,
        fullName=data.fullName,
        # Mot de passe inutilisable : valeur aléatoire que personne ne connaît.
        hashedPassword=hash_password(secrets.token_urlsafe(48)),
        status="pending",
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Course entre deux créations de la même adresse : la contrainte unique tranche.
        await db.rollback()
        raise AppError(
            code="email_already_used",
            message="Un compte ne peut pas être créé avec cette adresse.",
            status_code=409,
        ) from exc

    db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    jeton, expire = await _emet_invitation(db, organization_id, user, actor.id)
    try:
        await _envoie_invitation(user.fullName, email, organisation.name, jeton, expire)
    except AppError:
        await db.rollback()
        raise

    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_CREATE,
        entity_type="User",
        entity_id=user.id,
        summary=f"Création du compte {email} (en attente d'activation)",
        changes={"status": {"before": None, "after": "pending"}},
    )
    await db.commit()
    return CreatedUserResponse(
        id=user.id,
        email=user.email,
        fullName=user.fullName,
        status=user.status,
        organizationId=organization_id,
        invitationExpiresAt=expire,
    )


async def reissue_invitation(
    db: AsyncSession, actor: User, organization_id: uuid.UUID, user_id: uuid.UUID
) -> ReissuedInvitationResponse:
    """Nouveau lien pour un compte encore `pending` (jeton expiré ou perdu). L'ancien
    jeton est révoqué ; la réponse ne contient jamais le jeton."""
    if get_email_sender() is None:
        raise _sans_envoi_configure()
    user = await _membre(db, organization_id, user_id)
    if user.status != "pending":
        raise AppError(code="user_not_pending", message="Ce compte est déjà activé.", status_code=409)

    organisation = await db.get(Organization, organization_id)
    jeton, expire = await _emet_invitation(db, organization_id, user, actor.id)
    try:
        await _envoie_invitation(user.fullName, user.email, organisation.name, jeton, expire)
    except AppError:
        await db.rollback()
        raise

    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_INVITATION,
        entity_type="User",
        entity_id=user.id,
        summary=f"Nouvelle invitation pour le compte {user.email}",
    )
    await db.commit()
    return ReissuedInvitationResponse(userId=user.id, invitationExpiresAt=expire)


async def activate_account(db: AsyncSession, jeton: str, mot_de_passe: str) -> User:
    """Activation par jeton à usage unique. Le jeton est consommé par une seule
    mise à jour conditionnelle (usedAt, expiration, non révoqué) : deux requêtes
    concurrentes ne peuvent pas réussir toutes les deux. Toute erreur répond
    `invitation_invalid` (400), sans distinguer inconnu, expiré, utilisé ou révoqué."""
    maintenant = datetime.now(timezone.utc)
    resultat = await db.execute(
        update(UserInvitation)
        .where(
            UserInvitation.tokenHash == _empreinte(jeton),
            UserInvitation.usedAt.is_(None),
            UserInvitation.revokedAt.is_(None),
            UserInvitation.expiresAt > maintenant,
        )
        .values(usedAt=maintenant)
        .returning(UserInvitation.userId, UserInvitation.organizationId)
    )
    ligne = resultat.first()
    invalide = AppError(code="invitation_invalid", message="Ce lien d'activation est invalide ou expiré.", status_code=400)
    if ligne is None:
        await db.rollback()
        raise invalide

    user = await db.get(User, ligne.userId)
    if user is None or user.status != "pending" or user.deletedAt is not None:
        await db.rollback()
        raise invalide

    # Politique commune (T-013), vérifiée une fois le titulaire connu : e-mail et
    # nom interdits dans le mot de passe. En cas de refus, le rollback annule la
    # consommation du jeton : le titulaire peut réessayer avec le même lien.
    try:
        verifie_mot_de_passe(mot_de_passe, email=user.email, nom_complet=user.fullName)
    except PolitiqueMotDePasseErreur as exc:
        await db.rollback()
        raise erreur_api(exc) from exc
    user.hashedPassword = hash_password(mot_de_passe)
    user.status = "active"
    await db.execute(
        update(UserInvitation)
        .where(UserInvitation.userId == user.id, UserInvitation.usedAt.is_(None), UserInvitation.revokedAt.is_(None))
        .values(revokedAt=maintenant)
    )
    await record_audit_event(
        db,
        ligne.organizationId,
        user.id,
        action=ACTION_ACTIVATE,
        entity_type="User",
        entity_id=user.id,
        summary=f"Activation du compte {user.email} par son titulaire",
        changes={"status": {"before": "pending", "after": "active"}},
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _autres_proprietaires_actifs(db: AsyncSession, organization_id: uuid.UUID, exclu: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count(func.distinct(UserRole.userId)))
            .join(Role, Role.id == UserRole.roleId)
            .join(User, User.id == UserRole.userId)
            .where(
                UserRole.organizationId == organization_id,
                Role.organizationId == organization_id,
                Role.code == "owner",
                User.status == "active",
                User.deletedAt.is_(None),
                UserRole.userId != exclu,
            )
        )
    ) or 0


async def _est_proprietaire(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return (
        await db.scalar(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.roleId)
            .where(UserRole.organizationId == organization_id, Role.code == "owner", UserRole.userId == user_id)
            .limit(1)
        )
    ) is not None


async def update_user_status(
    db: AsyncSession, actor: User, organization_id: uuid.UUID, user_id: uuid.UUID, statut: str
) -> UserStatusResponse:
    user = await _membre(db, organization_id, user_id)

    if user.id == actor.id:
        raise AppError(code="self_status_change_forbidden", message="Vous ne pouvez pas modifier votre propre statut.", status_code=409)
    if user.status == "pending":
        raise AppError(code="user_not_activated", message="Ce compte n'a pas encore été activé.", status_code=409)
    if user.status == statut:
        return UserStatusResponse(id=user.id, email=user.email, fullName=user.fullName, status=user.status)

    if statut == "suspended":
        autres = await db.scalar(
            select(func.count(OrganizationUser.id))
            .join(User, User.id == OrganizationUser.userId)
            .join(Organization, Organization.id == OrganizationUser.organizationId)
            .where(
                OrganizationUser.userId == user.id,
                OrganizationUser.organizationId != organization_id,
                User.deletedAt.is_(None),
                Organization.deletedAt.is_(None),
            )
        )
        if autres:
            raise AppError(
                code="user_member_of_other_organizations",
                message="Ce compte appartient aussi à une autre organisation : sa désactivation n'est pas disponible ici.",
                status_code=409,
            )
        if await _est_proprietaire(db, organization_id, user.id) and await _autres_proprietaires_actifs(db, organization_id, user.id) == 0:
            raise AppError(code="last_owner", message="Impossible de suspendre le dernier propriétaire actif.", status_code=409)

    avant = user.status
    user.status = statut
    maintenant = datetime.now(timezone.utc)
    if statut == "suspended":
        # Révocation immédiate des sessions : refresh tokens. L'accès est coupé
        # aussi pour les jetons d'accès restants, car get_current_user exige `active`.
        await db.execute(
            update(RefreshToken)
            .where(RefreshToken.userId == user.id, RefreshToken.revokedAt.is_(None))
            .values(revokedAt=maintenant)
        )
    action = ACTION_SUSPEND if statut == "suspended" else ACTION_REACTIVATE
    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=action,
        entity_type="User",
        entity_id=user.id,
        summary=f"Statut du compte {user.email} : {avant} → {statut}",
        changes={"status": {"before": avant, "after": statut}},
    )
    await db.commit()
    await db.refresh(user)
    return UserStatusResponse(id=user.id, email=user.email, fullName=user.fullName, status=user.status)
