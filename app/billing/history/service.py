"""Lecture de l'historique commercial d'un tenant (BE-099).

Route : `GET /api/v1/billing/history` (app/billing/history/router.py).

Contrat, dans cet ordre :
1. Permission : le demandeur doit détenir `billing.history.read` sur le tenant courant.
   Sinon `FORBIDDEN` (403) ; aucune donnée n'est lue.
2. Périmètre : seules les entrées de `audit_event` dont `organizationId` est le tenant courant
   et dont l'action commence par `billing.` sont lues. Le tenant vient uniquement de la garde
   d'appartenance (en-tête `X-Organization-Id`) : aucun paramètre client ne le redéfinit, donc
   un filtre forgé ne sort jamais du tenant (CA-3).
3. Filtre optionnel `scope` (`payeur`, `tenant`, `beneficiaire`) : filtre additif sur
   `scopeResourceType`, jamais un contournement du périmètre ci-dessus.
4. Tri : les entrées les plus récentes d'abord ; pagination `limit`/`offset` (CA-1).

Les entrées sont lues telles qu'écrites par BE-073 ; elles ne contiennent aucun secret de
paiement (le journal masque les clés sensibles). La réponse, elle, n'expose que des colonnes de
résumé (voir `app/billing/history/router.py`), sans le détail `changes` (CA-4).
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.billing.errors import BillingErrorCode, billing_error
from app.billing.permissions import BILLING_HISTORY_READ
from app.rbac.service import user_has_permission

PREFIXE_HISTORIQUE = "billing."


async def lister_historique(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    demandeur_id: uuid.UUID,
    scope: str | None,
    limit: int,
    offset: int,
) -> tuple[list[AuditEvent], int]:
    """Entrées d'historique du tenant (page) et leur nombre total.

    Erreur : `FORBIDDEN` (403) si le demandeur n'a pas `billing.history.read` sur le tenant.
    Le total est calculé sur la même requête filtrée que la page, pour que la pagination
    reste cohérente avec le périmètre.
    """
    if not await user_has_permission(db, demandeur_id, tenant_id, BILLING_HISTORY_READ):
        raise billing_error(BillingErrorCode.FORBIDDEN)

    stmt = select(AuditEvent).where(
        AuditEvent.organizationId == tenant_id,
        AuditEvent.action.like(f"{PREFIXE_HISTORIQUE}%"),
    )
    if scope is not None:
        stmt = stmt.where(AuditEvent.scopeResourceType == scope)

    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    lignes = await db.scalars(
        stmt.order_by(AuditEvent.createdAt.desc(), AuditEvent.id.desc()).limit(limit).offset(offset)
    )
    return list(lignes.all()), total
