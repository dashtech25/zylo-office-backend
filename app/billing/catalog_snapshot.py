"""Capture et lecture de la version d'offre figée au devis et au contrat (BE-075).

Un devis ou un contrat doit garder le prix et les droits de l'offre telle qu'elle
était publiée au moment de la signature. Ce module produit cet instantané dans la
table `plan_version_snapshot` (app/billing/models.py::PlanVersionSnapshot) et
refuse de le relire sans droit ou hors de son tenant.

Règles :

- `capturer_version_offre` prend la dernière version du plan (numéro le plus élevé).
  Une version `withdrawn` ne peut plus être capturée pour un nouveau devis :
  `INVALID_TRANSITION` (409). Le retrait n'affecte pas les abonnements existants,
  qui gardent leur `planVersionId` (QE-FAC-10).
- Le contenu capturé est une copie sérialisable (dictionnaire) ; aucune référence
  vivante vers le catalogue n'est conservée. Une publication ultérieure ne le modifie pas.
- `lire_snapshot` vérifie d'abord le tenant : un instantané d'un autre tenant est
  `snapshot_not_found` (404), sans fuite d'existence. Puis la permission
  `billing.catalogue.read` (lecture interne) est exigée : sinon `FORBIDDEN` (403).
- Aucune route HTTP dans ce module : les routes des devis (BE-077) l'appelleront.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service as facturation
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.models import Plan, PlanVersion, PlanVersionSnapshot
from app.billing.permissions import BILLING_CATALOGUE_READ
from app.core.errors import AppError
from app.rbac.service import user_has_permission_any_scope


async def capturer_version_offre(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    plan_code: str,
    actor_user_id: uuid.UUID,
) -> PlanVersionSnapshot:
    """Fige la dernière version publiée du plan `plan_code` pour `organization_id`.

    Erreurs : `plan_not_found` (404) si le plan n'existe pas ; `INVALID_TRANSITION`
    (409) si la version courante est `withdrawn`. Commit à la fin.
    `actor_user_id` est l'auteur de la capture (non tracé dans la ligne ; réservé à l'audit de BE-077).
    """
    plan = await db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        raise AppError(code="plan_not_found", message=f"Plan inconnu : {plan_code}.", status_code=404)
    version = await db.scalar(
        select(PlanVersion).where(PlanVersion.planId == plan.id).order_by(PlanVersion.version.desc()).limit(1)
    )
    if version is None:
        version = await facturation.ensure_initial_plan_version(db, plan)
    if version.status == "withdrawn":
        raise billing_error(BillingErrorCode.INVALID_TRANSITION)

    snapshot = PlanVersionSnapshot(
        organizationId=organization_id,
        planRef=plan.code,
        planVersion=version.version,
        capturedAt=datetime.now(timezone.utc),
        sourceCatalogueRef=str(version.id),
        snapshotJson={
            "plan": {"code": plan.code, "name": plan.name, "moduleCode": plan.moduleCode},
            "version": {
                "version": version.version,
                "amountMinor": version.amountMinor,
                "currency": version.currency,
                "periodDays": version.periodDays,
                "entitlementCodes": list(version.entitlementCodes or []),
                "effectiveAt": version.effectiveAt.isoformat(),
            },
        },
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def lire_snapshot(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> PlanVersionSnapshot:
    """Renvoie l'instantané `snapshot_id`, si et seulement si il appartient à `organization_id`.

    Ordre des contrôles : tenant d'abord (404 `snapshot_not_found`), permission
    ensuite (403 `FORBIDDEN`). Ainsi un acteur d'un autre tenant ne reçoit jamais
    l'information qu'un instantané existe.
    """
    snapshot = await db.scalar(select(PlanVersionSnapshot).where(
        PlanVersionSnapshot.id == snapshot_id,
        PlanVersionSnapshot.organizationId == organization_id,
    ))
    if snapshot is None:
        raise AppError(code="snapshot_not_found", message="Instantané introuvable.", status_code=404)
    if not await user_has_permission_any_scope(db, actor_user_id, organization_id, BILLING_CATALOGUE_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)
    return snapshot
