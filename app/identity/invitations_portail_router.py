"""Routes des invitations d'organisation du portail (BE-105).

- `POST /organizations/{organization_id}/invitations` : création, portée `OrgScope` (BE-101),
  action `portail.invitation.creer` (permission `organization.members.invite`). Membre sans
  la permission : 403 ; hors appartenance ou organisation inconnue : 404.
- `POST /organizations/{organization_id}/invitations/{invitation}/accept` : acceptation par le
  destinataire. Pas de portée `OrgScope` : le destinataire n'est pas encore membre. Sans session :
  401 ; identité différente du destinataire : 403 ; invitation expirée, révoquée ou acceptée : 409.

Montées sous `/api/v1/organizations` (app/api/v1/router.py).
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity import invitations_portail
from app.identity.models import User
from app.identity.schemas import CreatePortalInvitationRequest, PortalInvitationResponse
from app.rbac.guards import organisation_introuvable
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

PORTAIL_INVITATION_CREER = "portail.invitation.creer"


@router.post(
    "/{organization_id}/invitations",
    response_model=PortalInvitationResponse,
    status_code=201,
    summary="Inviter une personne à rejoindre l'organisation",
)
async def create_portal_invitation(
    data: CreatePortalInvitationRequest,
    scope: OrgScope = Depends(exiger_action(PORTAIL_INVITATION_CREER)),
    db: AsyncSession = Depends(get_db),
) -> PortalInvitationResponse:
    """Crée une invitation `pending` (BE-105). Voir `invitations_portail.create_invitation`."""
    return await invitations_portail.create_invitation(db, scope, data)


@router.post(
    "/{organization_id}/invitations/{invitation}/accept",
    response_model=PortalInvitationResponse,
    summary="Accepter une invitation à rejoindre l'organisation",
)
async def accept_portal_invitation(
    organization_id: str,
    invitation: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PortalInvitationResponse:
    """Accepte l'invitation au nom de l'identité authentifiée (BE-105). Voir `invitations_portail.accept_invitation`."""
    try:
        cible = uuid.UUID(organization_id)
    except ValueError:
        raise organisation_introuvable()
    return await invitations_portail.accept_invitation(db, current_user, cible, invitation)
