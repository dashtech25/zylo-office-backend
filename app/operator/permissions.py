import os
import uuid

from fastapi import Depends

from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User


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


async def require_operator(current_user: User = Depends(get_current_user)) -> User:
    if current_user.id not in _operator_user_ids():
        raise AppError(
            code="operator_access_denied",
            message="Cette interface de support n'est pas disponible pour ce compte.",
            status_code=403,
        )
    return current_user
