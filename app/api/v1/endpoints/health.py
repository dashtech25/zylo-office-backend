from fastapi import APIRouter

from app.core.errors import AppError

router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/error-demo")
def error_demo() -> None:
    """Endpoint de démonstration pour valider le format d'erreur unique (Phase 4) —
    à retirer une fois qu'un vrai module aura son propre test d'erreur."""
    raise AppError(code="demo_error", message="Erreur de démonstration.", status_code=418)
