"""pointage des présences (B1) et passation entre responsables de tour (B2)

Revision ID: d6b2e9f4a713
Revises: c5a1d8e3f702
Create Date: 2026-10-01

Scénarios B1 et B2 : tables `zyloLiquidShiftAttendanceSheet` /
`zyloLiquidShiftAttendanceLine` (feuille de pointage d'une occurrence A5, prévu
et réel conservés côte à côte) et `zyloLiquidShiftHandover` /
`zyloLiquidShiftHandoverItem` (passation ancrée au tour sortant, lignes
typées consigne / anomalie en cours / information). Migration écrite à la
main. Aucune donnée créée (pas de pointage ni de passation par défaut :
jamais de donnée inventée).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d6b2e9f4a713"
down_revision = "c5a1d8e3f702"
branch_labels = None
depends_on = None


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    # ---------------------------------------------------------------- B1
    op.create_table(
        "zyloLiquidShiftAttendanceSheet",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("stationId", uuid_t, nullable=False),
        sa.Column("occurrenceId", uuid_t, nullable=False, comment="Tour (occurrence A5) pointé ; une seule feuille par tour."),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False, comment="Incrémentée à chaque enregistrement ; verrou optimiste."),
        sa.Column("firstSignedByUserId", uuid_t, nullable=False, comment="Auteur du premier enregistrement (jamais modifié)."),
        sa.Column("firstSignedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur du premier enregistrement (jamais modifié)."),
        sa.Column("lastSignedByUserId", uuid_t, nullable=False, comment="Signature : auteur du dernier enregistrement."),
        sa.Column("lastSignedAt", sa.DateTime(timezone=True), nullable=False, comment="Signature : horodatage serveur du dernier enregistrement."),
        sa.Column("lifecycleStatus", sa.String(length=10), server_default="declared", nullable=False, comment="declared | locked (tour validé, E1)."),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["occurrenceId"], ["zyloLiquidShiftOccurrence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["firstSignedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lastSignedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrenceId", name="uq_zlShiftAttendanceSheet_occurrence"),
        sa.CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlShiftAttendanceSheet_lifecycleStatus"),
        comment="Feuille de pointage d'un tour (une par occurrence) : signature du dernier enregistrement et version pour le verrou optimiste.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftAttendanceSheet_stationId"), "zyloLiquidShiftAttendanceSheet", ["stationId"], unique=False)

    op.create_table(
        "zyloLiquidShiftAttendanceLine",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("sheetId", uuid_t, nullable=False),
        sa.Column("lineKind", sa.String(length=12), nullable=False, comment="planned | replacement | unplanned (déduit, jamais saisi)."),
        sa.Column("plannedAssignmentId", uuid_t, nullable=True, comment="Affectation A5 représentant la personne prévue (kind planned) ; le prévu se lit via elle, jamais recopié."),
        sa.Column("replacesLineId", uuid_t, nullable=True, comment="Ligne `planned` absente remplacée par cette ligne (kind replacement) ; un seul remplaçant par absent."),
        sa.Column("personUserId", uuid_t, nullable=True, comment="Personne pointée ; NULL pour un remplaçant externe sans compte (nom libre)."),
        sa.Column("externalName", sa.String(length=120), nullable=True, comment="Nom libre d'un remplaçant externe sans compte (jamais affectable à une pompe sans compte)."),
        sa.Column("shiftRole", sa.String(length=20), nullable=False, comment="Rôle réel dans le tour : planned = rôle de l'affectation ; replacement = rôle de la ligne remplacée ; unplanned = poste de la personne."),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False, comment="pending (à pointer, défaut) | present | late | absent_justified | absent_unjustified."),
        sa.Column("arrivedAt", sa.DateTime(timezone=False), nullable=True, comment="Arrivée réelle (heure locale station, résolue depuis HH:MM) ; obligatoire si present/late, interdite sinon."),
        sa.Column("departedAt", sa.DateTime(timezone=False), nullable=True, comment="Départ réel (heure locale station) ; facultatif, postérieur à l'arrivée."),
        sa.Column("reason", sa.String(length=300), nullable=True, comment="Motif (obligatoire pour absent_justified, facultatif pour absent_unjustified et late, interdit sinon)."),
        sa.Column("note", sa.String(length=300), nullable=True, comment="Note libre facultative."),
        sa.Column("declaredByUserId", uuid_t, nullable=False, comment="Auteur de la dernière modification de cette ligne."),
        sa.Column("declaredAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la dernière modification de cette ligne."),
        sa.Column("changeReason", sa.Text(), nullable=True, comment="Raison d'une correction faite alors que le tour est clos."),
        sa.ForeignKeyConstraint(["sheetId"], ["zyloLiquidShiftAttendanceSheet.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plannedAssignmentId"], ["zyloLiquidShiftAssignment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["replacesLineId"], ["zyloLiquidShiftAttendanceLine.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["personUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["declaredByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("sheetId", "plannedAssignmentId", name="uq_zlShiftAttendanceLine_sheet_assignment"),
        sa.UniqueConstraint("replacesLineId", name="uq_zlShiftAttendanceLine_replaces"),
        sa.CheckConstraint("\"lineKind\" IN ('planned','replacement','unplanned')", name="ck_zlShiftAttendanceLine_lineKind"),
        sa.CheckConstraint("status IN ('pending','present','late','absent_justified','absent_unjustified')", name="ck_zlShiftAttendanceLine_status"),
        sa.CheckConstraint("\"lineKind\" <> 'replacement' OR \"replacesLineId\" IS NOT NULL", name="ck_zlShiftAttendanceLine_replacement_needs_target"),
        sa.CheckConstraint("\"replacesLineId\" IS NULL OR \"lineKind\" = 'replacement'", name="ck_zlShiftAttendanceLine_target_only_replacement"),
        sa.CheckConstraint("\"lineKind\" <> 'planned' OR \"plannedAssignmentId\" IS NOT NULL", name="ck_zlShiftAttendanceLine_planned_needs_assignment"),
        sa.CheckConstraint("\"plannedAssignmentId\" IS NULL OR \"lineKind\" = 'planned'", name="ck_zlShiftAttendanceLine_assignment_only_planned"),
        sa.CheckConstraint("status IN ('present','late') OR (\"arrivedAt\" IS NULL AND \"departedAt\" IS NULL)", name="ck_zlShiftAttendanceLine_no_times_if_absent"),
        sa.CheckConstraint("(\"personUserId\" IS NULL) <> (\"externalName\" IS NULL)", name="ck_zlShiftAttendanceLine_person_xor_external"),
        sa.CheckConstraint("\"shiftRole\" IN ('shift_manager','team_lead','pump_attendant')", name="ck_zlShiftAttendanceLine_shiftRole"),
        comment="Ligne de pointage d'un tour : personne planifiée, remplaçant lié ou personne hors planning ; prévu (affectation A5) et réel (statut, heures) conservés côte à côte.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftAttendanceLine_sheetId"), "zyloLiquidShiftAttendanceLine", ["sheetId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftAttendanceLine_plannedAssignmentId"), "zyloLiquidShiftAttendanceLine", ["plannedAssignmentId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftAttendanceLine_personUserId"), "zyloLiquidShiftAttendanceLine", ["personUserId"], unique=False)
    op.create_index(
        "uq_zlShiftAttendanceLine_sheet_person", "zyloLiquidShiftAttendanceLine", ["sheetId", "personUserId"], unique=True,
        postgresql_where=sa.text('"personUserId" IS NOT NULL'),
    )

    # ---------------------------------------------------------------- B2
    op.create_table(
        "zyloLiquidShiftHandover",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("stationId", uuid_t, nullable=False),
        sa.Column("occurrenceId", uuid_t, nullable=False, comment="Occurrence SORTANTE : la passation est ce que ce tour laisse au suivant."),
        sa.Column("nothingToReport", sa.Boolean(), server_default="false", nullable=False, comment="« Rien à signaler » explicite : vrai exige zéro ligne, faux exige au moins une ligne."),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False, comment="Incrémentée à chaque enregistrement ; verrou optimiste (409 handover_changed)."),
        sa.Column("firstSignedByUserId", uuid_t, nullable=False, comment="Auteur du premier enregistrement (jamais modifié)."),
        sa.Column("firstSignedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur du premier enregistrement (jamais modifié)."),
        sa.Column("lastSignedByUserId", uuid_t, nullable=False, comment="Signature : auteur du dernier enregistrement."),
        sa.Column("lastSignedAt", sa.DateTime(timezone=True), nullable=False, comment="Signature : horodatage serveur du dernier enregistrement."),
        sa.Column("receivedByUserId", uuid_t, nullable=True, comment="Personne ayant pris connaissance (dernière prise) ; NULL = pas encore reçue."),
        sa.Column("receivedAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage serveur de la dernière prise de connaissance ; la première reste dans l'audit."),
        sa.Column("receivingOccurrenceId", uuid_t, nullable=True, comment="Occurrence du tour suivant au moment de la prise de connaissance ; NULL si aucun tour suivant."),
        sa.Column("lifecycleStatus", sa.String(length=10), server_default="declared", nullable=False, comment="declared | locked (tour sortant validé, E1)."),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["occurrenceId"], ["zyloLiquidShiftOccurrence.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receivingOccurrenceId"], ["zyloLiquidShiftOccurrence.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["firstSignedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lastSignedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receivedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("occurrenceId", name="uq_zlShiftHandover_occurrence"),
        sa.CheckConstraint("\"lifecycleStatus\" IN ('declared','locked')", name="ck_zlShiftHandover_lifecycleStatus"),
        comment="Passation d'un tour sortant au suivant (une par occurrence) : signature, case « rien à signaler », prise de connaissance.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftHandover_stationId"), "zyloLiquidShiftHandover", ["stationId"], unique=False)

    op.create_table(
        "zyloLiquidShiftHandoverItem",
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("handoverId", uuid_t, nullable=False),
        sa.Column("position", sa.SmallInteger(), server_default="0", nullable=False, comment="Ordre de saisie dans le tableau (affichage)."),
        sa.Column("kind", sa.String(length=12), nullable=False, comment="instruction (consigne) | open_issue (anomalie en cours) | info (information)."),
        sa.Column("category", sa.String(length=20), nullable=False, comment="pump | tank | delivery | price_credit | safety | staff | customer | report_feedback | other."),
        sa.Column("pumpId", uuid_t, nullable=True, comment="Pompe concernée (catégorie pump) ; une pompe désactivée reste choisissable."),
        sa.Column("tankId", uuid_t, nullable=True, comment="Cuve concernée (catégorie tank)."),
        sa.Column("description", sa.Text(), nullable=False, comment="Texte libre factuel (3 à 1000 caractères), jamais interprété par le système."),
        sa.Column("importance", sa.String(length=10), server_default="normal", nullable=False, comment="normal | high."),
        sa.Column("status", sa.String(length=10), nullable=True, comment="open_issue seulement : open puis closed ; NULL pour les autres types."),
        sa.Column("closedByUserId", uuid_t, nullable=True, comment="Auteur du règlement de l'anomalie."),
        sa.Column("closedAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage serveur du règlement de l'anomalie."),
        sa.Column("resolution", sa.String(length=500), nullable=True, comment="Comment l'anomalie a été réglée (obligatoire à la clôture)."),
        sa.Column("authorUserId", uuid_t, nullable=False, comment="Auteur de la ligne."),
        sa.Column("authorRole", sa.String(length=30), nullable=False, comment="Rôle de l'auteur à l'écriture : station_admin (gérant/direction) ou shift_manager ; mémorisé pour afficher « consigne du gérant »."),
        sa.Column("declaredAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement de la ligne."),
        sa.Column("addedAfterReceipt", sa.Boolean(), server_default="false", nullable=False, comment="Vrai si ajoutée après la prise de connaissance (affichée « complément »)."),
        sa.Column("changeReason", sa.Text(), nullable=True, comment="Raison d'une correction faite alors que la passation est déjà reçue."),
        sa.ForeignKeyConstraint(["handoverId"], ["zyloLiquidShiftHandover.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["pumpId"], ["zyloLiquidPump.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tankId"], ["zyloLiquidTank.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["closedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind IN ('instruction','open_issue','info')", name="ck_zlShiftHandoverItem_kind"),
        sa.CheckConstraint("category IN ('pump','tank','delivery','price_credit','safety','staff','customer','report_feedback','other')", name="ck_zlShiftHandoverItem_category"),
        sa.CheckConstraint("importance IN ('normal','high')", name="ck_zlShiftHandoverItem_importance"),
        sa.CheckConstraint("\"pumpId\" IS NULL OR category = 'pump'", name="ck_zlShiftHandoverItem_pump_only_category_pump"),
        sa.CheckConstraint("\"tankId\" IS NULL OR category = 'tank'", name="ck_zlShiftHandoverItem_tank_only_category_tank"),
        sa.CheckConstraint("(status IS NOT NULL) = (kind = 'open_issue')", name="ck_zlShiftHandoverItem_status_iff_open_issue"),
        sa.CheckConstraint("status IS NULL OR status IN ('open','closed')", name="ck_zlShiftHandoverItem_status"),
        sa.CheckConstraint("\"closedAt\" IS NULL OR status = 'closed'", name="ck_zlShiftHandoverItem_closed_needs_status"),
        sa.CheckConstraint(
            "status IS DISTINCT FROM 'closed' OR (\"closedAt\" IS NOT NULL AND \"closedByUserId\" IS NOT NULL AND resolution IS NOT NULL)",
            name="ck_zlShiftHandoverItem_closed_needs_resolution",
        ),
        comment="Ligne de passation : consigne, anomalie en cours (niveau station jusqu'à réglée) ou information, écrite par une personne.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftHandoverItem_handoverId"), "zyloLiquidShiftHandoverItem", ["handoverId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftHandoverItem_pumpId"), "zyloLiquidShiftHandoverItem", ["pumpId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftHandoverItem_tankId"), "zyloLiquidShiftHandoverItem", ["tankId"], unique=False)
    op.create_index("ix_zlShiftHandoverItem_open_issues", "zyloLiquidShiftHandoverItem", ["handoverId"], unique=False, postgresql_where=sa.text("status = 'open'"))


def downgrade() -> None:
    op.drop_index("ix_zlShiftHandoverItem_open_issues", table_name="zyloLiquidShiftHandoverItem")
    op.drop_index(op.f("ix_zyloLiquidShiftHandoverItem_tankId"), table_name="zyloLiquidShiftHandoverItem")
    op.drop_index(op.f("ix_zyloLiquidShiftHandoverItem_pumpId"), table_name="zyloLiquidShiftHandoverItem")
    op.drop_index(op.f("ix_zyloLiquidShiftHandoverItem_handoverId"), table_name="zyloLiquidShiftHandoverItem")
    op.drop_table("zyloLiquidShiftHandoverItem")
    op.drop_index(op.f("ix_zyloLiquidShiftHandover_stationId"), table_name="zyloLiquidShiftHandover")
    op.drop_table("zyloLiquidShiftHandover")
    op.drop_index("uq_zlShiftAttendanceLine_sheet_person", table_name="zyloLiquidShiftAttendanceLine")
    op.drop_index(op.f("ix_zyloLiquidShiftAttendanceLine_personUserId"), table_name="zyloLiquidShiftAttendanceLine")
    op.drop_index(op.f("ix_zyloLiquidShiftAttendanceLine_plannedAssignmentId"), table_name="zyloLiquidShiftAttendanceLine")
    op.drop_index(op.f("ix_zyloLiquidShiftAttendanceLine_sheetId"), table_name="zyloLiquidShiftAttendanceLine")
    op.drop_table("zyloLiquidShiftAttendanceLine")
    op.drop_index(op.f("ix_zyloLiquidShiftAttendanceSheet_stationId"), table_name="zyloLiquidShiftAttendanceSheet")
    op.drop_table("zyloLiquidShiftAttendanceSheet")
