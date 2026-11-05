"""Route de service des événements de liaison facturation vers entitlements (BE-058).

POST /api/v1/internal/billing/entitlement-events. Montée sous `/api/v1/internal` (voir
app/api/v1/router.py) : réservée au réseau de service, jamais exposée à un utilisateur.

Droits : identité de service uniquement (QE-MOD-18, hypothèse appliquée). L'appelant
envoie l'en-tête `X-Service-Token` ; il doit égaler `BILLING_SERVICE_TOKEN`. Si la variable
est vide, aucun appelant n'est accepté (échec fermé). Un jeton utilisateur (`Authorization`)
ne vaut jamais identité de service : sans jeton de service, 403 et aucune écriture.
La comparaison passe par `hmac.compare_digest` pour éviter une fuite par temps de réponse.
"""

import hmac
import os
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.entitlement_events import (
    EvenementEntitlement,
    ResultatEvenementEntitlement,
    traiter_evenement_entitlement,
)
from app.core.database import get_db
from app.core.errors import AppError

router = APIRouter()


def verifier_identite_service(jeton_recu: str | None) -> None:
    """Lève 403 `service_identity_required` si le jeton est absent, vide ou erroné.

    Échec fermé : une variable `BILLING_SERVICE_TOKEN` vide désactive la route pour tous.
    """
    attendu = os.getenv("BILLING_SERVICE_TOKEN", "")
    if not attendu or not jeton_recu or not hmac.compare_digest(jeton_recu.encode(), attendu.encode()):
        raise AppError(
            code="service_identity_required",
            message="Identité de service requise pour cet évènement.",
            status_code=403,
        )


@router.post(
    "/billing/entitlement-events",
    response_model=ResultatEvenementEntitlement,
    summary="Recevoir un évènement de facturation qui modifie les entitlements (BE-058)",
)
async def recevoir_evenement_entitlement(
    evenement: Annotated[EvenementEntitlement, Body()],
    x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
    db: AsyncSession = Depends(get_db),
) -> ResultatEvenementEntitlement:
    """Vérifie l'identité de service, puis délègue à `traiter_evenement_entitlement`.

    Réponses : 200 (`applied`, `reconciliation_required`, `aucun_entitlement` ou doublon),
    403 sans identité de service, 404 si l'organisation ou l'abonnement est inconnu (journalisé),
    422 si le corps est invalide (source ou niveau hors liste, par exemple).
    """
    verifier_identite_service(x_service_token)
    return await traiter_evenement_entitlement(db, evenement)
