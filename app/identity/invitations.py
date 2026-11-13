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

Invitations à rejoindre une organisation (BE-012) : `create_organization_invitation`
et `list_organization_invitations`, routes `/organizations/current/invitations`.
Ce flux vise une adresse, pas forcément un compte : il utilise la table
`organizationInvitation` (et non `userInvitation`). Le jeton n'est envoyé que par
e-mail, stocké haché, et la permission `organization.members.invite` est exigée.
L'acceptation par le destinataire (BE-013) passe par `activate_account` : le lien
envoyé pointe vers la page d'activation, qui appelle `POST /auth/activate`.

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
from app.identity.models import Organization, OrganizationInvitation, OrganizationUser, User, UserInvitation
from app.identity.schemas import (
    CreateOrganizationInvitationRequest,
    CreatedUserResponse,
    CreateUserRequest,
    OrganizationInvitationResponse,
    ReissuedInvitationResponse,
    UserStatusResponse,
)
from app.rbac.models import Role, UserRole
from app.shared.email import EmailMessage, get_email_sender

ACTION_CREATE = "identity.user.create"
ACTION_INVITATION = "identity.user.invitation.reissue"
ACTION_ACTIVATE = "identity.user.activate"
ACTION_SUSPEND = "identity.user.suspend"
ACTION_REACTIVATE = "identity.user.reactivate"
ACTION_ORGANIZATION_INVITATION = "identity.organization.invitation.create"
ACTION_ACCEPTATION_ORGANISATION = "identity.organization.invitation.accept"


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


async def _envoie_message(email: str, sujet: str, corps: str, message_echec: str) -> None:
    """Envoi d'un message d'invitation. Appelé avant le commit : un échec d'envoi
    annule l'écriture (rien n'est à rattraper à la main). Lève une AppError si
    l'envoi n'est pas configuré ou échoue ; `message_echec` est le texte renvoyé
    au client dans ce cas, propre au flux appelant."""
    sender = get_email_sender()
    if sender is None:
        raise _sans_envoi_configure()
    try:
        await sender.send(EmailMessage(to=email, subject=sujet, body=corps))
    except Exception as exc:  # noqa: BLE001 - tout échec de transport est traité de la même façon
        raise AppError(code="email_delivery_failed", message=message_echec, status_code=503) from exc


async def _envoie_invitation(nom_complet: str, email: str, nom_organisation: str, jeton: str, expire: datetime) -> None:
    """Envoi du lien d'activation d'un compte créé (T-021)."""
    await _envoie_message(
        email,
        "Activation de votre compte Zylo Office",
        _corps_du_message(nom_complet, nom_organisation, jeton, expire),
        "L'invitation n'a pas pu être envoyée. Aucun compte n'a été créé.",
    )


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


def _invalide() -> AppError:
    return AppError(code="invitation_invalid", message="Ce lien d'activation est invalide ou expiré.", status_code=400)


async def activate_account(
    db: AsyncSession, jeton: str, mot_de_passe: str | None = None, nom_complet: str | None = None
) -> User:
    """Point d'entrée unique de `POST /auth/activate` (T-049 et BE-013).

    Résolution du jeton : d'abord une invitation à rejoindre une organisation
    (`organizationInvitation`, BE-012), puis un jeton d'activation de compte créé
    (`userInvitation`, T-049). Les deux tables ne partagent aucune empreinte, donc
    l'ordre n'a pas d'effet sur le résultat. Tout jeton inconnu, expiré, utilisé
    ou révoqué répond `invitation_invalid` (400), sans distinguer les cas.

    Le jeton est consommé par une seule mise à jour conditionnelle : deux requêtes
    concurrentes ne peuvent pas réussir toutes les deux.
    """
    maintenant = datetime.now(timezone.utc)
    invitation_org = (
        await db.execute(
            update(OrganizationInvitation)
            .where(
                OrganizationInvitation.tokenHash == _empreinte(jeton),
                OrganizationInvitation.status == "pending",
                OrganizationInvitation.expiresAt > maintenant,
            )
            .values(status="accepted")
            .returning(
                OrganizationInvitation.email,
                OrganizationInvitation.organizationId,
                OrganizationInvitation.roleId,
            )
        )
    ).first()
    if invitation_org is not None:
        return await _accepte_invitation_organisation(db, invitation_org, mot_de_passe, nom_complet, maintenant)
    return await _active_compte_cree(db, jeton, mot_de_passe, maintenant)


