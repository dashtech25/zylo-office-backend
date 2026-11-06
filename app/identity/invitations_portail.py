"""Invitations d'organisation du portail (BE-105).

Flux :
1. `create_invitation` : un membre actif doté de `organization.members.invite` (contrôlé par la
   route via `POLITIQUE_PORTAIL`) invite une identité existante. L'invitation est `pending`,
   expire après `USER_INVITATION_TTL_HOURS`, et l'événement `MemberInvited` est écrit dans
   l'outbox dans la même transaction.
2. `accept_invitation` : seule l'identité destinataire peut accepter (403 sinon). Une invitation
   `expired`, `revoked` ou `accepted`, ou échue, refuse l'acceptation (409) sans rien modifier.
   L'acceptation crée l'appartenance `organization_user`, attribue le rôle proposé s'il existe,
   passe l'invitation à `accepted` et écrit `InvitationAccepted`.

Règles de sécurité :
- Aucun rôle Owner par invitation (QE-POR-04) : refus 403 `owner_role_forbidden`.
- Le rôle proposé doit appartenir à l'organisation de l'invitation (404 sinon).
- Aucun transfert de propriété implicite : ce module n'écrit jamais le rôle Owner.

Les autorisations (permission, appartenance) relèvent de la route ; ce module suppose une
portée déjà validée (`OrgScope`) pour la création, et une identité authentifiée pour l'acceptation.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.errors import AppError
from app.evenements.outbox import enregistrer_evenement
from app.identity.models import Invitation, OrganizationUser, User
from app.identity.schemas import CreatePortalInvitationRequest, PortalInvitationResponse
from app.rbac.models import Role, UserRole
from app.rbac.portee_organisation import OrgScope

ACTION_PORTAIL_CREATE = "identity.organization.invitation.portal.create"
ACTION_PORTAIL_ACCEPT = "identity.organization.invitation.portal.accept"
EVENEMENT_MEMBER_INVITED = "MemberInvited"
EVENEMENT_INVITATION_ACCEPTED = "InvitationAccepted"
CODE_ROLE_OWNER = "owner"


def _vers_reponse(invitation: Invitation) -> PortalInvitationResponse:
    """Forme exposée par l'API : jamais de champ interne au-delà de l'invitation elle-même."""
    return PortalInvitationResponse(
        id=invitation.id,
        organizationId=invitation.organizationId,
        recipientUserId=invitation.recipientUserId,
        roleId=invitation.roleId,
        status=invitation.status,
        expiresAt=invitation.expiresAt,
        createdByUserId=invitation.createdByUserId,
    )


def _evenement(eventType: str, organization_id: uuid.UUID, acteur_id: uuid.UUID, invitation: Invitation, maintenant: datetime) -> dict:
    """Enveloppe d'événement de tenant (BE-150) pour une invitation. Le payload ne porte aucun secret."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": eventType,
        "schemaVersion": 1,
        "occurredAt": maintenant,
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"type": "user", "id": str(acteur_id)},
        "subject": {"type": "invitation", "id": str(invitation.id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {
            "invitationId": str(invitation.id),
            "organizationId": str(organization_id),
            "recipientUserId": str(invitation.recipientUserId),
            "roleId": None if invitation.roleId is None else str(invitation.roleId),
            "expiresAt": invitation.expiresAt.isoformat(),
        },
    }


async def create_invitation(
    db: AsyncSession, scope: OrgScope, data: CreatePortalInvitationRequest
) -> PortalInvitationResponse:
    """Crée une invitation `pending` pour `data.recipientUserId` dans `scope.organization_id` (BE-105, CA-1, CA-5).

    Erreurs, dans l'ordre : rôle absent de l'organisation (404 `role_not_found`) ; rôle Owner (403
    `owner_role_forbidden`) ; destinataire inexistant ou supprimé (404 `user_not_found`) ;
    destinataire déjà membre (409 `already_member`) ; invitation déjà ouverte (409
    `invitation_already_pending`). Aucune ligne n'est écrite en cas d'erreur.
    """
    organization_id = scope.organization_id
    maintenant = datetime.now(timezone.utc)

    if data.roleId is not None:
        role = await db.scalar(select(Role).where(Role.id == data.roleId, Role.organizationId == organization_id))
        if role is None:
            raise AppError(code="role_not_found", message="Rôle introuvable dans cette organisation.", status_code=404)
        if role.code == CODE_ROLE_OWNER:
            # QE-POR-04 : le rôle Owner ne s'attribue ni par invitation ni par transfert implicite.
            raise AppError(
                code="owner_role_forbidden",
                message="Une invitation ne peut pas proposer le rôle propriétaire.",
                status_code=403,
            )

    destinataire = await db.get(User, data.recipientUserId)
    if destinataire is None or destinataire.deletedAt is not None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable.", status_code=404)

    deja_membre = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == destinataire.id
        )
    )
    if deja_membre is not None:
        raise AppError(code="already_member", message="Cette personne est déjà membre de l'organisation.", status_code=409)

    ouverte = await db.scalar(
        select(Invitation.id).where(
            Invitation.organizationId == organization_id,
            Invitation.recipientUserId == destinataire.id,
            Invitation.status == "pending",
            Invitation.expiresAt > maintenant,
        )
    )
    if ouverte is not None:
        raise AppError(
            code="invitation_already_pending",
            message="Une invitation est déjà en attente pour cette personne.",
            status_code=409,
        )

    invitation = Invitation(
        organizationId=organization_id,
        recipientUserId=destinataire.id,
        roleId=data.roleId,
        status="pending",
        expiresAt=maintenant + timedelta(hours=settings.USER_INVITATION_TTL_HOURS),
        createdByUserId=scope.user_id,
    )
    db.add(invitation)
    await db.flush()

    await enregistrer_evenement(
        db,
        _evenement(EVENEMENT_MEMBER_INVITED, organization_id, scope.user_id, invitation, maintenant),
        emetteur_tenant=organization_id,
    )
    await record_audit_event(
        db,
        organization_id,
        scope.user_id,
        action=ACTION_PORTAIL_CREATE,
        entity_type="Invitation",
        entity_id=invitation.id,
        summary="Invitation à rejoindre l'organisation",
    )
    await db.commit()
    await db.refresh(invitation)
    return _vers_reponse(invitation)


