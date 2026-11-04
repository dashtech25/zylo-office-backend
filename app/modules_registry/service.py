import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.billing.models import Subscription, SubscriptionEntitlement
from app.core.database import get_db
from app.core.errors import AppError
from app.modules_registry.models import Module, OrganizationModule
from app.modules_registry.schemas import InstalledModuleResponse
from app.rbac.models import Permission, Role, RolePermission
from app.rbac.service import get_current_organization_id


# Hooks d'activation par module (seed des rôles par défaut). Le socle n'importe jamais un module métier :
# l'application (composition root, app/main.py) les enregistre. Sans cela, rbac -> module_assignment ->
# modules_registry -> modules.zylo_liquid rendait `Files ne dépend jamais de zylo_liquid` violé (import-linter).
HookActivation = Callable[[AsyncSession, uuid.UUID], Awaitable[None]]
_hooks_activation: dict[str, HookActivation] = {}


def enregistre_hook_activation(module_code: str, hook: HookActivation) -> None:
    _hooks_activation[module_code] = hook


async def grant_module_permissions_to_owner(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> None:
    """Sans cet appel, aucune permission déclarée par un module n'est
    accordable après son activation : aucun endpoint HTTP de gestion des
    rôles n'existe encore dans le socle (constat fait à la construction de
    l'endpoint 1 de Zylo Liquid, issue #23) — le owner doit donc recevoir de
    plein droit les permissions du module qu'il vient d'activer pour son
    organisation, exactement comme il reçoit déjà celles du socle à la
    création de l'organisation (OWNER_DEFAULT_PERMISSIONS, identity/service.py)."""
    result = await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == "owner"))
    owner_role = result.scalar_one_or_none()
    if owner_role is None:
        return

    permissions = (await db.execute(select(Permission).where(Permission.moduleCode == module_code))).scalars().all()
    if not permissions:
        return

    existing = (
        (
            await db.execute(
                select(RolePermission.permissionId).where(RolePermission.roleId == owner_role.id)
            )
        )
        .scalars()
        .all()
    )
    existing_ids = set(existing)
    for permission in permissions:
        if permission.id not in existing_ids:
            db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))


async def backfill_active_module_permissions_for_owners(db: AsyncSession) -> int:
    """Idempotent — répare les organisations dont un module était déjà actif
    AVANT l'ajout de nouvelles permissions à ce module en cours de
    développement (ex. la couche déclarative/commerciale/rapprochement
    ajoutée à `zylo_liquid` bien après l'activation initiale du module par
    des organisations existantes, processus-double-sources-verite Phase 8) —
    même principe que `backfill_owner_default_permissions`
    (identity/service.py) mais pour les permissions de module plutôt que du
    socle. `grant_module_permissions_to_owner` ne s'exécute normalement qu'à
    l'activation ; sans ce backfill, un owner déjà actif ne reçoit jamais
    les permissions ajoutées après coup. Ne touche jamais aux rôles
    personnalisés ni aux grants individuels — uniquement le rôle `owner`."""
    active_modules = (
        (await db.execute(select(OrganizationModule.organizationId, OrganizationModule.moduleCode).where(OrganizationModule.status == "active")))
        .all()
    )
    added = 0
    for organization_id, module_code in active_modules:
        owner_role = (await db.execute(select(Role).where(Role.organizationId == organization_id, Role.code == "owner"))).scalar_one_or_none()
        if owner_role is None:
            continue
        module_permissions = (await db.execute(select(Permission).where(Permission.moduleCode == module_code))).scalars().all()
        if not module_permissions:
            continue
        existing_ids = set(
            (await db.execute(select(RolePermission.permissionId).where(RolePermission.roleId == owner_role.id))).scalars().all()
        )
        for permission in module_permissions:
            if permission.id not in existing_ids:
                db.add(RolePermission(roleId=owner_role.id, permissionId=permission.id))
                existing_ids.add(permission.id)
                added += 1
    await db.commit()
    return added


async def get_or_create_module(db: AsyncSession, code: str, name: str, description: str, version: str = "0.1.0") -> Module:
    result = await db.execute(select(Module).where(Module.code == code))
    module = result.scalar_one_or_none()
    if module:
        return module
    module = Module(code=code, name=name, description=description, version=version)
    db.add(module)
    await db.flush()
    return module


