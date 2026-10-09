"""shift definition

Revision ID: 5b8d3f1a6c24
Revises: 7e2d9c4b8a51
Create Date: 2026-10-01

Scénario A9 (définir les tours d'une station) : table `zyloLiquidShiftDefinition`
(modèle de tour « Matin 06:00 → 14:00 », jamais supprimé, seulement désactivé).
Migration écrite à la main. Les contraintes uniques (station + numéro, station
+ nom) sont DIFFÉRÉES : l'enregistrement en lot peut échanger deux numéros ou
deux noms dans une même transaction sans échec transitoire. Aucun tour par
défaut n'est créé (aucune donnée inventée).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "5b8d3f1a6c24"
down_revision = "7e2d9c4b8a51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zyloLiquidShiftDefinition",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("stationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shiftNumber", sa.SmallInteger(), nullable=False, comment="Numéro d'ordre du tour, unique par station (ordre d'affichage)."),
        sa.Column("name", sa.String(length=100), nullable=False, comment="Nom du tour, unique par station."),
        sa.Column("startTime", sa.String(length=5), nullable=False, comment="Heure de début locale, format HH:MM."),
        sa.Column("endTime", sa.String(length=5), nullable=False, comment="Heure de fin locale, format HH:MM ; fin <= début = passe minuit (début = fin = 24 h)."),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stationId", "shiftNumber", name="uq_zlShiftDefinition_station_number", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("stationId", "name", name="uq_zlShiftDefinition_station_name", deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint('"shiftNumber" > 0', name="ck_zlShiftDefinition_shiftNumber_positive"),
        comment="Modèle de tour (période de travail d'une équipe) d'une station ; référentiel, sans planning.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftDefinition_stationId"), "zyloLiquidShiftDefinition", ["stationId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zyloLiquidShiftDefinition_stationId"), table_name="zyloLiquidShiftDefinition")
    op.drop_table("zyloLiquidShiftDefinition")
