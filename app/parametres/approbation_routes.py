"""BE-159 : routes des demandes d'approbation de paramètres, sous `/api/v1/approbations`.

Routes :
- `GET /api/v1/approbations/{demande_id}` : lit une demande (statut, demandeur, approbateur,
  dates). Autorisé au demandeur et aux détenteurs de `settings.approve`. 404 hors tenant.
- `POST /api/v1/approbations/{demande_id}/decisions` : corps `decision` (`approuver` ou
  `rejeter`) et `motif` non vide. Permission `settings.approve`, approbateur distinct du
  demandeur. 200 avec la demande tranchée ; 403 sinon ; 409 VERSION_CONFLICT si déjà tranchée.

Le tenant vient de l'en-tête `X-Organization-Id` (contexte serveur). La logique métier est dans
`app.parametres.approbation` ; ce module ne fait que traduire la requête et la réponse.
La création de la demande n'a pas de route propre : elle a lieu lors d'un `PUT` sur un paramètre
sensible (`app.parametres.routes`, réponse 202).

Documentation de route : app/parametres/approbation.md.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import get_db
from app.core.tenant_context import TenantContext, get_tenant_context
from app.parametres.approbation import decider_demande, lire_demande
from app.parametres.models import ApprobationParametre

router = APIRouter()


class DecisionApprobation(BaseModel):
    """Corps d'une décision : `approuver` ou `rejeter`, avec un motif non vide (journalisé)."""

    decision: Literal["approuver", "rejeter"]
    motif: str = Field(min_length=1)


class DemandeApprobation(BaseModel):
    """Représentation d'une demande d'approbation (la valeur proposée n'est pas renvoyée)."""

    id: uuid.UUID
    cle: str
    portee: str
    scopeId: uuid.UUID
    statut: str
    demandeur: uuid.UUID
    approbateur: uuid.UUID | None
    motif: str
    createdAt: datetime
    decidedAt: datetime | None

    @classmethod
    def depuis(cls, demande: ApprobationParametre) -> "DemandeApprobation":
        """Construit la réponse depuis la ligne ; la valeur proposée reste en base."""
        return cls(
            id=demande.id,
            cle=demande.settingKey,
            portee=demande.scopeKind,
            scopeId=demande.scopeId,
            statut=demande.statut,
            demandeur=demande.demandeur,
            approbateur=demande.approbateur,
            motif=demande.motif,
            createdAt=demande.createdAt,
            decidedAt=demande.decidedAt,
        )


@router.get("/{demande_id}", response_model=DemandeApprobation)
async def lire_approbation(
    demande_id: uuid.UUID,
    contexte: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DemandeApprobation:
    """Lit une demande d'approbation du tenant courant (voir `lire_demande` pour les erreurs)."""
    identite = IdentiteEmettrice(user_id=contexte.user_id, organization_id=contexte.organization_id)
    demande = await lire_demande(db, identite, contexte.organization_id, demande_id)
    return DemandeApprobation.depuis(demande)


@router.post("/{demande_id}/decisions", response_model=DemandeApprobation)
async def decider_approbation(
    demande_id: uuid.UUID,
    corps: DecisionApprobation,
    contexte: TenantContext = Depends(get_tenant_context),
    db: AsyncSession = Depends(get_db),
) -> DemandeApprobation:
    """Approuve ou rejette une demande en attente. Le commit est fait ici.

    Erreurs : 404 hors tenant, 403 sans `settings.approve` ou pour une auto-approbation,
    409 VERSION_CONFLICT si la demande est déjà tranchée, 422 si la décision ou le motif est invalide.
    """
    identite = IdentiteEmettrice(user_id=contexte.user_id, organization_id=contexte.organization_id)
    demande = await decider_demande(
        db,
        identite,
        contexte.organization_id,
        demande_id=demande_id,
        decision=corps.decision,
        motif=corps.motif,
    )
    await db.commit()
    return DemandeApprobation.depuis(demande)
