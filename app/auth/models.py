import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refreshToken"
    __table_args__ = {"comment": "Refresh token JWT émis à un utilisateur — révocable individuellement, avec rotation à chaque renouvellement."}

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    tokenHash: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    # Famille de rotation (T-020) : tous les refresh tokens issus d'une même
    # connexion partagent cet identifiant. Présenter un jeton déjà révoqué révoque
    # toute la famille (détection de réutilisation). Un nouveau login crée une famille.
    familyId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True, comment="Famille de rotation : révoquée entière en cas de réutilisation."
    )
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


class PasswordResetToken(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jeton de récupération de compte à usage unique, empreinte SHA-256 uniquement.

    Table `password_reset_token` (snake_case, décision BE-037 ; renommée par la
    révision c9f2a4e6b8d1). Seul le nom de table a changé : colonnes, index et
    contraintes gardent les noms camelCase de la migration d'origine
    (e3c4a8f1b2d6), déclarés explicitement ici pour que la comparaison ORM/base
    d'Alembic ne voie aucune différence.

    Invariants : `tokenHash` est unique ; au plus un jeton ouvert par utilisateur
    (index partiel unique sur `userId` où `usedAt` et `revokedAt` sont NULL).
    Le service d'authentification (`app/auth/password_reset.py`) révoque les
    jetons ouverts avant d'en émettre un nouveau.
    """

    __tablename__ = "password_reset_token"
    __table_args__ = (
        Index("ix_passwordResetToken_userId", "userId"),
        Index(
            "uq_passwordResetToken_open_per_user",
            "userId",
            unique=True,
            postgresql_where='"usedAt" IS NULL AND "revokedAt" IS NULL',
        ),
        {"comment": "Jeton de récupération de compte, haché, à usage unique et expiration courte."},
    )

    userId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    tokenHash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
