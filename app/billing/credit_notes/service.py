"""Émission d'un avoir sur une facture finalisée (BE-087).

Règles tenues par `emettre_avoir`, dans cet ordre, toutes avant toute écriture :

1. Motif obligatoire, non vide après suppression des espaces (CA-2) : sinon
   `APPROVAL_REQUIRED`. Le motif est exigé par l'audit (geste sensible, BE-073).
2. Périmètre : la facture doit appartenir à l'organisation courante. Hors périmètre ou
   inexistante, la réponse est 404 `invoice_not_found` (CA-4, même réponse que BE-086).
3. Approbation (QE-FAC-09, recommandation appliquée) : `approver_id` doit être renseigné,
   différent de l'acteur, et membre de l'organisation. Sinon `APPROVAL_REQUIRED` (CA-3).
   L'approbateur ne reçoit pas de permission ici : son rôle ACTF-08 reste INCONNU
   (QE-FAC-09) ; seule la séparation des personnes et l'appartenance sont contrôlées.
4. Statut : seule une facture `finalized` reçoit un avoir ; un brouillon ou une facture
   non finalisée renvoie `INVALID_TRANSITION` (CA-1).

Écritures, dans une seule transaction : une ligne `credit_note` (statut `issued`, devise
copiée de la facture) et une entrée d'audit `billing.credit_note.issue` portant le motif et
l'approbateur. La ligne `invoice` n'est jamais écrite (CA-1). La facture est verrouillée
(`FOR UPDATE`) pour que deux émissions concurrentes lisent le même état.

Hors périmètre, à traiter ailleurs :
- plafond cumulé des avoirs par rapport au total de la facture : non défini, aucun plafond
  n'est appliqué ici (à arbitrer, QE-FAC-09) ;
- événement de domaine pour l'avoir : non défini dans BE-087 ; aucun n'est publié.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.audit import record_audit_entry
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.invoices import _facture_de_l_organisation_verrouillee
from app.billing.models import CreditNote
from app.identity.models import OrganizationUser

STATUT_AVOIR_EMIS = "issued"
STATUT_FACTURE_FINALISEE = "finalized"


async def _est_membre(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    """Vrai si l'utilisateur a une ligne d'appartenance à l'organisation (seule preuve, identity/models.py)."""
    return await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id, OrganizationUser.userId == user_id,
        )
    ) is not None


async def emettre_avoir(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_id: uuid.UUID,
    invoice_id: uuid.UUID,
    *,
    amount: int,
    reason: str,
    approver_id: uuid.UUID | None,
) -> CreditNote:
    """Émet un avoir de `amount` (unités mineures, > 0) sur la facture `invoice_id`.

    Erreurs : voir la docstring du module (APPROVAL_REQUIRED, invoice_not_found, INVALID_TRANSITION).
    En cas d'erreur, rien n'est écrit. Retourne l'avoir relu après commit.
    """
    motif = (reason or "").strip()
    if not motif:
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)
    facture = await _facture_de_l_organisation_verrouillee(db, organization_id, invoice_id)
    if approver_id is None or approver_id == actor_id or not await _est_membre(db, organization_id, approver_id):
        raise billing_error(BillingErrorCode.APPROVAL_REQUIRED)
    if facture.status != STATUT_FACTURE_FINALISEE:
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)
    avoir = CreditNote(
        id=uuid.uuid4(), invoiceId=facture.id, amount=amount, currency=facture.currency,
        reason=motif, status=STATUT_AVOIR_EMIS, createdAt=datetime.now(timezone.utc),
    )
    db.add(avoir)
    await record_audit_entry(
        db, organization_id, actor_id,
        action="billing.credit_note.issue", scope="payeur",
        target_type="CreditNote", target_id=avoir.id,
        before_json=None, after_json={"status": STATUT_AVOIR_EMIS, "amount": amount, "invoiceId": str(facture.id)},
        summary=f"Avoir {avoir.id} sur la facture {facture.id}", reason=motif, approver_id=approver_id,
    )
    await db.commit()
    await db.refresh(avoir)
    return avoir
