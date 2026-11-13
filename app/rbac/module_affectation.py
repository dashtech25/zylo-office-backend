"""Affectation d'un utilisateur à un module, par module (T-022).

Intention : l'administrateur d'une organisation choisit un MEMBRE, un MODULE
ACTIF, et lui donne (ou change, ou retire) son rôle propre à ce module. Un
utilisateur a AU PLUS UN rôle par module et par organisation : changer de
rôle est un remplacement atomique, jamais un cumul.

Ce module n'invente aucun second système : il s'appuie sur `UserRole` et
`Role.moduleCode` (T-018), sur `get_role` et `_assert_no_privilege_escalation`
(rbac/service.py), et sur `assert_permissions_match_module` (module_policy.py).

Garde-fous, tous vérifiés AVANT toute écriture (une refusée = rien écrit) :
- cible membre de l'organisation et compte actif (404 / 409) ;
- rôle de l'organisation, rattaché à CE module (404 / 422) ;
- module actif pour l'affectation (409) ; le retrait reste possible si le
  module est désactivé, pour nettoyer des affectations orphelines ;
- non-élévation : le demandeur possède chaque permission du nouveau rôle, et
  chaque permission de l'ancien rôle qu'il retire (403) ;
- dernier administrateur du module : retirer le seul détenteur d'une
  permission d'administration (`*.manage` du module) est refusé (409) ;
- propriétaire : le rôle `owner` est transverse (moduleCode NULL) donc refusé
  ici (422) ; il ne passe jamais par les routes par module ;
- audit de chaque changement effectif (une ligne par affectation écrite).

Verrou : la ligne d'appartenance de la cible est verrouillée (FOR UPDATE)
pendant la modification, ce qui sérialise deux changements concurrents pour
un même utilisateur et une même organisation.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.modules_registry.service import is_module_active
from app.rbac.models import Permission, Role, RolePermission, UserRole
from app.rbac.module_policy import assert_permissions_match_module
from app.rbac.service import get_role, get_role_permission_codes, user_has_permission
from app.shared.permissions import SHARED_PERMISSION_CODES

# Suffixe d'une permission d'administration du module (vocabulaire recommandé
# de module_policy : read, create, update, delete, validate, export, manage).
ACTION_ADMIN = ".manage"

# Codes HTTP des refus métier que la prévisualisation expose sans les lever.
_CODES_REFUS_PREVISUALISABLES = {403, 409, 422}


@dataclass
class _Plan:
    """Résultat des vérifications : ce qui sera écrit, rien n'est écrit ici."""

    anciennes: list[UserRole] = field(default_factory=list)
    ancien_role: Role | None = None
    nouveau_role: Role | None = None
    codes_anciens: list[str] = field(default_factory=list)
    codes_nouveaux: list[str] = field(default_factory=list)


def _est_administrateur(codes: list[str]) -> bool:
    """Vrai si le rôle porte une permission d'administration (hors socle partagé)."""
    return any(c.endswith(ACTION_ADMIN) and c not in SHARED_PERMISSION_CODES for c in codes)


async def _affectations_du_module(db: AsyncSession, organization_id: uuid.UUID, module_code: str, user_id: uuid.UUID) -> list[UserRole]:
    result = await db.execute(
        select(UserRole)
        .join(Role, Role.id == UserRole.roleId)
        .where(
            UserRole.userId == user_id,
            UserRole.organizationId == organization_id,
            Role.moduleCode == module_code,
        )
        .order_by(UserRole.id)
    )
    return list(result.scalars().all())


async def _verifier_membre(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, *, verrou: bool, exiger_actif: bool
) -> None:
    stmt = select(OrganizationUser.id).where(
        OrganizationUser.organizationId == organization_id, OrganizationUser.userId == user_id
    )
    if verrou:
        stmt = stmt.with_for_update()
    if (await db.execute(stmt)).scalar_one_or_none() is None:
        raise AppError(code="user_not_member", message="Cet utilisateur n'est pas membre de l'organisation.", status_code=404)
    if exiger_actif:
        user = await db.get(User, user_id)
        if user is None or user.status != "active":
            raise AppError(
                code="user_not_active",
                message="Ce compte n'est pas actif : il ne peut pas recevoir de rôle de module.",
                status_code=409,
            )


