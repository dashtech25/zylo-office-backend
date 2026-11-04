"""Consentements versionnés de la facturation (BE-076).

Route : `POST /api/v1/billing/consents` (app/billing/consent_router.py).

Contrat, dans cet ordre :
1. Permission : l'appelant doit détenir `billing.consent.record` sur l'organisation
   courante (rôles acheteur ACTF-04 et contact de facturation ACTF-05). Sinon
   `FORBIDDEN` (403), rien n'est écrit.
2. Périmètre : le compte (`accountId`, un `billing_payer`) doit être rattaché au tenant
   courant par un abonnement (`beneficiaryTenantId`). Un compte d'un autre tenant ou
   inexistant reçoit la même réponse `SCOPE_MISMATCH` (403) : aucune fuite d'existence.
3. Correction : si `correctionOfId` est fourni, l'entrée d'origine doit exister et porter
   le même compte, sinon `SCOPE_MISMATCH`. La correction est une nouvelle ligne ; l'origine
   n'est jamais modifiée (append-only, garanti par la base).

La personne est l'utilisateur authentifié ; l'heure est celle du serveur. Commit à la fin.
Le rattachement compte / tenant est une recommandation (QE-FAC-22), non une décision.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import ConsentRecord, Subscription
from app.billing.permissions import BILLING_CONSENT_RECORD
from app.rbac.service import user_has_permission


async def enregistrer_consentement(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    personne_id: uuid.UUID,
    account_id: uuid.UUID,
    consent_text_version: str,
    scope: str,
    correction_of_id: uuid.UUID | None,
) -> ConsentRecord:
    """Enregistre un consentement, ou sa correction, et renvoie la ligne créée.

    Erreurs : `FORBIDDEN` sans permission ; `SCOPE_MISMATCH` si le compte n'est pas
    rattaché au tenant, ou si la correction vise une autre entrée du même compte.
    """
    if not await user_has_permission(db, personne_id, tenant_id, BILLING_CONSENT_RECORD):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    rattache = await db.scalar(select(Subscription.id).where(
        Subscription.payerId == account_id,
        Subscription.beneficiaryTenantId == tenant_id,
    ).limit(1))
    if rattache is None:
        raise billing_error(BillingErrorCode.SCOPE_MISMATCH)

    if correction_of_id is not None:
        origine = await db.scalar(select(ConsentRecord.accountId).where(ConsentRecord.id == correction_of_id))
        if origine is None or origine != account_id:
            raise billing_error(BillingErrorCode.SCOPE_MISMATCH)

    consentement = ConsentRecord(
        personId=personne_id,
        accountId=account_id,
        consentTextVersion=consent_text_version,
        scope=scope,
        correctionOfId=correction_of_id,
    )
    db.add(consentement)
    await db.commit()
    await db.refresh(consentement)
    return consentement
