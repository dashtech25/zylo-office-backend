"""shift planning (occurrences et affectations)

Revision ID: c5a1d8e3f702
Revises: a4c9e7d2b583
Create Date: 2026-10-01

Scénario A5 (planning des tours) : tables `zyloLiquidShiftOccurrence` (tour du
jour planifié, horaires COPIÉS du modèle, jamais resynchronisés) et
`zyloLiquidShiftAssignment` (personne + rôle dans le tour + pompe optionnelle).
Migration écrite à la main. Index uniques partiels : une pompe = un pompiste
par occurrence, un seul responsable de tour par occurrence. Aucune donnée
créée (aucun planning par défaut, jamais de donnée inventée).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c5a1d8e3f702"
down_revision = "a4c9e7d2b583"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "zyloLiquidShiftOccurrence",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("stationId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shiftDefinitionId", postgresql.UUID(as_uuid=True), nullable=False, comment="Modèle d'origine ; référence conservée, mais les champs copiés ci-dessous font foi pour l'occurrence."),
        sa.Column("shiftDate", sa.Date(), nullable=False, comment="Date locale de DÉBUT du tour (un tour de nuit du lundi appartient au lundi)."),
        sa.Column("shiftNumber", sa.SmallInteger(), nullable=False, comment="Copie du numéro d'ordre du modèle à la planification."),
        sa.Column("name", sa.String(length=100), nullable=False, comment="Copie du nom du modèle à la planification."),
        sa.Column("startTime", sa.String(length=5), nullable=False, comment="Copie de l'heure de début locale (HH:MM)."),
        sa.Column("endTime", sa.String(length=5), nullable=False, comment="Copie de l'heure de fin locale (HH:MM) ; fin <= début = passe minuit."),
        sa.Column("startsAt", sa.DateTime(timezone=False), nullable=False, comment="Début réel prévu (date + heure copiée), heure locale station."),
        sa.Column("endsAt", sa.DateTime(timezone=False), nullable=False, comment="Fin réelle prévue (lendemain si le tour passe minuit), heure locale station ; sert au contrôle de chevauchement."),
        sa.Column("status", sa.String(length=20), server_default="planned", nullable=False, comment="planned (géré par A5) | opened | closed | validated (B3 et suite)."),
        sa.Column("openedAt", sa.DateTime(timezone=True), nullable=True, comment="Ouverture réelle du tour (B3), non géré par A5."),
        sa.Column("closedAt", sa.DateTime(timezone=True), nullable=True, comment="Clôture réelle du tour, non gérée par A5."),
        sa.Column("validatedAt", sa.DateTime(timezone=True), nullable=True, comment="Validation du tour, non gérée par A5."),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shiftDefinitionId"], ["zyloLiquidShiftDefinition.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stationId", "shiftDate", "shiftDefinitionId", name="uq_zlShiftOccurrence_station_date_shift"),
        sa.CheckConstraint("status IN ('planned','opened','closed','validated')", name="ck_zlShiftOccurrence_status"),
        comment="Tour du jour planifié d'une station (date + modèle de tour), horaires copiés du modèle ; cycle planned -> opened -> closed -> validated.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftOccurrence_stationId"), "zyloLiquidShiftOccurrence", ["stationId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftOccurrence_shiftDefinitionId"), "zyloLiquidShiftOccurrence", ["shiftDefinitionId"], unique=False)
    op.create_index("ix_zlShiftOccurrence_station_date", "zyloLiquidShiftOccurrence", ["stationId", "shiftDate"], unique=False)

    op.create_table(
        "zyloLiquidShiftAssignment",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("occurrenceId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("userId", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shiftRole", sa.String(length=20), nullable=False, comment="shift_manager | team_lead | pump_attendant."),
        sa.Column("pumpId", postgresql.UUID(as_uuid=True), nullable=True, comment="Pompe tenue (pompiste seulement) ; NULL = placé sans pompe précise (renfort)."),
        sa.ForeignKeyConstraint(["occurrenceId"], ["zyloLiquidShiftOccurrence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["userId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpId"], ["zyloLiquidPump.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("\"shiftRole\" IN ('shift_manager','team_lead','pump_attendant')", name="ck_zlShiftAssignment_shiftRole"),
        sa.CheckConstraint("\"pumpId\" IS NULL OR \"shiftRole\" = 'pump_attendant'", name="ck_zlShiftAssignment_pump_only_attendant"),
        comment="Affectation d'une personne à un tour planifié : rôle dans le tour et pompe optionnelle (pompiste).",
    )
    op.create_index(op.f("ix_zyloLiquidShiftAssignment_occurrenceId"), "zyloLiquidShiftAssignment", ["occurrenceId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftAssignment_userId"), "zyloLiquidShiftAssignment", ["userId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftAssignment_pumpId"), "zyloLiquidShiftAssignment", ["pumpId"], unique=False)
    # Un pompiste peut tenir plusieurs pompes dans un tour : seule la ligne « sans pompe » est unique par personne.
    op.create_index(
        "uq_zlShiftAssignment_occurrence_user_nopump", "zyloLiquidShiftAssignment", ["occurrenceId", "userId"], unique=True,
        postgresql_where=sa.text('"pumpId" IS NULL'),
    )
    op.create_index(
        "uq_zlShiftAssignment_occurrence_pump", "zyloLiquidShiftAssignment", ["occurrenceId", "pumpId"], unique=True,
        postgresql_where=sa.text('"pumpId" IS NOT NULL'),
    )
    op.create_index(
        "uq_zlShiftAssignment_occurrence_manager", "zyloLiquidShiftAssignment", ["occurrenceId"], unique=True,
        postgresql_where=sa.text("\"shiftRole\" = 'shift_manager'"),
    )


def downgrade() -> None:
    op.drop_index("uq_zlShiftAssignment_occurrence_user_nopump", table_name="zyloLiquidShiftAssignment")
    op.drop_index("uq_zlShiftAssignment_occurrence_manager", table_name="zyloLiquidShiftAssignment")
    op.drop_index("uq_zlShiftAssignment_occurrence_pump", table_name="zyloLiquidShiftAssignment")
    op.drop_index(op.f("ix_zyloLiquidShiftAssignment_pumpId"), table_name="zyloLiquidShiftAssignment")
    op.drop_index(op.f("ix_zyloLiquidShiftAssignment_userId"), table_name="zyloLiquidShiftAssignment")
    op.drop_index(op.f("ix_zyloLiquidShiftAssignment_occurrenceId"), table_name="zyloLiquidShiftAssignment")
    op.drop_table("zyloLiquidShiftAssignment")
    op.drop_index("ix_zlShiftOccurrence_station_date", table_name="zyloLiquidShiftOccurrence")
    op.drop_index(op.f("ix_zyloLiquidShiftOccurrence_shiftDefinitionId"), table_name="zyloLiquidShiftOccurrence")
    op.drop_index(op.f("ix_zyloLiquidShiftOccurrence_stationId"), table_name="zyloLiquidShiftOccurrence")
    op.drop_table("zyloLiquidShiftOccurrence")
