import uuid

from fastapi import Depends, Header
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.permissions import AUDIT_EXPORT, AUDIT_LOG_VIEW, ORGANIZATION_AUDIT_READ
from app.exports.permissions import DONNEES_EXPORT_CREER
from app.audit.service import record_audit_event
from app.billing.permissions import (
    BILLING_CONSENT_RECORD,
    BILLING_DATA_EXPORT_REQUEST,
    BILLING_DISPUTE_READ,
    BILLING_HISTORY_READ,
    BILLING_RECONCILIATION_RUN,
    BILLING_REFUND_REQUEST,
    BILLING_INVOICE_FINALIZE,
    BILLING_INVOICE_READ,
    ORGANIZATION_ENTITLEMENT_ALLOCATE,
    ORGANIZATION_ENTITLEMENT_READ,
    ORGANIZATION_ENTITLEMENT_REVOKE,
    SUBSCRIPTION_MANAGE,
    SUBSCRIPTION_READ,
)
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.core.versioning import mutation_versionnee
from app.identity.models import Organization, OrganizationUser, User
from app.identity.permissions import (
    MEMBERS_INVITE,
    MEMBERS_READ,
    MEMBERS_REMOVE,
    ORGANIZATION_MANAGE,
    ORGANIZATION_SETTINGS_UPDATE,
    USER_MANAGE,
)
from app.identity.schemas import CreateOrganizationRequest, UpdateOrganizationRequest, UpdateUserProfileRequest
from app.modules_registry.permissions import (
    MODULE_MANAGE,
    ORGANIZATION_MODULE_ACTIVATE,
    ORGANIZATION_MODULE_SUSPEND,
    ORGANIZATION_MODULE_INSTALL,
    ORGANIZATION_MODULE_READ,
    ORGANIZATION_MODULE_UNINSTALL,
    ORGANIZATION_MODULE_UPGRADE,
)
from app.rbac.models import Role, RolePermission, UserRole
from app.rbac.permissions import GRANT_MANAGE, ROLE_MANAGE
from app.rbac.service import assert_active_membership, get_or_create_permission, organisation_introuvable
from app.shared.permissions import CURRENCY_MANAGE, CURRENCY_READ, EXCHANGE_RATE_MANAGE, EXCHANGE_RATE_READ, GEO_READ
from app.shared.storage import organisation_de_la_reference

