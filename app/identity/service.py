import uuid

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.permissions import AUDIT_LOG_VIEW
from app.audit.service import record_audit_event
from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import Organization, OrganizationUser, User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.schemas import CreateOrganizationRequest, UpdateOrganizationRequest, UpdateUserProfileRequest
from app.modules_registry.permissions import MODULE_MANAGE
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.permissions import GRANT_MANAGE, ROLE_MANAGE
from app.rbac.service import get_or_create_permission
from app.shared.permissions import CURRENCY_MANAGE, CURRENCY_READ, EXCHANGE_RATE_MANAGE, EXCHANGE_RATE_READ, GEO_READ

# Permissions d'administration du socle accordées automatiquement au rôle
# owner à la création d'une organisation — jamais les permissions d'un futur
# module métier, celles-ci restent attribuées explicitement via l'API rbac.
# Le référentiel devises/taux de change est Core (global, sans isolation
# tenant, Point 2 §7.1-§7.2) — sans concept de "super-admin plateforme" dans
# le socle actuel, chaque owner reçoit ces permissions de la même façon que
# MODULE_MANAGE/SUBSCRIPTION_MANAGE, plutôt que d'inventer un nouveau
# mécanisme de bootstrap (issue #49).
OWNER_DEFAULT_PERMISSIONS = [
    (ORGANIZATION_MANAGE, "identity", "Gérer l'organisation (membres, rôles, paramètres)."),
    (MODULE_MANAGE, "modules_registry", "Activer/désactiver les modules pour l'organisation."),
    (ROLE_MANAGE, "rbac", "Créer des rôles et modifier leurs permissions, attribuer/retirer un rôle."),
    (GRANT_MANAGE, "rbac", "Accorder ou refuser une permission individuelle, révoquer un grant."),
    (AUDIT_LOG_VIEW, "audit", "Consulter le journal d'audit."),
    (SUBSCRIPTION_MANAGE, "billing", "Gérer les abonnements de l'organisation."),
    (CURRENCY_READ, "shared", "Consulter le référentiel des devises."),
    (CURRENCY_MANAGE, "shared", "Créer/modifier le référentiel des devises."),
    (EXCHANGE_RATE_READ, "shared", "Consulter les taux de change."),
    (EXCHANGE_RATE_MANAGE, "shared", "Enregistrer un nouveau taux de change."),
    (GEO_READ, "shared", "Consulter le référentiel géographique (pays/régions/villes)."),
]


async def check_email_available(db: AsyncSession, email: str) -> None:
    """Même contrôle que `register_user` (app/auth/service.py) — factorisé
    ici pour être réutilisé par tout flux de création de compte (ex. module
    Personnel, un gérant créant un compte pour un employé), jamais dupliqué."""
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="email_already_used", message="Cet email est déjà utilisé.", status_code=409)


def build_user(
    email: str,
    full_name: str,
    hashed_password: str,
    status: str = "active",
    must_change_password: bool = False,
    first_name: str | None = None,
    last_name: str | None = None,
    phone: str | None = None,
) -> User:
    """Construit (sans `db.add`/commit) l'instance `User` — l'appelant reste
    responsable de la transaction (ex. le module Personnel crée `User` +
    `OrganizationUser` + un profil de poste en une seule transaction).
    `register_user` (auto-inscription) reste l'unique appelant qui commite
    immédiatement, comportement inchangé."""
    return User(
        email=email, hashedPassword=hashed_password, fullName=full_name, status=status,
        mustChangePassword=must_change_password, firstName=first_name, lastName=last_name, phone=phone,
    )


async def create_organization(db: AsyncSession, owner: User, data: CreateOrganizationRequest) -> Organization:
    existing = await db.execute(select(Organization).where(Organization.slug == data.slug))
    if existing.scalar_one_or_none() is not None:
        raise AppError(code="slug_already_used", message="Ce slug d'organisation est déjà utilisé.", status_code=409)

    organization = Organization(name=data.name, slug=data.slug)
    db.add(organization)
    await db.flush()

    db.add(OrganizationUser(organizationId=organization.id, userId=owner.id))

    # Rôle "owner" auto-créé pour le créateur — seul rôle qui existe par défaut,
    # tout autre rôle est créé explicitement par la suite via l'API rbac.
    owner_role = Role(organizationId=organization.id, code="owner", name="Propriétaire")
    db.add(owner_role)
    await db.flush()

    for code, module_code, description in OWNER_DEFAULT_PERMISSIONS:
        permission = await get_or_create_permission(db, code, module_code, description)
        db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
    db.add(UserRole(userId=owner.id, organizationId=organization.id, roleId=owner_role.id))

    await db.commit()
    await db.refresh(organization)
    return organization


