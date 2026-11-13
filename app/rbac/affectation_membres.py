"""Affectation des rôles transverses aux membres de l'organisation courante (BE-015).

Intention : remplacer, pour un membre donné, l'ensemble de ses rôles transverses
(sans portée ni module) dans l'organisation agie. La route PUT
`/api/v1/organizations/current/members/{userId}/roles` n'accepte donc que des
rôles de cette organisation, et jamais d'identifiant d'organisation venant du client.

Contrat (QE-SOC-04 et QE-SOC-06 non tranchés dans la définition ; choix retenus) :
- corps `roleIds` : l'ensemble cible. Un rôle déjà attribué est conservé sans
  nouvelle entrée d'audit ; un rôle absent de l'ensemble est retiré ; un rôle
  nouveau est attribué ;
- permission : `rbac.role.manage` (ROLE_MANAGE), vérifiée par la route avant cette
  fonction (403 `permission_denied`, aucune écriture) ;
- rôle d'une autre organisation : 404 `role_not_found` (`get_role`) ;
- cible non membre : 404 `user_not_found` (`assert_target_is_member`) ;
- rôle de module (moduleCode renseigné) : 422 `module_role_not_allowed`, car ces
  rôles passent par l'API de module (`rbac/module_affectation.py`) ;
- rôle propriétaire (code `owner`, transverse) : seul un propriétaire peut l'attribuer
  ou le retirer, sinon 403 `owner_assignment_forbidden` ; retirer le dernier
  propriétaire actif donne 409 `last_owner` ;
- revalidation serveur : l'acteur doit posséder chaque permission des rôles qu'il
  attribue, à la portée de l'organisation (`_assert_no_privilege_escalation`,
  403 `privilege_escalation_denied`), comme `assign_role`.

Ordre des contrôles : cible, rôles, propriétaire, dernier propriétaire, élévation.
Aucun contrôle ne modifie la base avant la fin : si l'un échoue, rien n'est écrit.
Les attributions et retraits sont validés dans une seule transaction, avec une
entrée d'audit par rôle attribué (`rbac.role.assign`) ou retiré (`rbac.role.unassign`).
"""

import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.evenements.outbox import enregistrer_evenement
from app.identity.evenements_membres import EVENEMENT_ROLE_CHANGED, construire_evenement_membre
from app.identity.models import OrganizationUser, User
from app.rbac.guards import assert_target_is_member
from app.rbac.models import Role, UserRole
from app.rbac.service import (
    _assert_no_privilege_escalation,
    get_role,
    get_role_permission_codes,
    list_organization_members_with_roles,
)

ACTION_ASSIGN = "rbac.role.assign"
ACTION_UNASSIGN = "rbac.role.unassign"


