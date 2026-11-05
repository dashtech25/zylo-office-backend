"""Service des devis (BE-077) : création, lecture, acceptation.

Ce module est la seule porte d'écriture des devis. Il réutilise, sans les redéfinir :
- `catalog_snapshot.capturer_version_offre` (BE-075) pour figer l'offre au devis ;
- `pricing.resolution.resoudre_prix` (BE-078) pour le prix, la devise et la taxe ;
- `billing.errors.billing_error` (BE-070) pour tous les codes d'erreur.

Machine d'état : `created -> priced -> accepted`, avec `expired` atteint par
expiration. `revoked` n'est pas produit ici. Toute transition incrémente `version`
(verrou optimiste, BE-072).

Règles :

- Permissions : la création et l'acceptation exigent `billing.subscription.manage`
  (SUBSCRIPTION_MANAGE) ; la lecture exige `billing.subscription.read`. Recommandation
  provisoire : la permission d'acheteur (ACTF-04) et le périmètre payeur ne sont pas
  encore définis (PH-08, Q-06, QE-FAC-03). Sans permission : `FORBIDDEN`.
- Ordre des contrôles en lecture et en acceptation : tenant d'abord (devis hors
  tenant = `quote_not_found` 404, identique à un identifiant inconnu), puis permission
  pour la lecture. Pour l'acceptation et la création, la permission précède le tenant,
  comme en BE-090.
- Création : le devis est persisté à l'état `created` avant la résolution de prix. Si
  BE-078 échoue (PRICE / CURRENCY / TAX_NOT_CONFIGURED), l'erreur est renvoyée avec
  `details = [{"quoteId": ...}]` et le devis reste `created` : aucun prix n'est deviné.
- Expiration : la durée de validité n'est pas définie (QE-FAC-21). Un devis sans
  `expiresAt` n'expire pas ; un devis dont `expiresAt` est passé, ou déjà `expired`,
  est refusé par `QUOTE_EXPIRED` et ne crée aucune souscription.
- Le devis n'ouvre aucun droit : l'acceptation ne crée pas de souscription. Le passage
  à l'achat est le rôle de BE-081.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import catalog_snapshot
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import BillingPayer, Quote
from app.billing.permissions import SUBSCRIPTION_MANAGE, SUBSCRIPTION_READ
from app.billing.pricing.resolution import resoudre_prix
from app.core.errors import AppError
from app.rbac.service import user_has_permission

STATUT_CREE = "created"
STATUT_PRICE = "priced"
STATUT_ACCEPTE = "accepted"
STATUT_EXPIRE = "expired"


async def creer_devis(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    plan_code: str,
    scenario: str,
    payer_id: uuid.UUID,
) -> Quote:
    """Crée un devis pour le tenant `organization_id` et renvoie la ligne finale.

    Ordre : permission ; compte payeur existant (`payer_not_found`, 404) ; capture de
    l'offre (BE-075, qui peut lever `plan_not_found` ou `INVALID_TRANSITION`) ; insertion
    à `created` ; résolution du prix (BE-078) qui fait passer à `priced`.
    `scenario` est fourni par l'appelant : la liste des scénarios n'est pas définie
    (QE-FAC-10). Commit à chaque étape, pour que le devis `created` survive à une erreur
    de prix.
    """
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    payeur = await db.scalar(select(BillingPayer).where(BillingPayer.id == payer_id))
    if payeur is None:
        raise AppError(code="payer_not_found", message="Compte payeur introuvable.", status_code=404)

    instantane = await catalog_snapshot.capturer_version_offre(
        db, organization_id=organization_id, plan_code=plan_code, actor_user_id=actor_user_id
    )
    devis = Quote(
        payerId=payer_id,
        beneficiaryTenantId=organization_id,
        planVersionSnapshotId=instantane.id,
        status=STATUT_CREE,
        version=1,
        expiresAt=None,
    )
    db.add(devis)
    await db.commit()
    await db.refresh(devis)

    try:
        prix = await resoudre_prix(db, organization_id=organization_id, object_code=plan_code, scenario=scenario)
    except AppError as erreur:
        # Le code d'origine (PRICE / CURRENCY / TAX_NOT_CONFIGURED) est conservé ; le
        # devis reste `created` et son identifiant est joint pour le relire.
        raise AppError(
            code=erreur.code,
            message=erreur.message,
            status_code=erreur.status_code,
            details=[{"quoteId": str(devis.id)}],
        ) from erreur

    devis.status = STATUT_PRICE
    devis.pricingSnapshotJson = prix.as_snapshot()
    devis.version += 1
    await db.commit()
    await db.refresh(devis)
    return devis


async def lire_devis(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quote_id: uuid.UUID,
) -> Quote:
    """Renvoie le devis si il appartient au tenant, puis si l'acteur peut le lire.

    Tenant d'abord : un devis d'un autre tenant est `quote_not_found` (404), exactement
    comme un identifiant inconnu (CA-4). La permission vient ensuite (`FORBIDDEN`, 403).
    """
    devis = await _charger_du_tenant(db, organization_id, quote_id)
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    return devis


async def accepter_devis(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    quote_id: uuid.UUID,
    expected_version: int | None = None,
) -> Quote:
    """Accepte un devis `priced` valide ; ne crée aucune souscription.

    Ordre des contrôles : permission (`FORBIDDEN`) ; tenant (`quote_not_found`) ;
    `expectedVersion` s'il est fourni (`VERSION_CONFLICT`, rien n'est modifié) ; devis
    expiré par date ou déjà `expired` (`QUOTE_EXPIRED`, le devis passe `expired`) ; sinon
    seul `priced` peut être accepté (`INVALID_TRANSITION` pour les autres états).
    """
    if not await user_has_permission(db, actor_user_id, organization_id, SUBSCRIPTION_MANAGE):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    devis = await _charger_du_tenant(db, organization_id, quote_id)

    if expected_version is not None and expected_version != devis.version:
        raise billing_error(BillingErrorCode.VERSION_CONFLICT)

    if devis.status == STATUT_EXPIRE:
        raise billing_error(BillingErrorCode.QUOTE_EXPIRED)
    if devis.status == STATUT_PRICE and devis.expiresAt is not None and devis.expiresAt <= datetime.now(timezone.utc):
        devis.status = STATUT_EXPIRE
        devis.version += 1
        await db.commit()
        raise billing_error(BillingErrorCode.QUOTE_EXPIRED)
    if devis.status != STATUT_PRICE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    devis.status = STATUT_ACCEPTE
    devis.version += 1
    await db.commit()
    await db.refresh(devis)
    return devis


async def _charger_du_tenant(db: AsyncSession, organization_id: uuid.UUID, quote_id: uuid.UUID) -> Quote:
    """Devis du tenant ; `quote_not_found` (404) sinon, sans distinguer hors tenant et inconnu."""
    devis = await db.scalar(select(Quote).where(
        Quote.id == quote_id,
        Quote.beneficiaryTenantId == organization_id,
    ))
    if devis is None:
        raise AppError(code="quote_not_found", message="Devis introuvable.", status_code=404)
    return devis
