"""ouverture du tour et rapport de tour (B3)

Revision ID: e1c3a5f7b902
Revises: d6b2e9f4a713
Create Date: 2026-10-01

Scénario B3 : tables `zyloLiquidShiftReport`, `zyloLiquidShiftReportPumpLine`
et `zyloLiquidShiftReportTankLine` (rapport de tour créé à l'ouverture, une
ligne par pompe active et par cuve active, instantané des libellés) ; colonnes
`openedByUserId` et `offPlanning` sur `zyloLiquidShiftOccurrence` (`openedAt`
existe déjà depuis A5) ; index unique partiel « un seul tour ouvert par
station ». Les colonnes `closingIndex` / `closingRealStockLiters` sont
RÉSERVÉES à D1/D2 (nulles, non écrites par B3) : elles alimentent le report
vers le tour suivant. Migration écrite à la main. Aucune donnée créée (jamais
de donnée inventée).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e1c3a5f7b902"
down_revision = "d6b2e9f4a713"
branch_labels = None
depends_on = None


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    # --- Occurrence : qui a ouvert, ouverture hors planning, un seul tour ouvert par station.
    op.add_column("zyloLiquidShiftOccurrence", sa.Column("openedByUserId", uuid_t, nullable=True, comment="Utilisateur qui a ouvert le tour (B3) ; peut être le gérant."))
    op.add_column("zyloLiquidShiftOccurrence", sa.Column("offPlanning", sa.Boolean(), server_default="false", nullable=False, comment="Vrai si l'occurrence a été créée à l'ouverture, faute de planning (B3)."))
    op.create_foreign_key("fk_zlShiftOccurrence_openedByUserId_user", "zyloLiquidShiftOccurrence", "user", ["openedByUserId"], ["id"], ondelete="RESTRICT")
    op.create_index("uq_zlShiftOccurrence_station_opened", "zyloLiquidShiftOccurrence", ["stationId"], unique=True, postgresql_where=sa.text("status = 'opened'"))

    # --- Rapport de tour.
    op.create_table(
        "zyloLiquidShiftReport",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("stationId", uuid_t, nullable=False),
        sa.Column("occurrenceId", uuid_t, nullable=False, comment="Tour (occurrence A5) dont ce rapport est le rapport ; un seul rapport par tour."),
        sa.Column("shiftDate", sa.Date(), nullable=False, comment="Journée du rapport = date de début du tour (copie de l'occurrence)."),
        sa.Column("shiftNumber", sa.SmallInteger(), nullable=False, comment="Copie du numéro du tour."),
        sa.Column("shiftName", sa.String(length=100), nullable=False, comment="Copie du nom du tour."),
        sa.Column("startTime", sa.String(length=5), nullable=False, comment="Copie de l'heure de début (HH:MM)."),
        sa.Column("endTime", sa.String(length=5), nullable=False, comment="Copie de l'heure de fin (HH:MM)."),
        sa.Column("responsibleUserId", uuid_t, nullable=False, comment="Responsable de tour RÉEL du rapport (en-tête)."),
        sa.Column("responsiblePhone", sa.String(length=20), nullable=True, comment="Téléphone du responsable copié du compte ou saisi à l'ouverture ; jamais inventé."),
        sa.Column("plannedResponsibleUserId", uuid_t, nullable=True, comment="Responsable de tour PRÉVU au planning (A5) ; nul si aucun (trace prévu vs réel)."),
        sa.Column("openedByUserId", uuid_t, nullable=False, comment="Utilisateur qui a ouvert le tour (peut être le gérant)."),
        sa.Column("openedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'ouverture (UTC)."),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["occurrenceId"], ["zyloLiquidShiftOccurrence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["responsibleUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plannedResponsibleUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["openedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrenceId", name="uq_zlShiftReport_occurrence"),
        comment="Rapport de tour d'une station (un par occurrence), créé à l'ouverture du tour : en-tête, responsable de tour prévu et réel.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftReport_stationId"), "zyloLiquidShiftReport", ["stationId"], unique=False)
    op.create_index("ix_zlShiftReport_station_date", "zyloLiquidShiftReport", ["stationId", "shiftDate"], unique=False)

    # --- Ligne de pompe.
    op.create_table(
        "zyloLiquidShiftReportPumpLine",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("pumpId", uuid_t, nullable=False),
        sa.Column("pumpNumber", sa.SmallInteger(), nullable=False, comment="Instantané du numéro de la pompe à l'ouverture."),
        sa.Column("pumpName", sa.String(length=100), nullable=False, comment="Instantané du nom généré de la pompe."),
        sa.Column("tankId", uuid_t, nullable=False, comment="Instantané de la cuve de la pompe à l'ouverture."),
        sa.Column("fuelProductName", sa.String(length=100), nullable=False, comment="Instantané du produit (via la cuve)."),
        sa.Column("openingIndex", sa.Numeric(14, 2), nullable=False, comment="Index d'ouverture ; comparé en décimal exact, jamais en flottant."),
        sa.Column("openingSource", sa.String(length=20), nullable=False, comment="carried (reporté de la fermeture précédente) | initial (premier tour de la pompe, saisi) | continuity_break (écart déclaré avec motif)."),
        sa.Column("carriedIndex", sa.Numeric(14, 2), nullable=True, comment="Fermeture précédente que le serveur avait calculée (écart = openingIndex - carriedIndex) ; nul si initial."),
        sa.Column("previousLineId", uuid_t, nullable=True, comment="Ligne du tour précédent dont la fermeture a été reportée (traçabilité) ; nul si initial."),
        sa.Column("continuityBreakReason", sa.String(length=20), nullable=True, comment="meter_replaced | meter_reset | carry_error | other (écart de continuité seulement)."),
        sa.Column("continuityBreakNote", sa.String(length=300), nullable=True, comment="Précision de l'écart de continuité (10 caractères minimum)."),
        sa.Column("addedDuringShift", sa.Boolean(), server_default="false", nullable=False, comment="Vrai si la ligne a été ajoutée explicitement après l'ouverture (« Ajouter une pompe au tour »)."),
        sa.Column("lockedAt", sa.DateTime(timezone=True), nullable=True, comment="Verrouillage de l'ouverture à la création ; correction possible seulement tant que le tour est ouvert (initial/écart)."),
        sa.Column("closingIndex", sa.Numeric(14, 2), nullable=True, comment="Index de fermeture : RÉSERVÉ à D1 (non écrit par B3) ; sert de source au report du tour suivant."),
        sa.ForeignKeyConstraint(["reportId"], ["zyloLiquidShiftReport.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pumpId"], ["zyloLiquidPump.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tankId"], ["zyloLiquidTank.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previousLineId"], ["zyloLiquidShiftReportPumpLine.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reportId", "pumpId", name="uq_zlShiftReportPumpLine_report_pump"),
        sa.CheckConstraint("\"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportPumpLine_openingSource"),
        sa.CheckConstraint("\"openingIndex\" >= 0", name="ck_zlShiftReportPumpLine_openingIndex_positive"),
        sa.CheckConstraint("\"openingSource\" = 'continuity_break' OR (\"continuityBreakReason\" IS NULL AND \"continuityBreakNote\" IS NULL)", name="ck_zlShiftReportPumpLine_break_only_on_break"),
        comment="Ligne de pompe d'un rapport de tour : index d'ouverture (reporté, initial ou écart déclaré) et instantané des libellés de la pompe.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftReportPumpLine_reportId"), "zyloLiquidShiftReportPumpLine", ["reportId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftReportPumpLine_pumpId"), "zyloLiquidShiftReportPumpLine", ["pumpId"], unique=False)

    # --- Ligne de cuve.
    op.create_table(
        "zyloLiquidShiftReportTankLine",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("tankId", uuid_t, nullable=False),
        sa.Column("tankNumber", sa.SmallInteger(), nullable=False, comment="Instantané du numéro de la cuve."),
        sa.Column("tankName", sa.String(length=100), nullable=False, comment="Instantané du libellé de la cuve."),
        sa.Column("fuelProductName", sa.String(length=100), nullable=False, comment="Instantané du produit de la cuve."),
        sa.Column("capacityLiters", sa.Numeric(12, 2), nullable=False, comment="Instantané de la capacité de la cuve (litres)."),
        sa.Column("openingStockLiters", sa.Numeric(12, 2), nullable=False, comment="Stock d'ouverture en litres, entre 0 et la capacité."),
        sa.Column("openingStockSource", sa.String(length=20), nullable=False, comment="previous_real_stock (stock réel de fermeture du tour précédent, D2) | initial (saisi)."),
        sa.Column("previousTankLineId", uuid_t, nullable=True, comment="Ligne de cuve du tour précédent reportée ; nulle si initial."),
        sa.Column("closingRealStockLiters", sa.Numeric(12, 2), nullable=True, comment="Stock réel de fermeture en litres : RÉSERVÉ à D2 (non écrit par B3) ; source du report du tour suivant."),
        sa.ForeignKeyConstraint(["reportId"], ["zyloLiquidShiftReport.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tankId"], ["zyloLiquidTank.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previousTankLineId"], ["zyloLiquidShiftReportTankLine.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reportId", "tankId", name="uq_zlShiftReportTankLine_report_tank"),
        sa.CheckConstraint("\"openingStockSource\" IN ('previous_real_stock','initial')", name="ck_zlShiftReportTankLine_openingStockSource"),
        sa.CheckConstraint("\"openingStockLiters\" >= 0", name="ck_zlShiftReportTankLine_openingStock_positive"),
        comment="Ligne de cuve d'un rapport de tour : stock d'ouverture en litres (reporté ou initial) et instantané des libellés de la cuve.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftReportTankLine_reportId"), "zyloLiquidShiftReportTankLine", ["reportId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftReportTankLine_tankId"), "zyloLiquidShiftReportTankLine", ["tankId"], unique=False)


def downgrade() -> None:
    op.drop_table("zyloLiquidShiftReportTankLine")
    op.drop_table("zyloLiquidShiftReportPumpLine")
    op.drop_table("zyloLiquidShiftReport")
    op.drop_index("uq_zlShiftOccurrence_station_opened", table_name="zyloLiquidShiftOccurrence")
    op.drop_constraint("fk_zlShiftOccurrence_openedByUserId_user", "zyloLiquidShiftOccurrence", type_="foreignkey")
    op.drop_column("zyloLiquidShiftOccurrence", "offPlanning")
    op.drop_column("zyloLiquidShiftOccurrence", "openedByUserId")