async def _est_proprietaire(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur détient le rôle transverse `owner` de l'organisation."""
    return (
        await db.scalar(
            select(UserRole.id)
            .join(Role, Role.id == UserRole.roleId)
            .where(
                UserRole.organizationId == organization_id,
                UserRole.userId == user_id,
                Role.organizationId == organization_id,
                Role.code == "owner",
                Role.moduleCode.is_(None),
            )
            .limit(1)
        )
    ) is not None


async def _autres_proprietaires_actifs(db: AsyncSession, organization_id: uuid.UUID, exclu: uuid.UUID) -> int:
    """Nombre d'utilisateurs actifs, autres que `exclu`, détenant le rôle propriétaire."""
    return (
        await db.scalar(
            select(func.count(func.distinct(UserRole.userId)))
            .join(Role, Role.id == UserRole.roleId)
            .join(User, User.id == UserRole.userId)
            .where(
                UserRole.organizationId == organization_id,
                Role.organizationId == organization_id,
                Role.code == "owner",
                Role.moduleCode.is_(None),
                User.status == "active",
                User.deletedAt.is_(None),
                UserRole.userId != exclu,
            )
        )
    ) or 0


async def _roles_transverses_du_membre(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID
) -> dict[uuid.UUID, tuple[UserRole, Role]]:
    """Attributions transverses (sans portée, hors rôles de module) du membre, indexées par `roleId`,
    avec le rôle correspondant pour lire son code et son nom."""
    lignes = await db.execute(
        select(UserRole, Role)
        .join(Role, Role.id == UserRole.roleId)
        .where(
            UserRole.organizationId == organization_id,
            UserRole.userId == user_id,
            UserRole.resourceType.is_(None),
            Role.moduleCode.is_(None),
        )
    )
    return {attribution.roleId: (attribution, role) for attribution, role in lignes.all()}


async def replace_member_roles(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor: User,
    target_user_id: uuid.UUID,
    role_ids: list[uuid.UUID],
) -> dict:
    """Fixe les rôles transverses de `target_user_id` à `role_ids` dans l'organisation,
    au nom de `actor`, puis renvoie le membre tel que `list_organization_members_with_roles`
    le décrit. Le détail des contrôles et de leur ordre est dans la doc du module."""
    await assert_target_is_member(db, organization_id, target_user_id)

    cibles = set(role_ids)
    roles_cibles: dict[uuid.UUID, Role] = {}
    for role_id in cibles:
        role = await get_role(db, organization_id, role_id)
        if role.moduleCode is not None:
            raise AppError(
                code="module_role_not_allowed",
                message="Un rôle de module s'affecte par l'API de module, pas par cette route.",
                status_code=422,
            )
        roles_cibles[role_id] = role

    actuelles = await _roles_transverses_du_membre(db, organization_id, target_user_id)
    a_attribuer = [role_id for role_id in cibles if role_id not in actuelles]
    a_retirer = [role_id for role_id in actuelles if role_id not in cibles]

    touche_proprietaire = any(roles_cibles[r].code == "owner" for r in a_attribuer) or any(
        actuelles[r][1].code == "owner" for r in a_retirer
    )
    if touche_proprietaire and not await _est_proprietaire(db, organization_id, actor.id):
        raise AppError(
            code="owner_assignment_forbidden",
            message="Seul un propriétaire peut attribuer ou retirer le rôle propriétaire.",
            status_code=403,
        )

    for role_id in a_retirer:
        if actuelles[role_id][1].code == "owner" and await _autres_proprietaires_actifs(db, organization_id, target_user_id) == 0:
            raise AppError(
                code="last_owner",
                message="Impossible de retirer le dernier propriétaire actif de l'organisation.",
                status_code=409,
            )

    for role_id in a_attribuer:
        codes = await get_role_permission_codes(db, role_id)
        await _assert_no_privilege_escalation(db, organization_id, actor.id, codes)

    target = await db.get(User, target_user_id)
    cible_nom = target.fullName if target else target_user_id

    for role_id in a_retirer:
        attribution, role = actuelles[role_id]
        await db.execute(delete(UserRole).where(UserRole.id == attribution.id))
        await record_audit_event(
            db,
            organization_id,
            actor.id,
            action=ACTION_UNASSIGN,
            entity_type="UserRole",
            entity_id=role_id,
            summary=f"Retrait du rôle {role.name} à {cible_nom}",
        )

    for role_id in a_attribuer:
        role = roles_cibles[role_id]
        db.add(UserRole(userId=target_user_id, organizationId=organization_id, roleId=role_id, resourceType=None, resourceId=None))
        await record_audit_event(
            db,
            organization_id,
            actor.id,
            action=ACTION_ASSIGN,
            entity_type="UserRole",
            entity_id=role_id,
            summary=f"Attribution du rôle {role.name} à {cible_nom}",
        )

    if a_attribuer or a_retirer:
        # BE-106 : `RoleChanged` part dans la même transaction que les attributions et retraits.
        membership_id = await db.scalar(
            select(OrganizationUser.id).where(
                OrganizationUser.organizationId == organization_id, OrganizationUser.userId == target_user_id
            )
        )
        await enregistrer_evenement(
            db,
            construire_evenement_membre(
                EVENEMENT_ROLE_CHANGED,
                organization_id,
                actor.id,
                membership_id,
                {
                    "userId": str(target_user_id),
                    "roleIds": [str(role_id) for role_id in cibles],
                    "rolesAttribues": [str(role_id) for role_id in a_attribuer],
                    "rolesRetires": [str(role_id) for role_id in a_retirer],
                },
            ),
            emetteur_tenant=organization_id,
        )

    await db.commit()
    membres = await list_organization_members_with_roles(db, organization_id)
    return next(entree for entree in membres if str(entree["userId"]) == str(target_user_id))
