import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refreshToken"
    __table_args__ = {"comment": "Refresh token JWT émis à un utilisateur — révocable individuellement, avec rotation à chaque renouvellement."}

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    tokenHash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
