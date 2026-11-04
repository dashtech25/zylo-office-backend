import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.operator.audit_models import OperatorAuditLog


async def record_operator_read(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    scope: str,
    action: str,
    target_type: str,
    outcome: str,
    request_id: str,
    target_id: uuid.UUID | None = None,
) -> None:
    """Persist only operator identity, scope, action, outcome and correlation ID."""
    db.add(OperatorAuditLog(
        actorUserId=actor_user_id,
        scope=scope,
        action=action,
        targetType=target_type,
        targetId=target_id,
        outcome=outcome,
        requestId=request_id,
    ))
    await db.commit()