async def _autres_administrateurs(db: AsyncSession, organization_id: uuid.UUID, module_code: str, exclu_user_id: uuid.UUID) -> int:
    """Nombre d'AUTRES membres actifs détenant une permission d'administration du module
    par un rôle de ce module."""
    stmt = (
        select(func.count(func.distinct(UserRole.userId)))
        .join(Role, Role.id == UserRole.roleId)
        .join(RolePermission, RolePermission.roleId == Role.id)
        .join(Permission, Permission.id == RolePermission.permissionId)
        .join(User, User.id == UserRole.userId)
        .join(
            OrganizationUser,
            (OrganizationUser.userId == UserRole.userId) & (OrganizationUser.organizationId == organization_id),
        )
        .where(
            UserRole.organizationId == organization_id,
            Role.moduleCode == module_code,
            Permission.moduleCode == module_code,
            Permission.code.like(f"%{ACTION_ADMIN}"),
            Permission.code.not_in(list(SHARED_PERMISSION_CODES)),
            User.status == "active",
            UserRole.userId != exclu_user_id,
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def _valider(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    module_code: str,
    target_user_id: uuid.UUID,
    nouveau_role_id: uuid.UUID | None,
    *,
    verrou: bool = False,
) -> _Plan:
    """Toutes les vérifications d'un changement, sans écriture.
    `nouveau_role_id=None` signifie retrait de l'affectation du module."""
    plan = _Plan()
    retrait = nouveau_role_id is None
    await _verifier_membre(db, organization_id, target_user_id, verrou=verrou, exiger_actif=not retrait)

    plan.anciennes = await _affectations_du_module(db, organization_id, module_code, target_user_id)
    if plan.anciennes:
        plan.ancien_role = await db.get(Role, plan.anciennes[0].roleId)
        plan.codes_anciens = await get_role_permission_codes(db, plan.ancien_role.id)

    if not retrait:
        nouveau = await get_role(db, organization_id, nouveau_role_id)
        if nouveau.moduleCode is None:
            raise AppError(
                code="role_not_module_role",
                message="Ce rôle n'est pas rattaché à un module : il ne peut pas être affecté par module.",
                status_code=422,
            )
        if nouveau.moduleCode != module_code:
            raise AppError(
                code="role_module_mismatch",
                message=f"Ce rôle appartient au module {nouveau.moduleCode}, pas au module {module_code}.",
                status_code=422,
            )
        if not await is_module_active(db, organization_id, module_code):
            raise AppError(code="module_not_active", message=f"Le module {module_code} n'est pas actif pour cette organisation.", status_code=409)
        plan.nouveau_role = nouveau
        plan.codes_nouveaux = await get_role_permission_codes(db, nouveau.id)
        await assert_permissions_match_module(db, module_code, plan.codes_nouveaux)
        for code in plan.codes_nouveaux:
            if not await user_has_permission(db, granter_user_id, organization_id, code):
                raise AppError(
                    code="privilege_escalation_denied",
                    message=f"Vous ne pouvez pas accorder une permission que vous ne possédez pas : {code}.",
                    status_code=403,
                )

    # Retirer (ou remplacer) un rôle : le demandeur doit posséder ce qu'il retire,
    # sinon un gestionnaire pourrait amputer les droits d'un administrateur plus haut.
    remplace = plan.ancien_role is not None and (plan.nouveau_role is None or plan.nouveau_role.id != plan.ancien_role.id)
    if remplace:
        for code in plan.codes_anciens:
            if not await user_has_permission(db, granter_user_id, organization_id, code):
                raise AppError(
                    code="module_role_removal_denied",
                    message=f"Vous ne pouvez pas retirer un droit que vous ne possédez pas : {code}.",
                    status_code=403,
                )

    # Dernier administrateur : on ne peut pas retirer le seul détenteur d'un droit d'administration.
    if remplace and _est_administrateur(plan.codes_anciens) and not _est_administrateur(plan.codes_nouveaux):
        if await _autres_administrateurs(db, organization_id, module_code, target_user_id) == 0:
            raise AppError(
                code="last_module_admin",
                message=f"Refusé : cet utilisateur est le dernier administrateur du module {module_code}.",
                status_code=409,
            )
    return plan


async def lister_membres_module(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> list[dict]:
    """Membres de l'organisation avec leur rôle sur ce module (null si aucun)."""
    membres = (
        await db.execute(
            select(OrganizationUser.userId, User.fullName, User.email, User.status)
            .join(User, User.id == OrganizationUser.userId)
            .where(OrganizationUser.organizationId == organization_id)
            .order_by(User.fullName, User.id)
        )
    ).all()
    affectations = (
        await db.execute(
            select(UserRole.id, UserRole.userId, Role.id, Role.code, Role.name)
            .join(Role, Role.id == UserRole.roleId)
            .where(UserRole.organizationId == organization_id, Role.moduleCode == module_code)
            .order_by(UserRole.id)
        )
    ).all()
    par_membre: dict[uuid.UUID, tuple] = {}
    for a_id, user_id, r_id, r_code, r_name in affectations:
        par_membre.setdefault(user_id, (a_id, r_id, r_code, r_name))
    result = []
    for user_id, full_name, email, status in membres:
        role = par_membre.get(user_id)
        result.append(
            {
                "userId": user_id,
                "fullName": full_name,
                "email": email,
                "status": status,
                "role": None
                if role is None
                else {"assignmentId": role[0], "roleId": role[1], "code": role[2], "name": role[3]},
            }
        )
    return result


async def definir_role_module(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    module_code: str,
    target_user_id: uuid.UUID,
    role_id: uuid.UUID,
) -> UserRole:
    """Affecte ou CHANGE le rôle du module pour un membre (un seul rôle par module)."""
    plan = await _valider(db, organization_id, granter_user_id, module_code, target_user_id, role_id, verrou=True)
    if plan.ancien_role is not None and plan.ancien_role.id == role_id:
        # Déjà affecté à ce rôle : rien à écrire, pas d'audit de faux changement.
        await db.commit()
        return plan.anciennes[0]

    for ancienne in plan.anciennes:
        await db.delete(ancienne)
    await db.flush()
    nouvelle = UserRole(userId=target_user_id, organizationId=organization_id, roleId=role_id, resourceType=None, resourceId=None)
    db.add(nouvelle)
    await db.flush()

    target = await db.get(User, target_user_id)
    nom = target.fullName if target else str(target_user_id)
    if plan.ancien_role is None:
        action, resume = "rbac.moduleRole.assign", f"Affectation du rôle {plan.nouveau_role.name} ({module_code}) à {nom}"
    else:
        action = "rbac.moduleRole.change"
        resume = f"Changement de rôle sur {module_code} pour {nom} : {plan.ancien_role.name} -> {plan.nouveau_role.name}"
    await record_audit_event(
        db,
        organization_id,
        granter_user_id,
        action=action,
        entity_type="UserRole",
        entity_id=nouvelle.id,
        summary=resume,
    )
    await db.commit()
    await db.refresh(nouvelle)
    return nouvelle


async def retirer_role_module(
    db: AsyncSession, organization_id: uuid.UUID, granter_user_id: uuid.UUID, module_code: str, target_user_id: uuid.UUID
) -> None:
    """Retire le rôle du module d'un membre. Un compte suspendu peut être nettoyé."""
    plan = await _valider(db, organization_id, granter_user_id, module_code, target_user_id, None, verrou=True)
    if not plan.anciennes:
        raise AppError(
            code="module_role_not_assigned",
            message=f"Cet utilisateur n'a aucun rôle sur le module {module_code}.",
            status_code=404,
        )
    target = await db.get(User, target_user_id)
    for ancienne in plan.anciennes:
        await db.delete(ancienne)
    await db.flush()
    await record_audit_event(
        db,
        organization_id,
        granter_user_id,
        action="rbac.moduleRole.unassign",
        entity_type="UserRole",
        entity_id=plan.anciennes[0].id,
        summary=f"Retrait du rôle {plan.ancien_role.name} ({module_code}) pour {target.fullName if target else target_user_id}",
    )
    await db.commit()


async def previsualiser_changement_module(
    db: AsyncSession,
    organization_id: uuid.UUID,
    granter_user_id: uuid.UUID,
    module_code: str,
    target_user_id: uuid.UUID,
    role_id: uuid.UUID | None,
) -> dict:
    """Droits effectifs AVANT et APRÈS le changement, sans écrire.
    Un refus métier (403/409/422) est renvoyé dans `refus`, pas levé : l'administrateur
    voit pourquoi l'action serait refusée. Les autres erreurs (404) sont levées."""
    avant_role = None
    avant_codes: list[str] = []
    anciennes = await _affectations_du_module(db, organization_id, module_code, target_user_id)
    if anciennes:
        avant_role = await db.get(Role, anciennes[0].roleId)
        avant_codes = await get_role_permission_codes(db, avant_role.id)

    refus = None
    plan = None
    try:
        plan = await _valider(db, organization_id, granter_user_id, module_code, target_user_id, role_id)
    except AppError as exc:
        if exc.status_code not in _CODES_REFUS_PREVISUALISABLES:
            raise
        refus = {"code": exc.code, "message": exc.message}

    apres_codes: list[str] = []
    apres_role = None
    if role_id is not None and plan is not None:
        apres_role = plan.nouveau_role
        apres_codes = plan.codes_nouveaux
    elif role_id is not None:
        # Refus : on montre tout de même le rôle demandé et ses permissions.
        apres_role = await get_role(db, organization_id, role_id)
        apres_codes = await get_role_permission_codes(db, apres_role.id)

    def _resume(role: Role | None, codes: list[str]) -> dict | None:
        return None if role is None else {"roleId": role.id, "code": role.code, "name": role.name, "permissionCodes": sorted(codes)}

    return {
        "moduleCode": module_code,
        "userId": target_user_id,
        "current": _resume(avant_role, avant_codes),
        "next": _resume(apres_role, apres_codes),
        "gained": sorted(set(apres_codes) - set(avant_codes)),
        "lost": sorted(set(avant_codes) - set(apres_codes)),
        "allowed": refus is None,
        "refusal": refus,
    }