async def backfill_owner_default_permissions(db: AsyncSession) -> int:
    """Idempotent — répare les organisations créées avant l'ajout d'une
    entrée à `OWNER_DEFAULT_PERMISSIONS` (ex. `ROLE_MANAGE`/`GRANT_MANAGE`/
    `AUDIT_LOG_VIEW`, ajoutées en cours de développement du socle RBAC :
    seules les organisations créées APRÈS ce commit recevaient ces
    permissions via `create_organization`). Ne touche jamais aux rôles
    personnalisés ni aux grants individuels — uniquement le rôle `owner`.
    Retourne le nombre de lignes `RolePermission` effectivement ajoutées."""
    owner_roles = (await db.execute(select(Role).where(Role.code == "owner"))).scalars().all()
    added = 0
    for owner_role in owner_roles:
        existing_permission_ids = set(
            (await db.execute(select(RolePermission.permissionId).where(RolePermission.roleId == owner_role.id)))
            .scalars()
            .all()
        )
        for code, module_code, description in OWNER_DEFAULT_PERMISSIONS:
            permission = await get_or_create_permission(db, code, module_code, description)
            if permission.id not in existing_permission_ids:
                db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
                existing_permission_ids.add(permission.id)
                added += 1
    await db.commit()
    return added


async def list_user_organizations(db: AsyncSession, user_id: uuid.UUID) -> list[Organization]:
    """Organisations auxquelles appartient l'utilisateur (Point App Launcher,
    frontend) — nécessaire pour que le frontend sache dans quelle
    organisation opérer, aucun endpoint ne l'exposait jusqu'ici."""
    result = await db.execute(
        select(Organization)
        .join(OrganizationUser, OrganizationUser.organizationId == Organization.id)
        .where(OrganizationUser.userId == user_id)
        .order_by(Organization.name)
    )
    return list(result.scalars().all())


async def update_organization(
    db: AsyncSession, organization_id: str, actor_user_id: uuid.UUID, data: UpdateOrganizationRequest
) -> Organization:
    """Seul `name` est modifiable — `Organization` (Core) n'a aucun autre
    champ éditable (pas de logo/téléphone/email/langue/devise : voir l'audit
    fait pour la page Paramètres Zylo Liquid, aucun de ces champs n'existe
    dans le modèle). `slug` reste immuable (identifiant stable)."""
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    before_name = organization.name
    organization.name = data.name
    await record_audit_event(
        db,
        organization.id,
        actor_user_id,
        action="identity.organization.update",
        entity_type="Organization",
        entity_id=organization.id,
        summary=f"Modification de l'organisation ({before_name} → {data.name})",
        changes={"name": {"before": before_name, "after": data.name}},
    )
    await db.commit()
    await db.refresh(organization)
    return organization


async def _is_owner_of_target_user_organization(db: AsyncSession, actor_user_id: uuid.UUID, target_user_id: uuid.UUID) -> bool:
    """Vrai si `actor_user_id` détient le rôle "owner" dans AU MOINS UNE des
    organisations auxquelles appartient `target_user_id` — un owner d'une
    organisation différente de celle de la cible reste refusé (pas de
    fuite entre organisations), tout comme un membre non-owner de la MÊME
    organisation que la cible."""
    result = await db.execute(
        select(UserRole.id)
        .join(Role, Role.id == UserRole.roleId)
        .join(
            OrganizationUser,
            (OrganizationUser.organizationId == UserRole.organizationId) & (OrganizationUser.userId == target_user_id),
        )
        .where(UserRole.userId == actor_user_id, Role.code == "owner")
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def update_user_profile(
    db: AsyncSession, user_id: uuid.UUID, actor: User, data: UpdateUserProfileRequest
) -> User:
    """PATCH /users/{user_id} (module Personnel) — deux cas autorisés :
    (a) l'utilisateur modifie sa propre photo (toujours permis, aucune
    permission RBAC requise au-delà d'être authentifié) ; (b) un owner
    d'une organisation modifie la photo d'un membre de CETTE organisation
    (flux admin/config Personnel, en cours de construction côté frontend).
    Tout autre cas est un 403 — jamais un 404 qui laisserait deviner
    l'existence d'un compte à un tiers non autorisé."""
    target = await db.get(User, user_id)
    if target is None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable.", status_code=404)

    if actor.id != target.id:
        is_owner = await _is_owner_of_target_user_organization(db, actor.id, target.id)
        if not is_owner:
            raise AppError(
                code="user_profile_forbidden",
                message="Vous ne pouvez modifier que votre propre profil, ou celui d'un membre de votre organisation si vous en êtes propriétaire.",
                status_code=403,
            )

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(target, field, value)

    await db.commit()
    await db.refresh(target)
    return target


async def require_organization_member(
    organization_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Vérifie seulement l'appartenance à l'organisation — plus permissive
    que `require_permission()` : voir les modules installés pour son
    organisation ne doit pas nécessiter une permission d'administration
    (contrairement à les activer/désactiver, toujours derrière MODULE_MANAGE).
    `organization_id` est résolu par FastAPI depuis le paramètre de chemin
    de même nom sur la route appelante — jamais une fabrique à la
    `require_permission(code)`, la valeur varie par requête, pas au chargement
    du module."""
    result = await db.execute(
        select(OrganizationUser).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == current_user.id
        )
    )
    if result.scalar_one_or_none() is None:
        raise AppError(
            code="not_organization_member",
            message="Vous n'appartenez pas à cette organisation.",
            status_code=403,
        )