async def accept_invitation(
    db: AsyncSession, user: User, organization_id: uuid.UUID, invitation_id: uuid.UUID
) -> PortalInvitationResponse:
    """Accepte l'invitation `invitation_id` au nom de `user` (BE-105, CA-3, CA-4).

    Erreurs : invitation absente de l'organisation (404 `invitation_not_found`) ; identité
    différente du destinataire (403 `invitation_recipient_mismatch`) ; statut `accepted`,
    `expired` ou `revoked`, ou échéance dépassée (409 `invitation_not_open` ou
    `invitation_expired`). Dans ces cas le statut reste inchangé et rien n'est écrit.
    """
    invitation = await db.scalar(
        select(Invitation).where(Invitation.id == invitation_id, Invitation.organizationId == organization_id)
    )
    if invitation is None:
        raise AppError(code="invitation_not_found", message="Invitation introuvable.", status_code=404)
    if invitation.recipientUserId != user.id:
        raise AppError(
            code="invitation_recipient_mismatch",
            message="Cette invitation est destinée à une autre personne.",
            status_code=403,
        )

    maintenant = datetime.now(timezone.utc)
    if invitation.status != "pending":
        raise AppError(code="invitation_not_open", message="Cette invitation n'est plus ouverte.", status_code=409)
    if invitation.expiresAt <= maintenant:
        raise AppError(code="invitation_expired", message="Cette invitation a expiré.", status_code=409)

    deja_membre = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == user.id
        )
    )
    if deja_membre is None:
        db.add(OrganizationUser(organizationId=organization_id, userId=user.id))
    if invitation.roleId is not None:
        role_attribue = await db.scalar(
            select(UserRole.id).where(
                UserRole.organizationId == organization_id,
                UserRole.userId == user.id,
                UserRole.roleId == invitation.roleId,
            )
        )
        if role_attribue is None:
            db.add(
                UserRole(
                    userId=user.id,
                    organizationId=organization_id,
                    roleId=invitation.roleId,
                    resourceType=None,
                    resourceId=None,
                )
            )

    invitation.status = "accepted"
    await db.flush()
    await enregistrer_evenement(
        db,
        _evenement(EVENEMENT_INVITATION_ACCEPTED, organization_id, user.id, invitation, maintenant),
        emetteur_tenant=organization_id,
    )
    await record_audit_event(
        db,
        organization_id,
        user.id,
        action=ACTION_PORTAIL_ACCEPT,
        entity_type="Invitation",
        entity_id=invitation.id,
        summary="Acceptation de l'invitation à rejoindre l'organisation",
    )
    await db.commit()
    await db.refresh(invitation)
    return _vers_reponse(invitation)
