from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.permissions import SUBSCRIPTION_MANAGE
from app.core.errors import AppError
from app.identity.models import Organization, OrganizationUser, User
from app.identity.permissions import ORGANIZATION_MANAGE
from app.identity.schemas import CreateOrganizationRequest
from app.modules_registry.permissions import MODULE_MANAGE
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.service import get_or_create_permission
from app.shared.permissions import CURRENCY_MANAGE, CURRENCY_READ, EXCHANGE_RATE_MANAGE, EXCHANGE_RATE_READ

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
    (SUBSCRIPTION_MANAGE, "billing", "Gérer les abonnements de l'organisation."),
    (CURRENCY_READ, "shared", "Consulter le référentiel des devises."),
    (CURRENCY_MANAGE, "shared", "Créer/modifier le référentiel des devises."),
    (EXCHANGE_RATE_READ, "shared", "Consulter les taux de change."),
    (EXCHANGE_RATE_MANAGE, "shared", "Enregistrer un nouveau taux de change."),
]


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
