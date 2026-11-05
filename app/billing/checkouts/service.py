"""Service des checkouts (BE-081) : création depuis un devis accepté, et lecture.

Ce module est la seule porte d'écriture des checkouts. Il réutilise, sans les redéfinir :
- `billing.errors.billing_error` (BE-070) pour les codes du catalogue ;
- `billing.models.Quote` et `ConsentRecord` pour le devis et le consentement (BE-077, BE-076).

Machine d'état : création à `open`. Aucune fonction de ce module ne produit `completed`
(CA-2) : la confirmation d'un paiement appartient à BE-083 / BE-084.

Ordre des contrôles à la création, qui est aussi l'ordre des écritures :
1. Permission `billing.subscription.manage` (acheteur, ACTF-04) : sinon `FORBIDDEN`.
2. Devis du tenant courant : sinon `quote_not_found` (404), comme un devis inexistant.
3. État du devis : `accepted` requis. Un devis expiré (statut `expired`, ou `priced` dont
   `expiresAt` est passé) renvoie `QUOTE_EXPIRED` ; tout autre état non accepté renvoie
   `INVALID_TRANSITION`. Un devis non accepté ne crée jamais de checkout.
4. Consentement : au moins une ligne `consent_record` pour le compte payeur du devis,
   sinon `CONSENT_REQUIRED`.
5. Insertion à `open`, `version = 1`, commit.

Lecture : tenant d'abord (checkout hors tenant = `checkout_not_found`, 404, identique à
un identifiant inconnu), puis permission `billing.subscription.read` (`FORBIDDEN`).

Le périmètre tenant passe par la table `quote` (`beneficiaryTenantId`) : la table
`checkout` ne porte pas de colonne tenant (définition BE-081, QE-FAC-04).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Checkout, ConsentRecord, Quote
from app.billing.permissions import SUBSCRIPTION_MANAGE, SUBSCRIPTION_READ
from app.core.errors import AppError
from app.rbac.service import user_has_permission

STATUT_OUVERT = "open"
STATUT_DEVIS_ACCEPTE = "accepted"
STATUT_DEVIS_EXPIRE = "expired"
STATUT_DEVIS_PRICE = "priced"


async def creer_checkout(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quote_id: uuid.UUID,
) -> Checkout:
    """Ouvre un checkout `open` depuis un devis `accepted` du tenant, consentement requis.

    Erreurs, dans l'ordre : `FORBIDDEN` (403) sans permission d'acheteur ; `quote_not_found`
    (404) ; `QUOTE_EXPIRED` (422) ; `INVALID_TRANSITION` (409) si le devis n'est pas
    `accepted` ; `CONSENT_REQUIRED` (422) sans consentement enregistré pour le payeur.
    Aucune ligne n'est écrite en cas d'erreur.
    """
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    devis = await db.scalar(select(Quote).where(
        Quote.id == quote_id,
        Quote.beneficiaryTenantId == organization_id,
    ))
    if devis is None:
        raise AppError(code="quote_not_found", message="Devis introuvable.", status_code=404)

    if devis.status == STATUT_DEVIS_EXPIRE or (
        devis.status == STATUT_DEVIS_PRICE
        and devis.expiresAt is not None
        and devis.expiresAt <= datetime.now(timezone.utc)
    ):
        raise billing_error(BillingErrorCode.QUOTE_EXPIRED)
    if devis.status != STATUT_DEVIS_ACCEPTE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    consentement = await db.scalar(
        select(ConsentRecord.id).where(ConsentRecord.accountId == devis.payerId).limit(1)
    )
    if consentement is None:
        raise billing_error(BillingErrorCode.CONSENT_REQUIRED)

    checkout = Checkout(quoteId=devis.id, status=STATUT_OUVERT, version=1)
    db.add(checkout)
    await db.commit()
    await db.refresh(checkout)
    return checkout


async def lire_checkout(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    checkout_id: uuid.UUID,
) -> Checkout:
    """Renvoie le checkout si son devis appartient au tenant, puis si l'acteur peut le lire.

    Tenant d'abord : un checkout hors tenant est `checkout_not_found` (404), identique à un
    identifiant inconnu. La permission `billing.subscription.read` vient ensuite (`FORBIDDEN`).
    """
    checkout = await db.scalar(
        select(Checkout)
        .join(Quote, Quote.id == Checkout.quoteId)
        .where(Checkout.id == checkout_id, Quote.beneficiaryTenantId == organization_id)
    )
    if checkout is None:
        raise AppError(code="checkout_not_found", message="Checkout introuvable.", status_code=404)
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    return checkout