async def activate_module(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, module_code: str
) -> OrganizationModule:
    await assert_module_entitled(db, organization_id, module_code)
    result = await db.execute(select(Module).where(Module.code == module_code))
    if result.scalar_one_or_none() is None:
        raise AppError(code="module_not_found", message=f"Module inconnu : {module_code}.", status_code=404)

    result = await db.execute(
        select(OrganizationModule).where(
            OrganizationModule.organizationId == organization_id, OrganizationModule.moduleCode == module_code
        )
    )
    org_module = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if org_module is None:
        org_module = OrganizationModule(
            organizationId=organization_id, moduleCode=module_code, status="active", activatedAt=now
        )
        db.add(org_module)
    else:
        org_module.status = "active"
        org_module.activatedAt = now
        org_module.deactivatedAt = None
    # Ordre voulu : seed des rôles D'ABORD, grant au owner ENSUITE — le seed
    # matérialise les lignes `permission` (y compris les codes ajoutés après
    # la première activation d'une organisation), et le grant ne peut
    # accorder au owner que des lignes existantes. Sous l'ancien ordre, tout
    # code de permission ajouté plus tard n'était jamais accordé au owner
    # d'une organisation déjà activée (bug constaté en test : 403
    # zyloLiquid.supplier.manage pour un owner fraîchement activé).
    #
    # Couplage direct et assumé (comme grant_module_permissions_to_owner
    # ci-dessus) plutôt qu'un mécanisme générique de hook par module — à
    # généraliser (registre de callables par module_code) le jour où un 2e
    # module a besoin de rôles par défaut (§20 du document d'architecture,
    # « rôle et permissions... .md »).
    hook = _hooks_activation.get(module_code)
    if hook is not None:
        await hook(db, organization_id)

    await grant_module_permissions_to_owner(db, organization_id, module_code)

    await db.flush()  # garantit org_module.id (défaut Python UUID, appliqué au flush) avant l'audit
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="modulesRegistry.module.activate",
        entity_type="OrganizationModule",
        entity_id=org_module.id,
        summary=f"Activation du module {module_code}",
    )
    await db.commit()
    await db.refresh(org_module)
    return org_module


async def deactivate_module(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, module_code: str
) -> OrganizationModule:
    result = await db.execute(
        select(OrganizationModule).where(
            OrganizationModule.organizationId == organization_id, OrganizationModule.moduleCode == module_code
        )
    )
    org_module = result.scalar_one_or_none()
    if org_module is None:
        raise AppError(code="module_not_activated", message="Ce module n'est pas activé pour cette organisation.", status_code=404)
    org_module.status = "inactive"
    org_module.deactivatedAt = datetime.now(timezone.utc)
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="modulesRegistry.module.deactivate",
        entity_type="OrganizationModule",
        entity_id=org_module.id,
        summary=f"Désactivation du module {module_code}",
    )
    await db.commit()
    await db.refresh(org_module)
    return org_module


