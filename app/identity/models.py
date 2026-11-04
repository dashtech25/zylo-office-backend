import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "organization"
    __table_args__ = {"comment": "Organisation cliente de Zylo Office — tenant racine du système multi-organisation."}

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    # Verrou de version (BE-233, app/core/versioning.py) : +1 à chaque mutation.
    version: Mapped[int] = mapped_column(
        nullable=False, server_default="1", comment="Version de l'agrégat (BE-233) ; incrémentée à chaque mutation, verrou de conflit."
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "user"
    # Intention (T-013) : unicité de l'e-mail sans tenir compte de la casse.
    # L'e-mail est normalisé en minuscules à l'écriture ; cet index bloque aussi
    # les comptes anciens qui ne différeraient que par la casse.
    __table_args__ = (
        Index("uq_user_email_lower", text("lower(email)"), unique=True),
        {"comment": "Utilisateur du système — identité unique, valable pour toutes les organisations et tous les modules."},
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashedPassword: Mapped[str] = mapped_column(String(255), nullable=False)
    fullName: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")  # active | suspended | pending

    # Module Personnel (Centre administratif de la station) — colonnes
    # additives, toutes nullable : les comptes déjà auto-inscrits via
    # `POST /auth/register` n'ont que `fullName`, jamais rétro-déduites.
    firstName: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lastName: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Référence opaque vers le service de stockage générique
    # (app/shared/storage.py) — jamais un fichier stocké par ce module.
    photoStorageReference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Vrai après une création de compte par un tiers (mot de passe temporaire
    # généré côté serveur, jamais choisi par la personne) — force un
    # changement via POST /auth/change-password avant utilisation normale.
    mustChangePassword: Mapped[bool] = mapped_column(nullable=False, server_default="false")


class OrganizationUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizationUser"
    __table_args__ = (
        UniqueConstraint("organizationId", "userId", name="uq_organizationUser_org_user"),
        {"comment": "Association utilisateur <-> organisation (appartenance, many-to-many)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)


class UserInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jeton d'activation d'un compte créé par une organisation (T-021, T-049).

    Intention : seule l'empreinte SHA-256 du jeton est stockée (le jeton n'existe
    qu'en clair dans le message envoyé au titulaire). Usage unique (`usedAt`),
    durée limitée (`expiresAt`), révocable (`revokedAt`, réémission). Un seul
    jeton ouvert par compte : garanti par l'index partiel ci-dessous.
    """

    __tablename__ = "userInvitation"
    __table_args__ = (
        Index(
            "uq_userInvitation_open_per_user",
            "userId",
            unique=True,
            postgresql_where="\"usedAt\" IS NULL AND \"revokedAt\" IS NULL",
        ),
        {"comment": "Jeton d'activation à usage unique d'un compte créé par une organisation (haché, à durée limitée)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    createdByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    tokenHash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