# Permissions d'administration du socle accordées automatiquement au rôle
# owner à la création d'une organisation — jamais les permissions d'un futur
# module métier, celles-ci restent attribuées explicitement via l'API rbac.
# Le référentiel devises/taux de change est Core (global, sans isolation
# tenant, Point 2 §7.1-§7.2) — sans concept de "super-admin plateforme" dans
# le socle actuel, chaque owner reçoit ces permissions de la même façon que
# MODULE_MANAGE/SUBSCRIPTION_MANAGE, plutôt que d'inventer un nouveau
# mécanisme de bootstrap (issue #49).
OWNER_DEFAULT_PERMISSIONS = [
    (DONNEES_EXPORT_CREER, "exports", "Demander un export de données d'un sujet ou du tenant (BE-243)."),
    (ORGANIZATION_MANAGE, "identity", "Gérer l'organisation (membres, rôles, paramètres)."),
    (USER_MANAGE, "identity", "Créer des utilisateurs, réémettre une invitation, suspendre et réactiver un membre."),
    (MEMBERS_INVITE, "identity", "Inviter une personne à rejoindre l'organisation et consulter les invitations en attente."),
    (MEMBERS_READ, "identity", "Lister les membres de l'organisation courante."),
    (MEMBERS_REMOVE, "identity", "Retirer un membre de l'organisation (le rôle propriétaire reste réservé aux propriétaires)."),
    (ORGANIZATION_SETTINGS_UPDATE, "identity", "Modifier les réglages de l'organisation courante (nom)."),
    (MODULE_MANAGE, "modules_registry", "Activer/désactiver les modules pour l'organisation."),
    (ORGANIZATION_MODULE_READ, "modules_registry", "Lire les permissions déclarées par les modules de l'organisation (BE-055)."),
    (ORGANIZATION_MODULE_INSTALL, "modules_registry", "Installer techniquement un module pour l'organisation (BE-047)."),
    (ORGANIZATION_MODULE_ACTIVATE, "modules_registry", "Activer ou désactiver un module installé pour l'organisation (BE-048)."),
    (ORGANIZATION_MODULE_SUSPEND, "modules_registry", "Suspendre ou reprendre un module pour l'organisation, origine client (BE-049)."),
    (ORGANIZATION_MODULE_UPGRADE, "modules_registry", "Mettre à jour une installation de module vers une version supérieure (BE-051)."),
    (ORGANIZATION_MODULE_UNINSTALL, "modules_registry", "Désinstaller un module de l'organisation, sans purge des données (BE-050)."),
    (ROLE_MANAGE, "rbac", "Créer des rôles et modifier leurs permissions, attribuer/retirer un rôle."),
    (GRANT_MANAGE, "rbac", "Accorder ou refuser une permission individuelle, révoquer un grant."),
    (AUDIT_LOG_VIEW, "audit", "Consulter le journal d'audit."),
    (AUDIT_EXPORT, "audit", "Demander un export du journal d'audit (BE-173)."),
    (ORGANIZATION_AUDIT_READ, "audit", "Consulter le journal des transitions de modules de l'organisation (BE-056)."),
    (SUBSCRIPTION_MANAGE, "billing", "Gérer les abonnements de l'organisation."),
    (SUBSCRIPTION_READ, "billing", "Consulter l'abonnement, les droits et les entitlements de l'organisation."),
    (BILLING_INVOICE_READ, "billing", "Consulter les factures et tentatives de paiement de l'organisation."),
    (BILLING_INVOICE_FINALIZE, "billing", "Finaliser une facture brouillon (BE-086, finance)."),
    (ORGANIZATION_ENTITLEMENT_READ, "billing", "Consulter les entitlements de l'organisation désignée par son identifiant (BE-045)."),
    (ORGANIZATION_ENTITLEMENT_ALLOCATE, "billing", "Attribuer un siège d'entitlement à un membre de l'organisation (BE-046)."),
    (ORGANIZATION_ENTITLEMENT_REVOKE, "billing", "Révoquer le siège d'entitlement d'un membre de l'organisation (BE-046)."),
    (BILLING_CONSENT_RECORD, "billing", "Enregistrer un consentement versionné pour un compte payeur (BE-076)."),
    (BILLING_DATA_EXPORT_REQUEST, "billing", "Demander un export des données de facturation d'un compte payeur (BE-098)."),
    (BILLING_HISTORY_READ, "billing", "Consulter l'historique commercial du tenant courant (BE-099)."),
    (BILLING_REFUND_REQUEST, "billing", "Demander un remboursement d'un paiement réussi (BE-093, finance)."),
    (BILLING_DISPUTE_READ, "billing", "Consulter les litiges fournisseur de l'organisation courante (BE-094, finance)."),
    (BILLING_RECONCILIATION_RUN, "billing", "Lancer une réconciliation des paiements et résultats incertains (BE-095, finance)."),
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
    # Insensible à la casse : même règle que l'index unique sur lower(email).
    existing = await db.execute(select(User).where(func.lower(User.email) == email.lower()))
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
    dans le modèle). `slug` reste immuable (identifiant stable).

    Contrôle de version (BE-233) : si `data.version` est fourni et ne correspond
    plus à la version courante, `mutation_versionnee` lève 409 `version_conflict`
    avant toute écriture ni trace d'audit. Le droit `ORGANIZATION_MANAGE` est
    déjà vérifié par la route, donc un refus reste un 403."""
    organization = await db.get(Organization, organization_id)
    if organization is None:
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    before_name = organization.name
    await mutation_versionnee(
        db,
        Organization,
        organization.id,
        data.version,
        {"name": data.name},
        code_introuvable="organization_not_found",
    )
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

    # T-014 (IAM-019) : une photo ne peut référencer qu'un fichier écrit par une
    # organisation dont l'acteur est membre. Sans ce contrôle, une référence d'une
    # autre organisation (obtenue par énumération ou fuite) serait acceptée.
    if data.photoStorageReference is not None:
        organisation = organisation_de_la_reference(data.photoStorageReference)
        membre = None
        if organisation is not None:
            membre = await db.scalar(
                select(OrganizationUser.id).where(
                    OrganizationUser.organizationId == organisation, OrganizationUser.userId == actor.id
                )
            )
        if membre is None:
            raise AppError(
                code="photo_reference_forbidden",
                message="Cette photo n'appartient pas à une organisation dont vous êtes membre.",
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
    x_organization_id: uuid.UUID | None = Header(None, alias="X-Organization-Id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Vérifie seulement l'appartenance (active) à l'organisation du chemin —
    plus permissive que `require_permission()` : voir les modules installés pour
    son organisation ne doit pas nécessiter une permission d'administration
    (contrairement à les activer/désactiver, toujours derrière MODULE_MANAGE).
    `organization_id` est résolu par FastAPI depuis le paramètre de chemin
    de même nom sur la route appelante — jamais une fabrique à la
    `require_permission(code)`, la valeur varie par requête, pas au chargement
    du module.

    T-010 : un en-tête `X-Organization-Id` présent doit désigner la même
    organisation que le chemin, sinon refus uniforme 404 ; un non-membre reçoit
    la même réponse qu'une organisation inexistante (pas d'énumération)."""
    if x_organization_id is not None and x_organization_id != organization_id:
        raise organisation_introuvable()
    await assert_active_membership(db, current_user.id, organization_id)
