"""Route de préparation d'opérations financières (BE-136), montée sous `/api/v1/admin`.

- `POST /api/v1/admin/invoices/{invoice_id}/finance-commands` : prépare une intention
  financière sur la facture (201 ; 200 au rejeu identique de la clé).

Codes : 403 `admin_scope_denied` si le compte n'a pas l'autorité finance sur le tenant
de la facture (et un cas d'escalade finance est ouvert) ; 404 `invoice_not_found` ;
409 `idempotency_conflict` ; 422 si le corps contient un champ inconnu, en particulier
un numéro de carte ou un CVV (le schéma interdit les champs hors contrat).

Aucune route d'exécution : l'effet financier et l'appel PSP sont hors périmètre (PH-10).
"""

import uuid

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.commands import AdminCommand
from app.operator.commands_router import CommandeResponse
from app.operator.finance_commands import preparer_operation_financiere

router = APIRouter()


class PreparationFinanciereCreate(BaseModel):
    """Corps de préparation. `extra="forbid"` : tout champ hors contrat est refusé en 422.

    Un numéro de carte ou un CVV n'a donc pas de champ où être accepté, et ne peut
    ni être stocké ni être journalisé (CA-2 de BE-136).
    """

    model_config = ConfigDict(extra="forbid")

    reasonTicket: str = Field(min_length=1, max_length=120)
    idempotencyKey: str = Field(min_length=8, max_length=120)


@router.post(
    "/invoices/{invoice_id}/finance-commands",
    response_model=CommandeResponse,
    status_code=201,
    summary="Préparer une opération financière sans exécution PSP (BE-136)",
)
async def preparer_commande_financiere(
    invoice_id: uuid.UUID,
    data: PreparationFinanciereCreate,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> AdminCommand:
    """Crée l'intention financière de la facture, sans aucun appel au prestataire de paiement."""
    commande, cree = await preparer_operation_financiere(
        db,
        actor_id=current_user.id,
        invoice_id=invoice_id,
        corps=data.model_dump(),
        correlation_id=request_id_ctx.get(),
    )
    if not cree:
        response.status_code = 200
    return commande
