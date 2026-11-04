import os
import uuid

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.audit import record_operator_read


def _operator_user_ids() -> set[uuid.UUID]:
    """Explicit process-level operator allowlist. Empty/unparseable values deny."""
    result: set[uuid.UUID] = set()
    for raw in os.getenv("OPERATOR_READ_USER_IDS", "").split(","):
        try:
            if raw.strip():
                result.add(uuid.UUID(raw.strip()))
        except ValueError:
            # A malformed configured value never broadens access.
            continue
    return result


def has_platform_authority(user_id: uuid.UUID) -> bool:
    """Vrai si `user_id` détient l'autorité plateforme (portée `platform`, BE-120).

    Même source et même refus fermé que `require_operator` : une seule liste.
    Utilisé par `app/operator/scope.py` ; ne lève rien, le refus est décidé par
    l'appelant."""
    return user_id in _operator_user_ids()


def assert_operator_user(user_id: uuid.UUID) -> None:
    """Lève 403 si `user_id` ne figure pas dans l'allowlist d'exploitation.

    Point d'entrée sans dépendance FastAPI, réutilisé par les services hors routes
    (ex. le registre des secrets, BE-230) : une seule liste, une seule règle de refus."""
    if user_id not in _operator_user_ids():
        raise AppError(
            code="operator_access_denied",
            message="Cette interface de support n'est pas disponible pour ce compte.",
            status_code=403,
        )


async def require_operator(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Garde des routes opérateur (BE-030 CA-3).

    Un compte hors de l'allowlist est refusé (403), et cette tentative est
    journalisée dans `audit_event` avec `result = refused` avant la réponse.
    La session est partagée avec la route (cache de dépendances FastAPI).
    """
    if current_user.id in _operator_user_ids():
        return current_user
    await record_operator_read(
        db,
        actor_user_id=current_user.id,
        scope="platform",
        action="console.access",
        target_type="operator_console",
        outcome="refused",
        request_id=request_id_ctx.get() or "sans-requete",
    )
    assert_operator_user(current_user.id)
    return current_user
