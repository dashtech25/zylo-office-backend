"""mouvements de personnel en cours de tour : pauses, remplacements, réaffectations (B5)

Revision ID: a3e5c7b9d124
Revises: f2d4b6a8c013
Create Date: 2026-10-01

Scénario B5 : table `zyloLiquidShiftStaffMovement` (une action de l'utilisateur
pouvant toucher plusieurs pompes ; jamais supprimée, seulement annulée) et
colonnes ajoutées à `zyloLiquidShiftPumpAssignment` (segments de B4) : le segment
sait quel mouvement l'a créé / fermé, qui il couvre, s'il est tenu par le chef
d'équipe, et s'il a été neutralisé par une annulation. Les colonnes `startIndex`
(index au changement) et `closedForShift` (pompe fermée pendant la pause) existent
déjà depuis B4 et sont réutilisées. Migration écrite à la main, après celle de B4.
Aucune donnée créée (jamais de mouvement inventé).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a3e5c7b9d124"
down_revision = "f2d4b6a8c013"
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
        "zyloLiquidShiftStaffMovement",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("stationId", uuid_t, nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False, comment="break_start | break_end | replacement | reassignment."),
        sa.Column("occurredAt", sa.DateTime(timezone=True), nullable=False, comment="Heure RÉELLE du mouvement (≤ maintenant, ≥ ouverture du tour) ; ≠ recordedAt car la décision orale précède la saisie."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la saisie."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi (RT ou gérant) ; le chef d'équipe décide oralement, il n'écrit pas."),
        sa.Column("subjectUserId", uuid_t, nullable=False, comment="Pompiste concerné : celui qui part en pause, revient ou est remplacé ; pour une réaffectation, le NOUVEAU titulaire."),
        sa.Column("reason", sa.String(length=20), nullable=True, comment="Motif (remplacement et réaffectation) ; nul pour une pause (imposé par la nature)."),
        sa.Column("note", sa.String(length=255), nullable=True, comment="Observation ; obligatoire si motif « other » ou pompe fermée pendant la pause."),
        sa.Column("breakStartMovementId", uuid_t, nullable=True, comment="Pour un break_end : la pause terminée."),
        sa.Column("cancelledAt", sa.DateTime(timezone=True), nullable=True, comment="Annulation du mouvement (jamais de suppression)."),
        sa.Column("cancelledByUserId", uuid_t, nullable=True),
        sa.Column("cancelReason", sa.String(length=255), nullable=True, comment="Motif obligatoire de l'annulation."),
        sa.ForeignKeyConstraint(["reportId"], ["zyloLiquidShiftReport.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subjectUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["breakStartMovementId"], ["zyloLiquidShiftStaffMovement.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cancelledByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('break_start','break_end','replacement','reassignment')", name="ck_zlShiftStaffMovement_kind"),
        sa.CheckConstraint(
            "reason IS NULL OR reason IN ('absence_unforeseen','left_during_shift','rebalancing','late_arrival','pump_breakdown','other')",
            name="ck_zlShiftStaffMovement_reason",
        ),
        sa.CheckConstraint(
            '("cancelledAt" IS NULL) = ("cancelledByUserId" IS NULL) AND ("cancelledAt" IS NULL) = ("cancelReason" IS NULL)',
            name="ck_zlShiftStaffMovement_cancel_complete",
        ),
        comment="Mouvement de personnel en cours de tour (pause, retour, remplacement, réaffectation) ; jamais supprimé, seulement annulé.",
    )
    for column in ("reportId", "stationId", "subjectUserId", "breakStartMovementId"):
        op.create_index(op.f(f"ix_zyloLiquidShiftStaffMovement_{column}"), "zyloLiquidShiftStaffMovement", [column], unique=False)
    op.create_index("ix_zlShiftStaffMovement_report_occurred", "zyloLiquidShiftStaffMovement", ["reportId", "occurredAt"], unique=False)

    # Colonnes ajoutées aux segments d'affectation de B4 (aucun segment existant n'est réécrit).
    op.add_column("zyloLiquidShiftPumpAssignment", sa.Column("movementId", uuid_t, nullable=True, comment="Mouvement de personnel (B5) qui a créé ce segment ; nul pour un segment de départ (B4)."))
    op.add_column("zyloLiquidShiftPumpAssignment", sa.Column("closedByMovementId", uuid_t, nullable=True, comment="Mouvement (B5) qui a fermé ce segment (renseigne endsAt) ; remis à nul si ce mouvement est annulé."))
    op.add_column("zyloLiquidShiftPumpAssignment", sa.Column("coversUserId", uuid_t, nullable=True, comment="Pompiste remplacé ou en pause que ce segment couvre (break_cover, replacement) ; nul sinon."))
    op.add_column(
        "zyloLiquidShiftPumpAssignment",
        sa.Column("holderIsTeamLead", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="Vrai si le titulaire du segment est le chef d'équipe (remplaçant autorisé, PC-52) : marqueur figé à la création."),
    )
    op.add_column(
        "zyloLiquidShiftPumpAssignment",
        sa.Column("cancelledAt", sa.DateTime(timezone=True), nullable=True, comment="Renseigné quand le mouvement qui a créé ce segment est annulé : le segment est neutralisé (endsAt = startsAt), jamais supprimé, et exclu de la chronologie."),
    )
    op.create_foreign_key("fk_zlShiftPumpAssignment_movementId", "zyloLiquidShiftPumpAssignment", "zyloLiquidShiftStaffMovement", ["movementId"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_zlShiftPumpAssignment_closedByMovementId", "zyloLiquidShiftPumpAssignment", "zyloLiquidShiftStaffMovement", ["closedByMovementId"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_zlShiftPumpAssignment_coversUserId", "zyloLiquidShiftPumpAssignment", "user", ["coversUserId"], ["id"], ondelete="RESTRICT")
    op.create_index(op.f("ix_zyloLiquidShiftPumpAssignment_movementId"), "zyloLiquidShiftPumpAssignment", ["movementId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftPumpAssignment_closedByMovementId"), "zyloLiquidShiftPumpAssignment", ["closedByMovementId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zyloLiquidShiftPumpAssignment_closedByMovementId"), table_name="zyloLiquidShiftPumpAssignment")
    op.drop_index(op.f("ix_zyloLiquidShiftPumpAssignment_movementId"), table_name="zyloLiquidShiftPumpAssignment")
    op.drop_constraint("fk_zlShiftPumpAssignment_coversUserId", "zyloLiquidShiftPumpAssignment", type_="foreignkey")
    op.drop_constraint("fk_zlShiftPumpAssignment_closedByMovementId", "zyloLiquidShiftPumpAssignment", type_="foreignkey")
    op.drop_constraint("fk_zlShiftPumpAssignment_movementId", "zyloLiquidShiftPumpAssignment", type_="foreignkey")
    for column in ("cancelledAt", "holderIsTeamLead", "coversUserId", "closedByMovementId", "movementId"):
        op.drop_column("zyloLiquidShiftPumpAssignment", column)
    op.drop_index("ix_zlShiftStaffMovement_report_occurred", table_name="zyloLiquidShiftStaffMovement")
    for column in ("breakStartMovementId", "subjectUserId", "stationId", "reportId"):
        op.drop_index(op.f(f"ix_zyloLiquidShiftStaffMovement_{column}"), table_name="zyloLiquidShiftStaffMovement")
    op.drop_table("zyloLiquidShiftStaffMovement")
