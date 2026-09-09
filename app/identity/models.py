import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
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


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "user"
    __table_args__ = {"comment": "Utilisateur du système — identité unique, valable pour toutes les organisations et tous les modules."}

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
