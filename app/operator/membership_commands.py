"""Commande de changement de rôle ou d'adhésion d'un membre (BE-140).

Classe `role.adhesion` du registre BE-127 : élargit ou restreint les accès d'une personne,
donc à double validation (BE-128) et à exécution par la garde BE-126.

Une commande de cette classe porte, dans `admin_command.payload`, l'utilisateur visé
(`userId`) et l'ensemble cible de ses rôles transverses (`roleIds`, trié, sans doublon).
La cible de la commande (`targetObjectType` = `Tenant`, `targetObjectId` = organisation)
est celle que lit la prévisualisation BE-125 ; le membre n'y figure pas comme cible
(même convention que BE-135).

Règles appliquées :
- droit (CA-1, CA-2) : `role_effectif` évalue le rôle sur la portée du tenant de la route.
  La classe n'a pas d'entrée dans `ROLES_PAR_CLASSE` : elle retombe sur `ROLES_GESTION`
  (fermé par défaut). Un agent L1, ou un gestionnaire d'un autre tenant, reçoit 403 ;
- membre (404 `user_not_found`) et rôles (404 `role_not_found` pour un rôle d'une autre
  organisation, 422 `module_role_not_allowed` pour un rôle de module), vérifiés avant toute
  écriture, à la création de l'intention ;
- exécution : le domaine `executer_changement_role` est enregistré dans `EXECUTEURS` au
  chargement du module. Il applique la différence entre rôles actuels et cibles, puis écrit
  un audit administratif (BE-122) dont `changes` porte l'état `avant` et `apres`. L'écriture
  est faite dans la transaction de la garde, qui committe à la clôture (BE-126) ;
- rôle propriétaire : tout attribution ou retrait du rôle `owner` est refusé en 403
  `owner_assignment_forbidden`. Un opérateur ne modifie pas la propriété d'un tenant ;
  cette décision est consignée comme hypothèse, à confirmer par les propriétaires ;
- l'approbation distincte est exigée par la garde (`exiger_approbation`, BE-128) : sans
  décision `approuvee`, l'exécution répond 409 `approval_required` avant tout appel au domaine.

Ce module ne contient que la logique ; les routes sont dans
`app.operator.membership_commands_router`.
"""

import uuid
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.errors import AppError
from app.identity.models import OrganizationUser
from app.operator.commands import AdminCommand, role_effectif
from app.operator.guard import EXECUTEURS
from app.rbac.guards import assert_target_is_member
from app.rbac.models import Role, UserRole
from app.rbac.service import get_role

CLASSE_ROLE_ADHESION = "role.adhesion"
TYPE_OBJET_TENANT = "Tenant"
ACTION_CHANGEMENT_ROLE = "admin.membership.role_changed"
ENTITE_MEMBRE = "OrganizationUser"


async def role_pour_changement(db: AsyncSession, actor_id: uuid.UUID, organization_id: uuid.UUID) -> str:
    """Rôle qui autorise la commande sur la portée du tenant (403 sinon, CA-1 et CA-2)."""
    return await role_effectif(db, actor_id, CLASSE_ROLE_ADHESION, organization_id)


def corps_commande(
    *,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    role_ids: list[uuid.UUID],
    reason_ticket: str,
    idempotency_key: str,
    target_version_expected: int | None,
) -> dict[str, Any]:
    """Corps d'intention au format de BE-124, avec l'utilisateur visé et ses rôles cibles.

    `roleIds` est normalisé (trié, sans doublon) : deux envois qui ne diffèrent que par
    l'ordre désignent la même intention, et `corps_identique` les reconnaît comme tels.
    """
    return {
        "commandType": CLASSE_ROLE_ADHESION,
        "commandVersion": 1,
        "tenantId": organization_id,
        "targetObjectType": TYPE_OBJET_TENANT,
        "targetObjectId": str(organization_id),
        "targetVersionExpected": target_version_expected,
        "reasonTicket": reason_ticket,
        "idempotencyKey": idempotency_key,
        "payload": {
            "userId": str(user_id),
            "roleIds": sorted({str(role_id) for role_id in role_ids}),
        },
    }


