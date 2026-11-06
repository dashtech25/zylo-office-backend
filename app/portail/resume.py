"""Résumé du portail filtré par permission (BE-109).

`build_portal_summary` agrège les lectures déjà autorisées par BE-106 (membres), BE-107
(entitlements), BE-108 (usage) et la lecture de l'abonnement (facturation). Chaque section n'est
incluse que si l'utilisateur détient sa permission ; une section refusée est absente de la
réponse, sans erreur globale. La permission du portail (`portal.summary.read`) est vérifiée
avant l'appel, par la dépendance `exiger_action` de la route : cette fonction ne la revérifie pas.

Les sections ne sont pas recalculées ici : chacune appelle la lecture existante de son domaine,
ce qui garde une seule forme de réponse par donnée. Lecture seule ; aucune écriture.
Écart : la section facturation porte l'état de l'abonnement le plus récent (statuts seuls), sous la
permission `billing.subscription.read` ; la fiche écrit `billing:read`.
"""

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.lecture_router import get_organization_usage, list_organization_entitlements
from app.billing.models import Subscription
from app.billing.permissions import ORGANIZATION_ENTITLEMENT_READ, ORGANIZATION_USAGE_READ, SUBSCRIPTION_READ
from app.billing.schemas import EntitlementsOrganisationResponse, UsageOrganisationResponse
from app.identity import membres
from app.identity.permissions import MEMBERS_READ
from app.rbac.portee_organisation import OrgScope
from app.rbac.schemas import OrganizationMemberResponse
from app.rbac.service import user_has_permission


class BillingSummary(BaseModel):
    """État de l'abonnement le plus récent de l'organisation (statuts seuls, sans montant)."""

    subscriptionId: str
    status: str
    lifecycleStatus: str
    financialStatus: str


class PortalSummaryResponse(BaseModel):
    """Réponse de `GET /organizations/{organization_id}/portal-summary` (BE-109).

    Chaque champ est une section ; une section non autorisée n'est pas assignée et disparaît de la
    réponse grâce à `response_model_exclude_unset`. Un corps vide signifie : aucune section accordée.
    """

    entitlements: EntitlementsOrganisationResponse | None = None
    usage: UsageOrganisationResponse | None = None
    members: list[OrganizationMemberResponse] | None = None
    billing: BillingSummary | None = None


async def build_portal_summary(db: AsyncSession, scope: OrgScope) -> PortalSummaryResponse:
    """Assemble le résumé de l'organisation du `scope`, en ne lisant que les sections autorisées.

    Ordre de contrôle : une permission par section (`user_has_permission`) ; la section n'est lue
    qu'après ce contrôle, donc une donnée refusée n'est jamais chargée. Toutes les lectures
    reçoivent `scope.organization_id` : aucune donnée d'une autre organisation n'est atteinte.
    """
    resume: dict = {}
    if await user_has_permission(db, scope.user_id, scope.organization_id, ORGANIZATION_ENTITLEMENT_READ):
        resume["entitlements"] = await list_organization_entitlements(organization_id=scope.organization_id, db=db)
    if await user_has_permission(db, scope.user_id, scope.organization_id, ORGANIZATION_USAGE_READ):
        resume["usage"] = await get_organization_usage(scope=scope, db=db)
    if await user_has_permission(db, scope.user_id, scope.organization_id, MEMBERS_READ):
        resume["members"] = await membres.list_members(db, scope.organization_id)
    if await user_has_permission(db, scope.user_id, scope.organization_id, SUBSCRIPTION_READ):
        resume["billing"] = await _resume_facturation(db, scope)
    return PortalSummaryResponse(**resume)


async def _resume_facturation(db: AsyncSession, scope: OrgScope) -> BillingSummary | None:
    """État de l'abonnement le plus récent de l'organisation, ou nul s'il n'en a pas."""
    ligne = (
        await db.execute(
            select(Subscription)
            .where(Subscription.organizationId == scope.organization_id)
            .order_by(Subscription.createdAt.desc())
            .limit(1)
        )
    ).scalars().first()
    if ligne is None:
        return None
    return BillingSummary(
        subscriptionId=str(ligne.id),
        status=ligne.status,
        lifecycleStatus=ligne.lifecycleStatus,
        financialStatus=ligne.financialStatus,
    )
