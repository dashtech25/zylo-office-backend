import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

# Valeurs des enums du catalogue (BE-040, matrice-etats-modules-et-droits.md section 1).
# Publication et visibilité sont des axes orthogonaux : aucun des deux n'ouvre l'accès à lui seul.
# L'accès reste décidé par `etats.py` (registre) et par l'activation de l'organisation.
ETATS_PUBLICATION_MODULE: tuple[str, ...] = (
    "draft",
    "review",
    "published",
    "deprecated",
    "withdrawn",
    "quarantined",
)
VISIBILITES_MODULE: tuple[str, ...] = ("hidden", "visible", "restricted")


class Module(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Module du catalogue Zylo Office (table `module`, réutilisée par BE-040).

    La table existait depuis BE-021 comme registre statique. BE-040 y ajoute le cycle de
    publication (`publicationState`) et la visibilité (`visibility`). `code` joue le rôle de
    `slug` du catalogue : unique, il sert de clé stable. `version` est l'ancien champ texte de
    BE-021, conservé ; la liste des versions est dans `module_version`.
    """

    __tablename__ = "module"
    __table_args__ = {"comment": "Catalogue des modules (registre, cycle de publication, visibilité)."}

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.1.0")
    # Version du contrat de manifeste (format non défini, QE-SOC-19). Hors de
    # VERSIONS_MANIFESTE_SUPPORTEES, le module passe à l'état `incompatible` (etats.py).
    manifestVersion: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="Version du contrat de manifeste du module."
    )
    publicationState: Mapped[str] = mapped_column(
        Enum(*ETATS_PUBLICATION_MODULE, name="module_publication_state", native_enum=True),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="Cycle de publication du module au catalogue (draft, review, published, ...).",
    )
    visibility: Mapped[str] = mapped_column(
        Enum(*VISIBILITES_MODULE, name="module_visibility", native_enum=True),
        nullable=False,
        default="hidden",
        server_default="hidden",
        comment="Visibilité du module dans le catalogue (hidden, visible, restricted).",
    )


class ModuleVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une version d'un module du catalogue (table `module_version`, BE-040).

    Une version est immuable dès qu'elle est publiée (`publishedAt` renseigné) : son contenu
    (`digest`, `provenance`, `licence`, `compatibility`, `prerequisites`) ne se modifie plus.
    La règle est appliquée par `catalogue.modifier_version`. Une version sans `digest` ni
    `provenance` ne peut pas être publiée (`catalogue.verifier_publiable`).
    `stateVersion` est le compteur de révision de la version, réservé à la machine d'états de BE-041.
    """

    __tablename__ = "module_version"
    __table_args__ = (
        UniqueConstraint("moduleId", "version", name="uq_module_version_module_version"),
        {"comment": "Versions d'un module du catalogue ; une version publiée est immuable."},
    )

    moduleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("module.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, comment="Version semver (ex. 1.2.0).")
    digest: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="Empreinte du paquet.")
    provenance: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="Origine du paquet.")
    licence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    compatibility: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prerequisites: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stateVersion: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    publishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizationModule"
    __table_args__ = (
        UniqueConstraint("organizationId", "moduleCode", name="uq_organizationModule_org_module"),
        {"comment": "État d'activation d'un module pour une organisation donnée (active/inactive/trial)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="inactive")  # active | inactive | trial
    activatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
