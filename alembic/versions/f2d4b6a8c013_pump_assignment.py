"""affectation réelle des pompistes aux pompes (B4)

Revision ID: f2d4b6a8c013
Revises: e1c3a5f7b902
Create Date: 2026-10-01

Scénario B4 : tables `zyloLiquidShiftPumpAssignmentSheet` (confirmation/verrou de
l'affectation de départ d'un rapport de tour, une par rapport) et
`zyloLiquidShiftPumpAssignment` (segments d'affectation d'une pompe à un pompiste,
chronologie par pompe ; prévu A5 et réel conservés côte à côte). Migration écrite à
la main, après celle de B3 (rapport de tour et lignes de pompe). Aucune donnée créée
(jamais d'affectation inventée).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f2d4b6a8c013"
down_revision = "e1c3a5f7b902"
branch_labels = None
depends_on = None


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    op.create_table(
        "zyloLiquidShiftPumpAssignmentSheet",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False, comment="Rapport de tour (B3) dont l'affectation de départ est confirmée."),
        sa.Column("stationId", uuid_t, nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False, comment="Incrémentée à chaque modification de l'affectation (B4 : 1 à la confirmation ; B5 ensuite) ; verrou optimiste."),
        sa.Column("plannedDeciderUserId", uuid_t, nullable=True, comment="Chef d'équipe PRÉVU au planning (A5) à la confirmation ; figé, jamais écrasé."),
        sa.Column("decidedByUserId", uuid_t, nullable=True, comment="Chef d'équipe décideur (information, non authentifiante : il décide oralement, le RT saisit)."),
        sa.Column("confirmedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la confirmation (verrou)."),
        sa.Column("confirmedByUserId", uuid_t, nullable=False, comment="Utilisateur qui a saisi et confirmé (RT ou gérant)."),
        sa.ForeignKeyConstraint(["reportId"], ["zyloLiquidShiftReport.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plannedDeciderUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decidedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["confirmedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reportId", name="uq_zlShiftPumpAssignmentSheet_report"),
        comment="Confirmation (verrou) de l'affectation de départ des pompistes d'un rapport de tour ; une par rapport.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftPumpAssignmentSheet_stationId"), "zyloLiquidShiftPumpAssignmentSheet", ["stationId"], unique=False)

    op.create_table(
        "zyloLiquidShiftPumpAssignment",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("pumpLineId", uuid_t, nullable=False, comment="Ligne de pompe du rapport (B3) ; la pompe est celle de la ligne."),
        sa.Column("pumpId", uuid_t, nullable=False, comment="Pompe (copie de la ligne, pour les requêtes par pompe)."),
        sa.Column("userId", uuid_t, nullable=True, comment="Pompiste RÉEL ; nul seulement si la pompe est fermée pour ce tour."),
        sa.Column("plannedUserId", uuid_t, nullable=True, comment="Pompiste PRÉVU (copie de l'affectation A5 de cette pompe), figé à la confirmation ; nul si aucun prévu. Jamais modifié."),
        sa.Column("startsAt", sa.DateTime(timezone=True), nullable=False, comment="Début du segment ; segment de départ = ouverture du tour (la décision orale précède la saisie)."),
        sa.Column("endsAt", sa.DateTime(timezone=True), nullable=True, comment="Fin du segment ; nulle tant qu'il est en cours (renseignée par B5)."),
        sa.Column("kind", sa.String(length=20), server_default="start", nullable=False, comment="start (B4) | break_cover | break_return | replacement | late_arrival | reassignment (B5)."),
        sa.Column("startIndex", sa.Numeric(14, 2), nullable=True, comment="Index de la pompe au début du segment (index d'ouverture pour un segment de départ) ; sert à B5 pour répartir les litres."),
        sa.Column("closedForShift", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="Pompe fermée pour ce tour : aucun pompiste, observation obligatoire."),
        sa.Column("note", sa.String(length=255), nullable=True, comment="Observation (obligatoire si la pompe est fermée)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la saisie (≠ startsAt : la décision orale précède la saisie)."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi (RT, ou gérant à sa place)."),
        sa.ForeignKeyConstraint(["reportId"], ["zyloLiquidShiftReport.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpLineId"], ["zyloLiquidShiftReportPumpLine.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpId"], ["zyloLiquidPump.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["userId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plannedUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('start','break_cover','break_return','replacement','late_arrival','reassignment')", name="ck_zlShiftPumpAssignment_kind"),
        sa.CheckConstraint('"userId" IS NOT NULL OR "closedForShift"', name="ck_zlShiftPumpAssignment_user_or_closed"),
        sa.CheckConstraint('NOT "closedForShift" OR ("userId" IS NULL AND note IS NOT NULL)', name="ck_zlShiftPumpAssignment_closed_needs_note_no_user"),
        sa.CheckConstraint('"endsAt" IS NULL OR "endsAt" >= "startsAt"', name="ck_zlShiftPumpAssignment_period"),
        comment="Segment d'affectation d'une pompe à un pompiste pendant un tour (chronologie ; prévu A5 et réel conservés).",
    )
    for column in ("reportId", "pumpLineId", "pumpId", "userId"):
        op.create_index(op.f(f"ix_zyloLiquidShiftPumpAssignment_{column}"), "zyloLiquidShiftPumpAssignment", [column], unique=False)
    # Une pompe n'a qu'UN titulaire à un instant donné ; un pompiste peut tenir plusieurs pompes.
    op.create_index(
        "uq_zlShiftPumpAssignment_current", "zyloLiquidShiftPumpAssignment", ["reportId", "pumpLineId"],
        unique=True, postgresql_where=sa.text('"endsAt" IS NULL'),
    )


def downgrade() -> None:
    op.drop_index("uq_zlShiftPumpAssignment_current", table_name="zyloLiquidShiftPumpAssignment")
    for column in ("userId", "pumpId", "pumpLineId", "reportId"):
        op.drop_index(op.f(f"ix_zyloLiquidShiftPumpAssignment_{column}"), table_name="zyloLiquidShiftPumpAssignment")
    op.drop_table("zyloLiquidShiftPumpAssignment")
    op.drop_index(op.f("ix_zyloLiquidShiftPumpAssignmentSheet_stationId"), table_name="zyloLiquidShiftPumpAssignmentSheet")
    op.drop_table("zyloLiquidShiftPumpAssignmentSheet")
