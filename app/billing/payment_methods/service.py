"""Écriture des moyens de paiement et émission de `PaymentMethodChanged` (BE-116).

Contrat de transaction : chaque fonction écrit la ligne et l'événement dans la même transaction,
puis committe. Si l'émission échoue, la transaction est annulée : un changement sans événement
n'est jamais committé (CA-5). Une seule méthode est sélectionnée par organisation : la sélection
désélectionne les autres avant de sélectionner la cible, et l'index partiel de la table garantit
l'invariant côté base.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.events.emission import emettre_evenement_facturation
from app.billing.models import PaymentMethodReference
from app.core.errors import AppError

# Nom de l'événement de contrat (BE-116, CA-5) ; schéma de payload en version 1.
TYPE_EVENEMENT_MOYEN_PAIEMENT = "PaymentMethodChanged"
VERSION_SCHEMA_MOYEN_PAIEMENT = 1
ACTION_AJOUT = "added"
ACTION_SELECTION = "selected"


async def add_payment_method(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, token_reference: str
) -> PaymentMethodReference:
    """Ajoute une référence de token et la sélectionne ; ajouter remplace la méthode précédente.

    La méthode précédemment sélectionnée est désélectionnée (et non supprimée) : l'historique des
    références reste lisible. Émet `PaymentMethodChanged` avec l'action `added`. La valeur du token
    n'entre jamais dans le payload de l'événement. Erreur : relève l'exception de l'émission,
    après annulation de la transaction.
    """
    try:
        await db.execute(
            update(PaymentMethodReference)
            .where(PaymentMethodReference.organizationId == organization_id, PaymentMethodReference.selected.is_(True))
            .values(selected=False)
        )
        ligne = PaymentMethodReference(organizationId=organization_id, tokenReference=token_reference, selected=True)
        db.add(ligne)
        await db.flush()
        await emettre_evenement_facturation(
            db, _enveloppe(organization_id, user_id, ligne, ACTION_AJOUT), emetteur_tenant=organization_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(ligne)
    return ligne


async def select_payment_method(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, method_id: uuid.UUID
) -> PaymentMethodReference:
    """Sélectionne une méthode de l'organisation et désélectionne les autres ; émet `PaymentMethodChanged`.

    Erreur `payment_method_not_found` (404) si la méthode n'existe pas dans l'organisation du chemin :
    une méthode d'une autre organisation répond comme une méthode inexistante (isolation tenant).
    """
    ligne = (
        await db.execute(
            select(PaymentMethodReference).where(
                PaymentMethodReference.id == method_id,
                PaymentMethodReference.organizationId == organization_id,
            )
        )
    ).scalars().first()
    if ligne is None:
        raise AppError(code="payment_method_not_found", message="Moyen de paiement introuvable.", status_code=404)
    try:
        await db.execute(
            update(PaymentMethodReference)
            .where(PaymentMethodReference.organizationId == organization_id, PaymentMethodReference.id != method_id)
            .values(selected=False)
        )
        await db.execute(
            update(PaymentMethodReference)
            .where(PaymentMethodReference.id == method_id)
            .values(selected=True)
        )
        await emettre_evenement_facturation(
            db, _enveloppe(organization_id, user_id, ligne, ACTION_SELECTION), emetteur_tenant=organization_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(ligne)
    return ligne


def _enveloppe(
    organization_id: uuid.UUID, user_id: uuid.UUID, ligne: PaymentMethodReference, action: str
) -> dict[str, Any]:
    """Enveloppe BE-150 de `PaymentMethodChanged`.

    Le payload ne porte que l'identifiant de la méthode et l'action ; la référence de token reste
    hors de l'événement, qui sort de la base de facturation.
    """
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": TYPE_EVENEMENT_MOYEN_PAIEMENT,
        "schemaVersion": VERSION_SCHEMA_MOYEN_PAIEMENT,
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"userId": str(user_id)},
        "subject": {"type": "PaymentMethodReference", "id": str(ligne.id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"paymentMethodId": str(ligne.id), "action": action, "selected": True},
    }
