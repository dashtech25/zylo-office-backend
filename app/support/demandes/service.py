"""Création d'une demande de support et émission de `SupportRequestCreated` (BE-118).

Contrat de transaction : la ligne et l'événement sont écrits dans la même transaction, puis
committés. Si l'émission échoue, la transaction est annulée : une demande sans événement n'est
jamais committée. Le contrôle de contexte secret précède toute écriture (CA-2).
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.evenements.enveloppe import MARQUEURS_CLE_SECRETE
from app.evenements.outbox import enregistrer_evenement
from app.support.models import SupportRequest

# Nom de l'événement de contrat (BE-118, CA-1) ; schéma de payload en version 1.
TYPE_EVENEMENT_DEMANDE_SUPPORT = "SupportRequestCreated"
VERSION_SCHEMA_DEMANDE_SUPPORT = 1
STATUT_OUVERT = "open"


def verifier_contexte_sans_secret(valeur: Any) -> None:
    """Refuse 400 `secret_context_refused` si une clé du contexte désigne un secret, à tout niveau.

    Seul le nom de la clé est examiné, jamais la valeur. Même liste de marqueurs que
    l'enveloppe d'événement (BE-150) : un secret refusé ici ne peut pas non plus sortir par
    l'outbox.
    """
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            normalisee = str(cle).lower().replace("_", "").replace("-", "")
            if any(marqueur in normalisee for marqueur in MARQUEURS_CLE_SECRETE):
                raise AppError(
                    code="secret_context_refused",
                    message="Le contexte de la demande ne doit contenir ni mot de passe ni token.",
                    status_code=400,
                )
            verifier_contexte_sans_secret(sous_valeur)
    elif isinstance(valeur, list):
        for element in valeur:
            verifier_contexte_sans_secret(element)


async def create_support_request(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, contexte: dict[str, Any] | None
) -> SupportRequest:
    """Crée une demande `open` pour l'organisation, auteur `user_id`, et émet `SupportRequestCreated`.

    `user_id` est toujours l'identité authentifiée (CA-5). Le payload de l'événement ne porte que
    l'identifiant de la demande et son statut : le contexte reste en base, hors de l'outbox.
    Erreurs : `secret_context_refused` (400) avant écriture ; erreurs de `enregistrer_evenement`
    après annulation de la transaction.
    """
    if contexte is not None:
        verifier_contexte_sans_secret(contexte)
    try:
        ligne = SupportRequest(organizationId=organization_id, statut=STATUT_OUVERT, contexte=contexte, createdBy=user_id)
        db.add(ligne)
        await db.flush()
        await enregistrer_evenement(
            db, _enveloppe(organization_id, user_id, ligne), emetteur_tenant=organization_id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await db.refresh(ligne)
    return ligne


def _enveloppe(organization_id: uuid.UUID, user_id: uuid.UUID, ligne: SupportRequest) -> dict[str, Any]:
    """Enveloppe BE-150 de `SupportRequestCreated` ; forme identique à celle de la facturation."""
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": TYPE_EVENEMENT_DEMANDE_SUPPORT,
        "schemaVersion": VERSION_SCHEMA_DEMANDE_SUPPORT,
        "occurredAt": datetime.now(timezone.utc).isoformat(),
        "tenantId": str(organization_id),
        "scope": {"type": "organization", "id": str(organization_id)},
        "actor": {"userId": str(user_id)},
        "subject": {"type": "SupportRequest", "id": str(ligne.id)},
        "dataClassification": "internal",
        "correlationId": None,
        "causationId": None,
        "payload": {"supportRequestId": str(ligne.id), "statut": STATUT_OUVERT},
    }
