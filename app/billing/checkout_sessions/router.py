"""Routes des sessions de paiement du portail (BE-110), montées sous `/api/v1/organizations`.

- `POST /organizations/{organization_id}/checkout-sessions` : crée une session (201). En-tête
  `Idempotency-Key` obligatoire (422 si absent) ; corps : `planCode`, `scenario`, `payerId`,
  `consentTextVersion`. Un rejeu avec la même clé renvoie la même session.
- `GET /organizations/{organization_id}/checkout-sessions/{session}` : lit l'état durable (200).

Ordre de contrôle d'une requête : portée et permission (`exiger_action`, 401/403/404) ; en-tête
d'idempotence (422) ; consentement versionné absent ou vide (400 `consent_required`, rien n'est
écrit) ; écriture ou lecture (`service.py`). La query string n'est jamais lue.
"""

import uuid

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.checkout_sessions.service import creer_session_paiement, lire_session_paiement, offre_figee
from app.billing.models import Checkout
from app.core.database import get_db
from app.core.errors import AppError
from app.core.idempotency import require_idempotency_key
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

# Actions du portail : permissions dans POLITIQUE_PORTAIL (app/rbac/portee_organisation.py, BE-110).
SESSION_CREER_ACTION = "portail.session_paiement.creer"
SESSION_LIRE_ACTION = "portail.session_paiement.lire"


class CreerSessionRequete(BaseModel):
    """Corps de la création. `consentTextVersion` est optionnel au schéma pour que son absence
    produise 400 `consent_required` (et non 422) ; la route le vérifie avant toute écriture."""

    planCode: str = Field(min_length=1, max_length=100)
    scenario: str = Field(min_length=1, max_length=100)
    payerId: uuid.UUID
    consentTextVersion: str | None = Field(default=None, max_length=64)


class SessionPaiementReponse(BaseModel):
    """État d'une session : identifiant, devis, état durable, version, date et offre figée."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    quoteId: uuid.UUID
    status: str
    version: int
    createdAt: str
    offre: dict


async def _reponse(db: AsyncSession, session: Checkout) -> SessionPaiementReponse:
    return SessionPaiementReponse(
        id=session.id,
        quoteId=session.quoteId,
        status=session.status,
        version=session.version,
        createdAt=session.createdAt.isoformat(),
        offre=await offre_figee(db, session),
    )


@router.post(
    "/{organization_id}/checkout-sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=SessionPaiementReponse,
    summary="Créer une session de paiement (BE-110)",
)
async def creer(
    corps: CreerSessionRequete,
    cle: str = Depends(require_idempotency_key),
    scope: OrgScope = Depends(exiger_action(SESSION_CREER_ACTION)),
    db: AsyncSession = Depends(get_db),
) -> SessionPaiementReponse:
    """Crée une session `open` pour l'organisation du chemin. 400 `consent_required` si la version
    du consentement est absente ou vide : rien n'est lu ni écrit. 409 `DUPLICATE` si la clé
    est réutilisée avec une autre charge."""
    version = (corps.consentTextVersion or "").strip()
    if not version:
        raise AppError(
            code="consent_required",
            message="Un consentement versionné est requis pour démarrer le paiement.",
            status_code=400,
        )
    session = await creer_session_paiement(
        db,
        organization_id=scope.organization_id,
        actor_user_id=scope.user_id,
        idempotency_key=cle,
        plan_code=corps.planCode,
        scenario=corps.scenario,
        payer_id=corps.payerId,
        consent_text_version=version,
    )
    return await _reponse(db, session)


@router.get(
    "/{organization_id}/checkout-sessions/{session}",
    response_model=SessionPaiementReponse,
    summary="Lire l'état d'une session de paiement (BE-110)",
)
async def lire(
    session: uuid.UUID,
    scope: OrgScope = Depends(exiger_action(SESSION_LIRE_ACTION)),
    db: AsyncSession = Depends(get_db),
) -> SessionPaiementReponse:
    """Renvoie l'état durable de la session. 404 `checkout_session_not_found` si elle appartient
    à une autre organisation ou n'existe pas (réponse identique)."""
    trouvee = await lire_session_paiement(db, organization_id=scope.organization_id, checkout_id=session)
    return await _reponse(db, trouvee)