async def _accepte_invitation_organisation(
    db: AsyncSession,
    invitation,
    mot_de_passe: str | None,
    nom_complet: str | None,
    maintenant: datetime,
) -> User:
    """Acceptation d'une invitation à rejoindre `invitation.organizationId` (BE-013).

    - Personne sans compte : création d'un compte `active` ; `mot_de_passe` et
      `nom_complet` sont alors obligatoires (422 sinon) et la politique commune
      (T-013) s'applique, e-mail et nom compris.
    - Personne avec un compte actif : aucun nouveau mot de passe n'est demandé ni
      modifié ; le compte rejoint l'organisation. Un compte suspendu, supprimé ou
      en attente d'activation par une autre organisation est refusé (400 uniforme).
    - Appartenance à l'organisation de l'invitation uniquement (CA-4) ; le rôle
      proposé, s'il existe, est attribué dans cette même organisation.
    Le rollback annule la consommation du jeton en cas d'erreur.
    """
    email = invitation.email
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        if not mot_de_passe or not nom_complet:
            await db.rollback()
            raise AppError(
                code="account_details_required",
                message="Le mot de passe et le nom complet sont requis pour créer le compte.",
                status_code=422,
            )
        try:
            verifie_mot_de_passe(mot_de_passe, email=email, nom_complet=nom_complet)
        except PolitiqueMotDePasseErreur as exc:
            await db.rollback()
            raise erreur_api(exc) from exc
        user = User(email=email, fullName=nom_complet, hashedPassword=hash_password(mot_de_passe), status="active")
        db.add(user)
        await db.flush()
    elif user.deletedAt is not None or user.status != "active":
        # Suspendu, supprimé, ou `pending` (compte créé par une organisation, pas
        # encore activé : son titulaire doit d'abord utiliser son propre lien).
        await db.rollback()
        raise _invalide()

    appartenance = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == invitation.organizationId,
            OrganizationUser.userId == user.id,
        )
    )
    if appartenance is None:
        db.add(OrganizationUser(organizationId=invitation.organizationId, userId=user.id))
    if invitation.roleId is not None:
        role_deja_attribue = await db.scalar(
            select(UserRole.id).where(
                UserRole.organizationId == invitation.organizationId,
                UserRole.userId == user.id,
                UserRole.roleId == invitation.roleId,
            )
        )
        if role_deja_attribue is None:
            db.add(
                UserRole(
                    userId=user.id,
                    organizationId=invitation.organizationId,
                    roleId=invitation.roleId,
                    resourceType=None,
                    resourceId=None,
                )
            )
    await record_audit_event(
        db,
        invitation.organizationId,
        user.id,
        action=ACTION_ACCEPTATION_ORGANISATION,
        entity_type="User",
        entity_id=user.id,
        summary=f"Acceptation de l'invitation à rejoindre l'organisation par {email}",
    )
    await db.commit()
    await db.refresh(user)
    return user


async def _active_compte_cree(db: AsyncSession, jeton: str, mot_de_passe: str | None, maintenant: datetime) -> User:
    """Activation d'un compte créé par une organisation (T-049, `userInvitation`)."""
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
    if ligne is None:
        await db.rollback()
        raise _invalide()

    user = await db.get(User, ligne.userId)
    if user is None or user.status != "pending" or user.deletedAt is not None:
        await db.rollback()
        raise _invalide()
    if not mot_de_passe:
        await db.rollback()
        raise AppError(code="password_required", message="Le mot de passe est requis pour activer ce compte.", status_code=422)

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


def _corps_invitation_organisation(nom_organisation: str, jeton: str, expire: datetime) -> str:
    # Le lien pointe vers la page d'activation ; son acceptation est traitée par
    # `activate_account` (BE-013).
    lien = f"{settings.ACTIVATION_URL_BASE}#token={jeton}"
    return (
        f"Vous êtes invité à rejoindre l'organisation « {nom_organisation} » sur Zylo Office.\n"
        f"Le lien suivant est valable jusqu'au {expire.strftime('%d/%m/%Y %H:%M')} (UTC) :\n\n"
        f"{lien}\n\n"
        "Ce lien ne fonctionne qu'une fois. Si vous n'attendiez pas ce message, ignorez-le.\n"
    )