async def is_module_active(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> bool:
    result = await db.execute(
        select(OrganizationModule.status).where(
            OrganizationModule.organizationId == organization_id,
            OrganizationModule.moduleCode == module_code,
        )
    )
    status_value = result.scalar_one_or_none()
    return status_value in ("active", "trial")


async def assert_module_entitled(db: AsyncSession, organization_id: uuid.UUID, module_code: str) -> None:
    """Compatibility-first entitlement gate.

    Organizations without an explicit entitlement row retain legacy access.
    If a row exists, only its latest effective entitlement is considered;
    explicit inactive/expired/blocked state or an expired/cancelled backing
    subscription denies activation and module access.
    """
    _access_state, allowed = await get_module_entitlement_access(db, organization_id, module_code)
    if not allowed:
        raise AppError(
            code="module_entitlement_unavailable",
            message=f"L'accès au module '{module_code}' n'est pas disponible pour cette organisation.",
            status_code=403,
        )


def _project_entitlement_access(row, now: datetime) -> tuple[str, bool]:
    """Project the existing enforcement rule for read-only UI decisions.

    A missing row continues to allow legacy organizations for compatibility;
    this is deliberately not represented as a paid/active subscription.
    Only a missing entitlement row retains legacy access. Explicit unknown
    entitlement or subscription states fail closed.
    """
    if row is None:
        return "not_configured", True

    entitlement, subscription_status = row
    if entitlement.status == "blocked":
        return "blocked", False
    if (
        entitlement.status == "expired"
        or (entitlement.endsAt is not None and entitlement.endsAt <= now)
        or subscription_status in {"expired", "cancelled"}
    ):
        return "expired", False
    if entitlement.status == "inactive" or entitlement.startsAt > now:
        return "inactive", False
    if entitlement.status == "active" and subscription_status in {"active", "trial"}:
        return "active", True
    return "unknown", False


def _select_effective_entitlement(rows, now: datetime):
    """Choose the latest entitlement already in effect; future rows cannot mask it."""
    effective = [row for row in rows if row[0].startsAt <= now]
    if effective:
        return max(effective, key=lambda row: (row[0].startsAt, row[0].createdAt))
    # A future-only explicit entitlement is configured but not yet effective.
    return min(rows, key=lambda row: (row[0].startsAt, row[0].createdAt), default=None)


async def get_module_entitlement_access(
    db: AsyncSession, organization_id: uuid.UUID, module_code: str
) -> tuple[str, bool]:
    """Return the same compatibility-first decision used by module guards."""
    result = await db.execute(
        select(SubscriptionEntitlement, Subscription.status)
        .join(Subscription, Subscription.id == SubscriptionEntitlement.subscriptionId)
        .where(
            SubscriptionEntitlement.organizationId == organization_id,
            SubscriptionEntitlement.moduleCode == module_code,
        )
    )
    now = datetime.now(timezone.utc)
    return _project_entitlement_access(_select_effective_entitlement(result.all(), now), now)


async def list_installed_modules(db: AsyncSession, organization_id: uuid.UUID) -> list[InstalledModuleResponse]:
    """Croise le catalogue complet des modules avec les activations de
    l'organisation — 'inactive' par défaut si aucune ligne OrganizationModule
    n'existe pour ce module (jamais activé pour cette organisation)."""
    modules = (await db.execute(select(Module).order_by(Module.name))).scalars().all()
    org_modules = (
        (await db.execute(select(OrganizationModule).where(OrganizationModule.organizationId == organization_id)))
        .scalars()
        .all()
    )
    org_modules_by_code = {org_module.moduleCode: org_module for org_module in org_modules}

    entitlement_rows = (
        await db.execute(
            select(SubscriptionEntitlement, Subscription.status)
            .join(Subscription, Subscription.id == SubscriptionEntitlement.subscriptionId)
            .where(SubscriptionEntitlement.organizationId == organization_id)
            .order_by(
                SubscriptionEntitlement.moduleCode,
                SubscriptionEntitlement.startsAt.desc(),
                SubscriptionEntitlement.createdAt.desc(),
            )
        )
    ).all()
    entitlements_by_module = {}
    for row in entitlement_rows:
        module_code = row[0].moduleCode
        entitlements_by_module.setdefault(module_code, []).append(row)

    result: list[InstalledModuleResponse] = []
    now = datetime.now(timezone.utc)
    for module in modules:
        org_module = org_modules_by_code.get(module.code)
        installation_status = org_module.status if org_module else "inactive"
        access_state, can_activate = _project_entitlement_access(
            _select_effective_entitlement(entitlements_by_module.get(module.code, []), now), now
        )
        result.append(
            InstalledModuleResponse(
                moduleCode=module.code,
                name=module.name,
                description=module.description,
                version=module.version,
                status=installation_status,
                activatedAt=org_module.activatedAt if org_module else None,
                accessState=access_state,
                canActivate=can_activate,
                canOpen=(installation_status in {"active", "trial"} and can_activate),
            )
        )
    return result


def require_module_active(module_code: str):
    """Combinable avec require_permission() sur une même route — un module
    inactif bloque l'accès même si l'utilisateur a la permission requise
    (grande_phases.md §9)."""

    async def dependency(
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not await is_module_active(db, organization_id, module_code):
            raise AppError(
                code="module_inactive",
                message=f"Le module '{module_code}' n'est pas actif pour cette organisation.",
                status_code=403,
            )
        await assert_module_entitled(db, organization_id, module_code)

    return dependency


def require_module_active_any(*module_codes: str):
    """Généralisation Zylo Tanker (2026-09-16) — pour les routes réellement
    partagées entre deux modules (ex. `app/location/router.py`, monté à la
    fois sous `/zylo-liquid` et `/zylo-tanker` : `/gps-devices`,
    `/tracking-locations`, `/tracking-settings`...). Ces routes sont
    déclarées UNE SEULE FOIS en Python mais exposées sous deux préfixes —
    impossible d'y attacher une garde `require_module_active(module_code)`
    figée sur un seul module sans bloquer injustement l'autre préfixe.
    Passe dès que l'UN des modules listés est actif pour l'organisation
    (jamais les deux exigés)."""

    async def dependency(
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        blocked_error: AppError | None = None
        for module_code in module_codes:
            if await is_module_active(db, organization_id, module_code):
                try:
                    await assert_module_entitled(db, organization_id, module_code)
                    return
                except AppError as exc:
                    if exc.code != "module_entitlement_unavailable":
                        raise
                    blocked_error = exc
        if blocked_error is not None:
            raise blocked_error
        raise AppError(
            code="module_inactive",
            message=f"Aucun des modules {', '.join(module_codes)} n'est actif pour cette organisation.",
            status_code=403,
        )

    return dependency
