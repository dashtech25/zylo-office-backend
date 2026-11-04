"""Membres de l'organisation courante : liste et retrait (BE-014).

Intention : l'organisation agie est toujours celle validée par la garde
BE-009 (`get_current_organization_id`) ; ce module ne reçoit jamais un
identifiant d'organisation venant du client. Un membre d'une autre
organisation n'est donc jamais visible ni retirable depuis ici (404
uniforme `user_not_found`, sans énumération).

Règles :
- la liste reprend `rbac.service.list_organization_members_with_roles` (un
  seul calcul des membres et de leurs rôles dans l'organisation) ;
- le retrait supprime l'appartenance (`organizationUser`) et les attributions
  de rôle de l'utilisateur dans CETTE organisation (`userRole`). Sans
  appartenance, `assert_active_membership` refuse toute requête suivante : la
  révocation prend effet dès la requête suivante, sans attendre l'expiration
  des jetons ;
- le rôle propriétaire est protégé : seul un propriétaire peut retirer un
  propriétaire (403 `owner_removal_forbidden`), et une organisation garde au
  moins un propriétaire actif (409 `last_owner`) ;
- chaque retrait écrit exactement une entrée d'audit (BE-007) dans la même
  transaction que la suppression.

Hors périmètre (décision à reprendre si besoin) : les grants individuels
(`user_permission_grant`) de l'utilisateur dans l'organisation ne sont pas
supprimés ici. Ils n'ont aucun effet tant que l'appartenance manque, mais
réapparaîtraient à une nouvelle adhésion.
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.identity.invitations import _autres_proprietaires_actifs, _est_proprietaire, _membre
from app.identity.models import OrganizationUser, User
from app.rbac.models import UserRole
from app.rbac.service import list_organization_members_with_roles

ACTION_MEMBER_REMOVE = "identity.member.remove"


async def list_members(db: AsyncSession, organization_id: uuid.UUID) -> list[dict]:
    """Membres de l'organisation avec leurs rôles, triés par nom complet.

    Une organisation sans autre membre renvoie au moins son propriétaire ; une
    liste vide n'est donc pas un état normal. Le refus (non-membre, 404) et
    l'absence de permission de lecture (403) sont traités avant, par les gardes
    de la route."""
    return await list_organization_members_with_roles(db, organization_id)


async def remove_member(db: AsyncSession, organization_id: uuid.UUID, actor: User, target_user_id: uuid.UUID) -> None:
    """Retire `target_user_id` de l'organisation, au nom de `actor`.

    Ordre des contrôles (chacun renvoie une erreur sans rien écrire) :
    1. la cible doit être membre de l'organisation, sinon 404 `user_not_found` ;
    2. si la cible est propriétaire, l'acteur doit l'être aussi, sinon 403
       `owner_removal_forbidden` ;
    3. le retrait ne doit pas laisser l'organisation sans propriétaire actif,
       sinon 409 `last_owner`.

    La permission `organization.members.remove` est vérifiée par la route avant
    cette fonction. Le retrait et l'entrée d'audit sont validés ensemble."""
    target = await _membre(db, organization_id, target_user_id)

    cible_est_proprietaire = await _est_proprietaire(db, organization_id, target.id)
    if cible_est_proprietaire and not await _est_proprietaire(db, organization_id, actor.id):
        raise AppError(
            code="owner_removal_forbidden",
            message="Seul un propriétaire peut retirer un propriétaire de l'organisation.",
            status_code=403,
        )
    if cible_est_proprietaire and await _autres_proprietaires_actifs(db, organization_id, target.id) == 0:
        raise AppError(
            code="last_owner",
            message="Impossible de retirer le dernier propriétaire actif de l'organisation.",
            status_code=409,
        )

    appartenance = await db.scalar(
        select(OrganizationUser).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == target.id
        )
    )
    if appartenance is None:
        # Course entre la lecture de `_membre` et la suppression : même réponse qu'une cible absente.
        raise AppError(code="user_not_found", message="Utilisateur introuvable dans cette organisation.", status_code=404)

    membership_id = appartenance.id
    await db.execute(
        delete(UserRole).where(UserRole.organizationId == organization_id, UserRole.userId == target.id)
    )
    await db.delete(appartenance)
    await record_audit_event(
        db,
        organization_id,
        actor.id,
        action=ACTION_MEMBER_REMOVE,
        entity_type="OrganizationUser",
        entity_id=membership_id,
        summary=f"Retrait du membre {target.email} de l'organisation",
    )
    await db.commit()