def _vers_reponse_invitation(invitation: OrganizationInvitation) -> OrganizationInvitationResponse:
    return OrganizationInvitationResponse(
        id=invitation.id,
        email=invitation.email,
        roleId=invitation.roleId,
        status=invitation.status,
        expiresAt=invitation.expiresAt,
    )


async def create_organization_invitation(
    db: AsyncSession, actor: User, organization_id: uuid.UUID, data: CreateOrganizationInvitationRequest
) -> OrganizationInvitationResponse:
    """Invite une adresse à rejoindre `organization_id` (BE-012, CA-1, CA-4, CA-5).

    Déroulé : refus si l'envoi n'est pas configuré (503, rien n'est écrit) ;
    rôle proposé vérifié dans l'organisation (404 sinon) ; une seule invitation
    ouverte par adresse et organisation (409) ; insertion avec l'empreinte du
    jeton ; envoi du lien par e-mail ; entrée d'audit ; commit.

    L'envoi a lieu avant le commit : un échec d'envoi annule l'invitation. La
    réponse ne contient jamais le jeton, seul le message au destinataire le porte.
    Les droits sont contrôlés par la route (`organization.members.invite`), pas ici.
    """
    if get_email_sender() is None:
        raise _sans_envoi_configure()

    email = str(data.email).lower()
    maintenant = datetime.now(timezone.utc)
    if data.roleId is not None:
        # Rôle d'une autre organisation : même réponse que pour un rôle absent.
        role_ok = await db.scalar(select(Role.id).where(Role.id == data.roleId, Role.organizationId == organization_id))
        if role_ok is None:
            raise AppError(code="role_not_found", message="Rôle introuvable dans cette organisation.", status_code=404)

    ouverte = await db.scalar(
        select(OrganizationInvitation.id).where(
            OrganizationInvitation.organizationId == organization_id,
            OrganizationInvitation.email == email,
            OrganizationInvitation.status == "pending",
            OrganizationInvitation.expiresAt > maintenant,
        )
    )
    if ouverte is not None:
        raise AppError(
            code="invitation_already_pending",
            message="Une invitation est déjà en attente pour cette adresse.",
            status_code=409,
        )

    organisation = await db.get(Organization, organization_id)
    jeton = secrets.token_urlsafe(32)
    expire = maintenant + timedelta(hours=settings.USER_INVITATION_TTL_HOURS)
    invitation = OrganizationInvitation(
        organizationId=organization_id,
        email=email,
        roleId=data.roleId,
        status="pending",
        tokenHash=_empreinte(jeton),
        expiresAt=expire,
        createdByUserId=actor.id,
    )
    db.add(invitation)
    try:
        await db.flush()
    except IntegrityError as exc:
        # Course entre deux créations pour la même adresse : l'index partiel tranche.
        await db.rollback()
        raise AppError(
            code="invitation_already_pending",
            message="Une invitation est déjà en attente pour cette adresse.",
            status_code=409,
        ) from exc

    try:
        await _envoie_message(
            email,
            f"Invitation à rejoindre {organisation.name} sur Zylo Office",
            _corps_invitation_organisation(organisation.name, jeton, expire),
            "L'invitation n'a pas pu être envoyée. Aucune invitation n'a été créée.",
        )
    except AppError:
        await db.rollback()
        raise

    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_ORGANIZATION_INVITATION,
        entity_type="OrganizationInvitation",
        entity_id=invitation.id,
        summary=f"Invitation de {email} à rejoindre l'organisation",
    )
    reponse = _vers_reponse_invitation(invitation)
    await db.commit()
    return reponse


async def list_organization_invitations(db: AsyncSession, organization_id: uuid.UUID) -> list[OrganizationInvitationResponse]:
    """Invitations `pending` non expirées de l'organisation, les plus anciennes d'abord.
    Filtre strict sur `organizationId` : aucune invitation d'une autre organisation (CA-3)."""
    maintenant = datetime.now(timezone.utc)
    lignes = (
        await db.execute(
            select(OrganizationInvitation)
            .where(
                OrganizationInvitation.organizationId == organization_id,
                OrganizationInvitation.status == "pending",
                OrganizationInvitation.expiresAt > maintenant,
            )
            .order_by(OrganizationInvitation.createdAt)
        )
    ).scalars().all()
    return [_vers_reponse_invitation(ligne) for ligne in lignes]
