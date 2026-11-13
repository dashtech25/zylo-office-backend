"""Demande d'export des données de facturation d'un compte payeur (BE-098).

Route : `POST /api/v1/billing/data-exports` (app/billing/exports/router.py).

Contrat, dans cet ordre :
1. Permission : le demandeur doit détenir `billing.data_export.request` sur le tenant
   courant (rôles ACTF-04 acheteur et ACTF-05 contact de facturation). Sinon `FORBIDDEN`
   (403) ; rien n'est lu ni écrit.
2. Périmètre : le compte (`accountId`, un `billing_payer`) doit être rattaché au tenant
   courant par un abonnement (`beneficiaryTenantId`). Un compte d'un autre tenant ou
   inexistant reçoit la même réponse `SCOPE_MISMATCH` (403) : aucune donnée, aucune fuite
   d'existence (CA-4).
3. Contenu : seuls les abonnements de ce compte dans ce tenant, et leurs factures, sont lus.
   Les champs sont listés explicitement (`CHAMPS_ABONNEMENT`, `CHAMPS_FACTURE`) ; tout
   champ absent de ces listes n'est jamais exporté, y compris les références de paiement (CA-1,
   CA-2).
4. Trace : une ligne `data_export_request` (`status` = `ready`, `fileRef` = NULL tant qu'aucun
   stockage de fichier n'est branché, QE-FAC-25) et une entrée d'audit `billing.data_export.request`
   (BE-073) sont écrites dans la même transaction.

Le contenu n'est jamais stocké : il est renvoyé directement dans la réponse. Commit à la fin.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import DataExportRequest, Invoice, Subscription
from app.billing.permissions import BILLING_DATA_EXPORT_REQUEST
from app.rbac.service import user_has_permission

# Liste blanche des champs exportés. Un champ n'y figure que s'il est une donnée de
# facturation non secrète : les références fournisseur, les URL de paiement et les
# tentatives de paiement en sont exclues par construction (CA-2).
CHAMPS_ABONNEMENT = (
    "id", "planId", "status", "lifecycleStatus", "financialStatus", "incidentStatus",
    "startDate", "endDate",
)
CHAMPS_FACTURE = (
    "id", "subscriptionId", "currency", "status", "amountMinor", "total",
    "issuedAt", "paidAt", "finalizedAt",
)


def _valeur(valeur: Any) -> Any:
    """Rend une valeur JSON-compatible : dates en ISO 8601, UUID en texte, le reste tel quel."""
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


def _ligne(objet: Any, champs: tuple[str, ...]) -> dict[str, Any]:
    """Extrait uniquement les `champs` de l'objet, dans la liste blanche."""
    return {champ: _valeur(getattr(objet, champ)) for champ in champs}


async def demander_export(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    demandeur_id: uuid.UUID,
    account_id: uuid.UUID,
    scope: str,
) -> tuple[DataExportRequest, dict[str, Any]]:
    """Crée la demande, puis renvoie la ligne créée et le contenu de l'export.

    Erreurs : `FORBIDDEN` sans permission ; `SCOPE_MISMATCH` si le compte n'est pas
    rattaché au tenant courant. En cas d'erreur, rien n'est écrit.
    """
    if not await user_has_permission(db, demandeur_id, tenant_id, BILLING_DATA_EXPORT_REQUEST):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    abonnements = list((await db.scalars(select(Subscription).where(
        Subscription.payerId == account_id,
        Subscription.beneficiaryTenantId == tenant_id,
    ).order_by(Subscription.id))).all())
    if not abonnements:
        raise billing_error(BillingErrorCode.SCOPE_MISMATCH)

    identifiants_abonnements = [abonnement.id for abonnement in abonnements]
    factures = list((await db.scalars(select(Invoice).where(
        Invoice.subscriptionId.in_(identifiants_abonnements),
    ).order_by(Invoice.id))).all())

    contenu = {
        "scope": scope,
        "accountId": str(account_id),
        "subscriptions": [_ligne(abonnement, CHAMPS_ABONNEMENT) for abonnement in abonnements],
        "invoices": [_ligne(facture, CHAMPS_FACTURE) for facture in factures],
    }

    demande = DataExportRequest(
        id=uuid.uuid4(),
        organizationId=tenant_id,
        accountId=account_id,
        scope=scope,
        requestedBy=demandeur_id,
        status="ready",
        requestedAt=datetime.now(timezone.utc),
        fileRef=None,
    )
    db.add(demande)
    await record_audit_entry(
        db,
        tenant_id,
        demandeur_id,
        action="billing.data_export.request",
        scope="payeur",
        target_type="data_export_request",
        target_id=demande.id,
        before_json=None,
        after_json={"status": "ready", "invoiceCount": len(factures)},
        summary="Demande d'export des données de facturation d'un compte payeur.",
    )
    await db.commit()
    await db.refresh(demande)
    return demande, contenu
