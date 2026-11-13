"""Compteurs d'exploitation de la console opérateur (BE-145).

Route unique : `GET /api/v1/admin/ops/metrics`, réservée à l'opérateur habilité
(`require_operator`, allowlist `OPERATOR_READ_USER_IDS`, fail-closed). Un compte
hors liste reçoit 403 `operator_access_denied`, même avec le filtre `tenantId`.

Réponse :
- `filtre.tenantId` : organisation demandée, ou `null` pour la portée plateforme ;
- `compteurs` : un entier par compteur, ou `null` si le compteur n'est pas mesurable ;
- `indisponibles` : noms des compteurs valant `null`, triés. Un compteur non mesurable
  n'est jamais présenté comme 0 ;
- `mesureAt` : instant UTC de la mesure.

Sources des compteurs mesurables :
- `commandes` : lignes de `admin_command` (BE-124), filtrables par `tenantId` ;
- `refus_autorisation`, `erreurs`, `resultats_inconnus` : lignes de `audit_event` dont
  `result` vaut `refused`, `error` ou `unknown`, filtrables par `organizationId` ;
- `echec_ou_doublon_webhook` : évènements de `paymentWebhookEvent` en quarantaine
  (BE-029). Ces lignes ne portent pas de tenant : avec `tenantId`, ce compteur est `null`.

Compteurs non mesurables à ce jour, faute de source définie (QE à trancher) :
`previews_expirees`, `duree_propagation`, `integration_degradee`,
`notification_non_delivree`.

Règles de contenu :
- aucune valeur de charge utile, de secret, de jeton ou de message libre ne sort de ce
  module : seuls des noms fixes, des entiers, des `null` et des dates ;
- aucun seuil ni alerte n'est codé ici. Les seuils restent NON DÉFINIS (PH-16) et
  relèvent du registre d'alertes (BE-241), pas de ce module.

Piège évité : un compteur non mesurable est renvoyé à `null` et non à 0, sinon un
tableau de bord afficherait une absence de problème là où la mesure n'existe pas.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent
from app.billing.models import PaymentWebhookEvent
from app.core.database import get_db
from app.operator.commands import AdminCommand
from app.operator.permissions import require_operator

# Compteurs mesurables : nom de la réponse -> valeur de `audit_event.result`, sauf les
# deux cas à part (commandes et webhooks) traités dans `_mesurer`.
COMPTEURS_AUDIT = {
    "refus_autorisation": "refused",
    "erreurs": "error",
    "resultats_inconnus": "unknown",
}
COMPTEURS_NON_MESURABLES = (
    "previews_expirees",
    "duree_propagation",
    "integration_degradee",
    "notification_non_delivree",
)

router = APIRouter(dependencies=[Depends(require_operator)])


class OpsMetricsFiltre(BaseModel):
    tenantId: uuid.UUID | None


class OpsMetricsResponse(BaseModel):
    """Projection des compteurs : seuls ces champs sortent de la route."""

    filtre: OpsMetricsFiltre
    compteurs: dict[str, int | None]
    indisponibles: list[str]
    mesureAt: datetime


async def _mesurer(db: AsyncSession, tenant_id: uuid.UUID | None) -> dict[str, int | None]:
    """Calcule chaque compteur mesurable, filtré par tenant quand il est demandé."""
    compteurs: dict[str, int | None] = {}

    stmt_commandes = select(func.count()).select_from(AdminCommand)
    if tenant_id is not None:
        stmt_commandes = stmt_commandes.where(AdminCommand.tenantId == tenant_id)
    compteurs["commandes"] = int(await db.scalar(stmt_commandes) or 0)

    for nom, resultat in COMPTEURS_AUDIT.items():
        stmt = select(func.count()).select_from(AuditEvent).where(AuditEvent.result == resultat)
        if tenant_id is not None:
            stmt = stmt.where(AuditEvent.organizationId == tenant_id)
        compteurs[nom] = int(await db.scalar(stmt) or 0)

    if tenant_id is None:
        stmt_webhook = select(func.count()).select_from(PaymentWebhookEvent).where(
            PaymentWebhookEvent.quarantinedAt.is_not(None),
        )
        compteurs["echec_ou_doublon_webhook"] = int(await db.scalar(stmt_webhook) or 0)
    else:
        compteurs["echec_ou_doublon_webhook"] = None

    for nom in COMPTEURS_NON_MESURABLES:
        compteurs[nom] = None
    return compteurs


@router.get("/ops/metrics", response_model=OpsMetricsResponse)
async def lire_compteurs_exploitation(
    tenantId: uuid.UUID | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> OpsMetricsResponse:
    """Lecture des compteurs d'exploitation (BE-145), portée plateforme ou par tenant.

    Sans `tenantId`, les compteurs couvrent toute la plateforme. Avec `tenantId`, les
    compteurs filtrables sont restreints à cette organisation ; le compteur de webhooks,
    qui n'a pas de tenant, passe à `null` et figure dans `indisponibles`.
    """
    compteurs = await _mesurer(db, tenantId)
    indisponibles = sorted(nom for nom, valeur in compteurs.items() if valeur is None)
    return OpsMetricsResponse(
        filtre=OpsMetricsFiltre(tenantId=tenantId),
        compteurs=compteurs,
        indisponibles=indisponibles,
        mesureAt=datetime.now(timezone.utc),
    )
