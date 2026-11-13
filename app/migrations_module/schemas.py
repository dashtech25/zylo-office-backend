"""Schémas Pydantic pour les migrations (BE-198)."""

from pydantic import BaseModel
import uuid


class MigrationRunRequest(BaseModel):
    """Requête pour un run/dry-run/resume/rollback."""
    tenantId: str  # UUID du tenant


class MigrationRunResponse(BaseModel):
    """Réponse d'un run/dry-run/resume/rollback."""
    state: str  # pending, running, completed, failed, paused, dry_run_success, etc.
    checkpoint: int  # Dernier élément complété
