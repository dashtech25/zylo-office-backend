"""Routes de la file de lettres mortes (BE-235), montées sous `/api/v1/internal`.

Routes :
- `GET /api/v1/internal/dead-letters` : entrées DLQ du tenant de la portée ;
- `POST /api/v1/internal/dead-letters/{id}/replay` : rejoue une entrée vers son consommateur.

Garde : `require_admin_scope` (BE-120). Sans autorité plateforme : 403 (CA-3). La portée doit
désigner un tenant (`X-Admin-Scope: tenant:<uuid>`) : la portée plateforme ne donne pas accès au
contenu d'un tenant (BE-120, CA-2), donc 403 à la lecture et 404 au replay. Une entrée d'un autre
tenant que celui de la portée répond 404 (CA-4), sans rien révéler de son existence.

Les réponses n'exposent ni payload ni message d'erreur : seulement les identifiants, le
consommateur, le motif court et les compteurs.
"""

import uuid

from fastapi import APIRouter, Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.evenements.dlq import lister_dead_letters, rejouer_dead_letter
from app.evenements.models import DeadLetter
from app.operator.scope import AdminScope, require_admin_scope

router = APIRouter(prefix="/dead-letters", tags=["evenements-dlq"])


def _tenant_de_portee(scope: AdminScope) -> uuid.UUID:
    """Tenant de la portée ; refuse (403) la portée plateforme, qui ne lit jamais de contenu tenant."""
    if scope.is_platform or scope.organization_id is None:
        raise AppError(code="admin_scope_denied", message="Accès d'administration refusé pour cette portée.", status_code=403)
    return scope.organization_id


def _vue(ligne: DeadLetter) -> dict:
    """Représentation publique d'une entrée DLQ, sans payload ni message d'erreur."""
    return {
        "id": str(ligne.id),
        "eventId": str(ligne.eventId),
        "consommateur": ligne.consommateur,
        "motif": ligne.motif,
        "tentatives": ligne.tentatives,
        "tenantId": str(ligne.tenantId),
        "statut": ligne.statut,
    }


@router.get("")
async def lister(scope: AdminScope = Depends(require_admin_scope), db: AsyncSession = Depends(get_db)) -> dict:
    """Liste les lettres mortes du tenant de la portée (CA-4 : jamais celles d'un autre tenant)."""
    lignes = await lister_dead_letters(db, _tenant_de_portee(scope))
    return {"items": [_vue(ligne) for ligne in lignes]}


@router.post("/{dead_letter_id}/replay")
async def rejouer(
    dead_letter_id: uuid.UUID = Path(...),
    scope: AdminScope = Depends(require_admin_scope),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rejoue une entrée DLQ de la portée. Hors portée : 404. Déjà rejouée : 409."""
    tenant = None if scope.is_platform else scope.organization_id
    ligne = await rejouer_dead_letter(db, dead_letter_id, tenant)
    await db.commit()
    return _vue(ligne)
