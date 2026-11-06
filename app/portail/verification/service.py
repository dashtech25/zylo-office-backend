"""Dépôt et lecture du cas de vérification d'une organisation (BE-103).

Le service ne fixe que le statut initial `verification_pending` : le client ne choisit jamais le
statut (CA-4). Aucune fonction ici ne passe un cas à `verified` ou `rejected`. Politique de
décision NON DÉFINIE (QE-POR-07) : une seconde demande n'est ni refusée ni fusionnée.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.portail.verification.models import VerificationCase

STATUT_EN_ATTENTE = "verification_pending"


async def deposer_demande(db: AsyncSession, organization_id: uuid.UUID) -> VerificationCase:
    """Crée un cas `verification_pending` pour l'organisation et le commit."""
    ligne = VerificationCase(organizationId=organization_id, statut=STATUT_EN_ATTENTE)
    db.add(ligne)
    await db.commit()
    await db.refresh(ligne)
    return ligne


async def dernier_cas(db: AsyncSession, organization_id: uuid.UUID) -> VerificationCase | None:
    """Cas le plus récent de l'organisation, ou None s'il n'en a pas encore déposé."""
    return (
        await db.execute(
            select(VerificationCase)
            .where(VerificationCase.organizationId == organization_id)
            .order_by(VerificationCase.createdAt.desc())
            .limit(1)
        )
    ).scalars().first()