async def exiger_membre_et_roles(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, role_ids: list[uuid.UUID]
) -> None:
    """404 si l'utilisateur n'est pas membre, 404 si un rôle n'est pas de l'organisation,
    422 si un rôle est un rôle de module. Aucune écriture."""
    await assert_target_is_member(db, organization_id, user_id)
    for role_id in set(role_ids):
        role = await get_role(db, organization_id, role_id)
        if role.moduleCode is not None:
            raise AppError(
                code="module_role_not_allowed",
                message="Un rôle de module ne s'affecte pas par ce changement de rôle.",
                status_code=422,
            )


async def _roles_transverses(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> dict[uuid.UUID, Role]:
    """Rôles transverses du membre (sans portée ni module), indexés par identifiant de rôle."""
    lignes = await db.execute(
        select(Role)
        .join(UserRole, UserRole.roleId == Role.id)
        .where(
            UserRole.organizationId == organization_id,
            UserRole.userId == user_id,
            UserRole.resourceType.is_(None),
            Role.moduleCode.is_(None),
        )
    )
    return {role.id: role for role in lignes.scalars().all()}


async def executer_changement_role(db: AsyncSession, commande: AdminCommand) -> dict[str, Any]:
    """Domaine propriétaire de `role.adhesion` : applique la différence de rôles (BE-140).

    Appelé par la garde BE-126, après l'audit d'intention et dans sa transaction. Ajoute les
    rôles absents, retire les rôles en trop, puis écrit un audit administratif dont `changes`
    porte `avant` et `apres` (identifiants de rôles triés). Le rôle propriétaire est refusé
    (403) avant toute écriture. Ne committe pas : la garde committe à la clôture.
    """
    charge = commande.payload or {}
    organization_id = commande.tenantId
    user_id = uuid.UUID(charge["userId"])
    cibles = {uuid.UUID(role_id) for role_id in charge.get("roleIds", [])}

    await assert_target_is_member(db, organization_id, user_id)
    actuels = await _roles_transverses(db, organization_id, user_id)
    a_retirer = [role_id for role_id in actuels if role_id not in cibles]
    a_attribuer = [role_id for role_id in cibles if role_id not in actuels]

    roles_a_toucher = [actuels[r] for r in a_retirer] + [await get_role(db, organization_id, r) for r in a_attribuer]
    if any(role.code == "owner" for role in roles_a_toucher):
        raise AppError(
            code="owner_assignment_forbidden",
            message="Le rôle propriétaire ne se modifie pas par une commande opérateur.",
            status_code=403,
        )

    for role_id in a_retirer:
        await db.execute(
            delete(UserRole).where(
                UserRole.organizationId == organization_id,
                UserRole.userId == user_id,
                UserRole.roleId == role_id,
                UserRole.resourceType.is_(None),
            )
        )
    for role_id in a_attribuer:
        db.add(UserRole(userId=user_id, organizationId=organization_id, roleId=role_id, resourceType=None, resourceId=None))

    membership_id = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == user_id,
        )
    )
    avant = sorted(str(role_id) for role_id in actuels)
    apres = sorted(str(role_id) for role_id in cibles)
    await ecrire_evenement_admin(
        db,
        organization_id=organization_id,
        actor_user_id=commande.actorId,
        action=ACTION_CHANGEMENT_ROLE,
        entity_type=ENTITE_MEMBRE,
        entity_id=membership_id,
        summary="Changement de rôles d'un membre sur commande sensible approuvée.",
        correlation_id=commande.correlationId or str(commande.commandId),
        changes={"userId": str(user_id), "avant": avant, "apres": apres},
    )
    return {"userId": str(user_id), "avant": avant, "apres": apres}


EXECUTEURS[CLASSE_ROLE_ADHESION] = executer_changement_role
