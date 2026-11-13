"""Payeur, tenant bénéficiaire et administrateur d'un abonnement (BE-071).

Un abonnement sépare trois rôles qui étaient confondus dans `organizationId` :

- le **payeur** (`billing_payer`, colonne `subscription.payerId`) règle la facture.
  Il n'a aucun droit d'accès du seul fait de payer : un paiement réussi n'alimente
  jamais `subscription_entitlement` (CA-4) ;
- le **tenant bénéficiaire** (`subscription.beneficiaryTenantId`) est l'organisation
  dont les droits découlent de l'abonnement. Toute lecture et toute écriture passe
  par ce périmètre : un abonnement d'un autre tenant est traité comme inexistant
  (CA-3), sans fuite d'existence ;
- l'**administrateur** (`subscription.adminUserId`) est l'utilisateur du tenant qui
  gère l'abonnement. Seul l'administrateur courant peut le changer (CA-2).

Ce module n'expose aucune route : il sert les routes futures de facturation et
reste la seule porte d'écriture de ces trois rôles. Les règles ne sont pas
déduites du lien payeur : payer ne donne ni accès au tenant, ni droit d'administration.

Codes d'erreur : `FORBIDDEN` (403) pour un acteur qui n'est pas l'administrateur,
`subscription_not_found` (404) pour un abonnement hors périmètre du tenant demandé
(même réponse qu'un abonnement inexistant, voir app/billing/errors.py).

Compte payeur : la frontière tenant / organisation du compte payeur n'est pas
décidée (QE-FAC-22) ; `accountRef` reste donc une référence opaque.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import BillingPayer, Subscription
from app.core.errors import AppError


async def creer_payeur(db: AsyncSession, payer_kind: str, account_ref: str) -> BillingPayer:
    """Enregistre un payeur d'abonnement et renvoie sa ligne (validée, commit inclus).

    `payer_kind` et `account_ref` sont posés tels quels : la liste des sortes de
    payeur et le format de la référence relèvent de QE-FAC-04 et QE-FAC-22, non fixés.
    """
    payeur = BillingPayer(payerKind=payer_kind, accountRef=account_ref)
    db.add(payeur)
    await db.commit()
    await db.refresh(payeur)
    return payeur


async def changer_administrateur(
    db: AsyncSession,
    subscription_id: uuid.UUID,
    tenant_id: uuid.UUID,
    acteur_user_id: uuid.UUID,
    nouvel_admin_user_id: uuid.UUID,
) -> Subscription:
    """Change l'administrateur d'un abonnement du tenant bénéficiaire (CA-2, CA-3).

    Règles, dans cet ordre :
    1. L'abonnement doit appartenir à `tenant_id` (son `beneficiaryTenantId`). Sinon
       `subscription_not_found` (404) : un abonnement d'un autre tenant n'est ni lu
       ni signalé comme existant.
    2. Seul l'administrateur courant (`adminUserId`) peut agir. Un payeur qui n'est
       pas administrateur, ou un abonnement sans administrateur, reçoit `FORBIDDEN`
       (403) et `adminUserId` reste intact.

    Ne fait aucun contrôle de droit par permission RBAC : la règle est portée par
    le lien d'administration de l'abonnement lui-même. Commit à la fin.
    """
    abonnement = await db.scalar(select(Subscription).where(
        Subscription.id == subscription_id,
        Subscription.beneficiaryTenantId == tenant_id,
    ))
    if abonnement is None:
        raise AppError(code="subscription_not_found", message="Abonnement introuvable.", status_code=404)
    if abonnement.adminUserId is None or abonnement.adminUserId != acteur_user_id:
        raise billing_error(BillingErrorCode.FORBIDDEN)
    abonnement.adminUserId = nouvel_admin_user_id
    await db.commit()
    await db.refresh(abonnement)
    return abonnement
