"""Machine d'état des trois axes d'un abonnement (BE-079).

Un abonnement porte trois états indépendants, chacun dans sa colonne :

- `lifecycleStatus` (cycle de vie) : une transition ne touche que cette colonne ;
- `financialStatus` (finances) : idem, indépendant du cycle de vie et de l'incident ;
- `incidentStatus` (incident de paiement ou de litige) : idem.

Un seul état « abonnement » fusionnerait ces réalités : il est interdit. Aucun de ces
trois états n'accorde de droit d'accès ; les droits restent calculés par
app/billing/entitlements.py et ne se déduisent pas de `lifecycleStatus = active`.

La transition d'un axe est la seule porte d'écriture de ces trois états :
`transition_etat`. Elle vérifie la transition contre la table de l'axe ci-dessous,
verrouille la ligne (`SELECT ... FOR UPDATE`) et incrémente `version` (BE-072).
Une transition absente de la table, un axe inconnu ou une valeur cible inconnue
renvoie `INVALID_TRANSITION` (409) et ne modifie rien.

Les états ci-dessous sont ceux de la machine d'état conceptuelle
(00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md) ;
les valeurs exactes des colonnes relèvent de QE-FAC-04 (non défini). Les valeurs
`financialStatus` (none, pending, settled, failed) sont donc provisoires.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Subscription
from app.core.errors import AppError

# Cycle de vie : état courant -> cibles permises. `subscription_closed` est terminal.
TRANSITIONS_CYCLE_DE_VIE: dict[str, frozenset[str]] = {
    "pending": frozenset({"trialing", "active"}),
    "trialing": frozenset({"active", "expired"}),
    "active": frozenset({"change_scheduled", "cancel_scheduled", "expired"}),
    "change_scheduled": frozenset({"active"}),
    "cancel_scheduled": frozenset({"active", "cancelled"}),
    "expired": frozenset({"close_pending"}),
    "cancelled": frozenset({"close_pending"}),
    "close_pending": frozenset({"subscription_closed"}),
    "subscription_closed": frozenset(),
}

# Finances : indépendantes de la période et de l'incident.
TRANSITIONS_FINANCIERES: dict[str, frozenset[str]] = {
    "none": frozenset({"pending"}),
    "pending": frozenset({"settled", "failed"}),
    "settled": frozenset(),
    "failed": frozenset({"pending"}),
}

# Incident de paiement ou de litige : `none` est l'état sans incident.
TRANSITIONS_INCIDENT: dict[str, frozenset[str]] = {
    "none": frozenset({"past_due", "disputed", "incomplete"}),
    "past_due": frozenset({"grace", "suspended", "none"}),
    "grace": frozenset({"suspended", "none"}),
    "suspended": frozenset({"none"}),
    "disputed": frozenset({"none"}),
    "incomplete": frozenset({"none"}),
}

# Nom d'axe exposé à l'appelant -> (colonne ORM, table de transitions).
AXES: dict[str, tuple[str, dict[str, frozenset[str]]]] = {
    "lifecycle": ("lifecycleStatus", TRANSITIONS_CYCLE_DE_VIE),
    "financial": ("financialStatus", TRANSITIONS_FINANCIERES),
    "incident": ("incidentStatus", TRANSITIONS_INCIDENT),
}


async def charger_abonnement_du_tenant(
    db: AsyncSession, subscription_id: uuid.UUID, tenant_id: uuid.UUID, *, verrou: bool = False
) -> Subscription | None:
    """Abonnement dont le tenant bénéficiaire est `tenant_id`, ou `None`.

    Le périmètre est `beneficiaryTenantId` ; pour les lignes antérieures à BE-071 où il
    est nul, c'est `organizationId` (même valeur après backfill). Un abonnement d'un
    autre tenant donne `None`, comme un abonnement inexistant : pas de fuite d'existence.
    `verrou=True` prend un verrou de ligne pour une transition.
    """
    requete = select(Subscription).where(
        Subscription.id == subscription_id,
        func.coalesce(Subscription.beneficiaryTenantId, Subscription.organizationId) == tenant_id,
    )
    if verrou:
        requete = requete.with_for_update()
    return await db.scalar(requete)


async def transition_etat(
    db: AsyncSession, subscription_id: uuid.UUID, tenant_id: uuid.UUID, axe: str, cible: str
) -> Subscription:
    """Fait passer UN axe de l'abonnement à `cible`, les deux autres restent intacts.

    Ordre des contrôles :
    1. abonnement hors du tenant ou inexistant : `subscription_not_found` (404) ;
    2. axe inconnu, ou transition absente de la table de l'axe : `INVALID_TRANSITION` (409).

    Incrémente `version` et valide le tout par un commit. Aucune autre colonne n'est écrite.
    """
    abonnement = await charger_abonnement_du_tenant(db, subscription_id, tenant_id, verrou=True)
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    if axe not in AXES:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    colonne, transitions = AXES[axe]
    etat_courant = getattr(abonnement, colonne)
    if cible not in transitions.get(etat_courant, frozenset()):
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    setattr(abonnement, colonne, cible)
    abonnement.version += 1
    await db.commit()
    await db.refresh(abonnement)
    return abonnement
