from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.health import base_repond

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    """Sonde de vivacité (liveness) : confirme que le processus répond.

    Ne contacte pas la base, donc un ralentissement de la base ne fait pas
    redémarrer l'instance. Public, sans session. Réponse : `{"status": "ok"}`.
    Pour savoir si l'instance peut recevoir du trafic, utiliser `/health/ready`.
    """
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness_check(response: Response, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Sonde de disponibilité (readiness) : la base répond-elle ?

    - HTTP 200 et `{"status": "ready"}` quand un `SELECT 1` aboutit ;
    - HTTP 503 et `{"status": "not ready"}` quand la base est injoignable.

    Public et sans session : un orchestrateur doit pouvoir l'interroger sans
    identifiant. Le corps ne contient ni message d'erreur, ni URL de base, ni
    donnée d'organisation (voir `app/core/health.py`). Seul GET est accepté.
    """
    if await base_repond(db):
        return {"status": "ready"}
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "not ready"}


@router.get("/health/error-demo")
def error_demo() -> None:
    """Endpoint de démonstration pour valider le format d'erreur unique (Phase 4) —
    à retirer une fois qu'un vrai module aura son propre test d'erreur."""
    raise AppError(code="demo_error", message="Erreur de démonstration.", status_code=418)
