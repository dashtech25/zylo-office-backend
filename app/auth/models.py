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


class LoginAttempt(UUIDPrimaryKeyMixin, Base):
    """Tentative d'authentification enregistrée pour la limitation de débit (T-012).

    Intention : une ligne par échec (outcome='failure'), plus une ligne par couple
    (IP, compte) connu après un succès (outcome='success', sert à reconnaître une
    IP déjà utilisée par le titulaire). `keyHash` est une empreinte SHA-256 de
    (action, portée, IP, email) : aucun email ni mot de passe n'est stocké en clair.
    Les échecs anciens sont purgés par app/auth/ratelimit.py.
    """

    __tablename__ = "loginAttempt"
    __table_args__ = {"comment": "Échecs d'authentification et couples (IP, compte) connus — limitation de débit T-012. Empreintes uniquement."}

    action: Mapped[str] = mapped_column(String(16), nullable=False, comment="login, register ou refresh")
    scope: Mapped[str] = mapped_column(String(8), nullable=False, comment="couple (IP, compte) ou ip")
    keyHash: Mapped[str] = mapped_column(String(64), nullable=False, index=True, comment="Empreinte SHA-256 de la clé de limitation")
    outcome: Mapped[str] = mapped_column(String(8), nullable=False, comment="failure ou success")
    occurredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Horodatage applicatif de la tentative")
