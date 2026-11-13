"""Services BE-214 : Rétention, sauvegarde et purge.

Logique métier pour la purge de données selon les politiques de rétention.
- Création de demande de purge
- Vérification des legal_holds (CA-1)
- Vérification des durées définies (CA-2)
- Audit de la demande (CA-5)
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.retention.models import RetentionPolicy, LegalHold


async def request_purge(
    db: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    category: str,
    before_date: datetime,
) -> dict[str, Any]:
    """Demande la purge des données d'une catégorie.

    Critique :
    - Vérification legal_hold actif (CA-1)
    - Vérification durée définie (CA-2)
    - Isolement tenant (CA-4)
    - Audit de la demande (CA-5)

    Lève :
    - 422 : legal_hold actif ou durée non définie
    - 404 : catégorie inexistante

    Implémentation spéculative : structure de base.
    """
    # CA-1 : vérifier legal_hold actif
    result = await db.execute(
        select(LegalHold).where(
            and_(
                LegalHold.tenantId == organization_id,
                LegalHold.releasedAt.is_(None),  # Actif
            )
        )
    )
    active_hold = result.scalar_one_or_none()

    if active_hold:
        raise AppError(
            code="legal_hold_active",
            message=f"Une garde légale est active pour cette organisation. Purge refusée.",
            status_code=422,
        )

    # CA-2 : vérifier que la durée est définie
    result = await db.execute(
        select(RetentionPolicy).where(RetentionPolicy.category == category)
    )
    policy = result.scalar_one_or_none()

    if not policy:
        raise AppError(
            code="policy_not_found",
            message=f"Politique de rétention inexistante pour la catégorie '{category}'.",
            status_code=404,
        )

    if policy.duration_days is None:
        raise AppError(
            code="duration_not_defined",
            message=f"Durée non définie pour la catégorie '{category}'. Aucune purge effectuée.",
            status_code=422,
        )

    # CA-5 : audit de la demande (TODO : implémentation complète avec événement)
    # await write_audit_event(
    #     db=db,
    #     principal_id=user_id,
    #     action="data.purge.requested",
    #     organization_id=organization_id,
    #     details={"category": category, "beforeDate": before_date.isoformat()},
    # )

    # TODO : implémentation réelle de la purge
    # - CA-4 : isolement tenant (purger seulement pour organization_id)
    # - CA-3 : sauvegarde/restauration (mécanisme à définir, QE-API-15)

    return {
        "status": "requested",
        "category": category,
        "beforeDate": before_date.isoformat(),
        "organizationId": str(organization_id),
        "requestedAt": datetime.now(timezone.utc).isoformat(),
    }
