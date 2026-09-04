"""Référentiel géographique commun (pays/régions/villes) — Core.

Décision d'architecture (instruction_2_base_donnees_phase_1.md §3/§11) : un
pays n'est pas une donnée spécifique à Zylo Liquid. Il est factorisé ici
pour qu'un futur module (CRM, RH, comptabilité...) puisse l'utiliser sans
avoir besoin que Zylo Liquid soit installé.

Source : trouvé dans la base PostgreSQL réelle `zylo_liquid` (tables `pays`,
`regions`, `villes`) mais ABSENT du schéma initialement validé
(`schema_complet_base_de_donnees.sql`) — c'est une évolution réelle,
postérieure au document source, confirmée par inspection directe de la base
de test (6 pays, 16 régions, 16 villes, couverture panafricaine réelle :
Cameroun, Côte d'Ivoire, Sénégal, Nigeria, Kenya, Afrique du Sud). Voir
phase_1_database.md §5 pour la comparaison complète.

Noms de colonnes traduits en camelCase anglais conformément à la convention
Zylo Office déjà établie (grande_phases.md §5.3) — structure, contraintes et
sémantique conservées à l'identique depuis la base réelle."""

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
import uuid

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Country(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "country"
    __table_args__ = (
        UniqueConstraint("isoCode2", name="uq_country_isoCode2"),
        CheckConstraint("\"isoCode2\" = upper(\"isoCode2\")", name="ck_country_isoCode2_upper"),
        {"comment": "Référentiel des pays — commun à tous les modules (Core). Source : table 'pays' de la base zylo_liquid réelle, absente du schéma initial validé."},
    )

    isoCode2: Mapped[str] = mapped_column(String(2), nullable=False)
    isoCode3: Mapped[str | None] = mapped_column(String(3), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    currencyCode: Mapped[str] = mapped_column(String(3), nullable=False, default="XAF")
    currencySymbol: Mapped[str] = mapped_column(String(10), nullable=False, default="FCFA")
    phonePrefix: Mapped[str | None] = mapped_column(String(6), nullable=True)
    defaultTimezone: Mapped[str] = mapped_column(String(50), nullable=False, default="Africa/Douala")
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class Region(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "region"
    __table_args__ = (
        UniqueConstraint("countryId", "name", name="uq_region_country_name"),
        {"comment": "Découpage administratif régional d'un pays (Core). Source : table 'regions' de la base zylo_liquid réelle."},
    )

    countryId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("country.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)


class City(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "city"
    __table_args__ = (
        UniqueConstraint("regionId", "name", name="uq_city_region_name"),
        {"comment": "Ville rattachée à une région (Core). Source : table 'villes' de la base zylo_liquid réelle."},
    )

    regionId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("region.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    longitude: Mapped[float | None] = mapped_column(Numeric(10, 7), nullable=True)
    population: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)
