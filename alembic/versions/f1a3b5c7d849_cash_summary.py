"""calcul de la caisse A à H et du NOTA (D5) : saisies uniquement

Revision ID: f1a3b5c7d849
Revises: e0f2a4b6c738
Create Date: 2026-10-02

Scénario D5 : trois tables de SAISIES (`zyloLiquidShiftReportCashAdjustment` : règle PC-03 avec motif et version du bloc ;
`zyloLiquidShiftReportExpenseLine` : dépenses diverses saisies ; `zyloLiquidShiftReportSettlementLine` : règlements VAL/CCT, un
`Payment` ne comptant qu'une fois). A, B, C, E, F, H et le NOTA ne sont JAMAIS stockés : recalculés à chaque lecture.
Migration écrite à la main, après D4 (e0f2a4b6c738). Aucune donnée créée.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "f1a3b5c7d849"
down_revision = "e0f2a4b6c738"
branch_labels = None
depends_on = None

_REPORT = "zyloLiquidShiftReport"
_ADJ = "zyloLiquidShiftReportCashAdjustment"
_EXP = "zyloLiquidShiftReportExpenseLine"
_SET = "zyloLiquidShiftReportSettlementLine"


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    op.create_table(
        _ADJ,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("deductRetainedSales", sa.Boolean(), server_default="true", nullable=False, comment="Vrai (défaut) : les ventes de lubrifiants (rubrique 2) et de boutique (rubrique 4) sont comptées comme dépenses diverses (PC-03) ; faux : elles ne le sont plus (motif obligatoire)."),
        sa.Column("deductRetainedSalesNote", sa.String(length=255), nullable=True, comment="Motif de la désactivation de la déduction (10 caractères minimum) ; nul tant que la règle est active."),
        sa.Column("inputsVersion", sa.Integer(), server_default="0", nullable=False, comment="Version du bloc de saisie D5 : +1 à chaque enregistrement ; verrou optimiste (409 cash_inputs_version_changed)."),
        sa.Column("lastRecordedAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D5."),
        sa.Column("lastRecordedByUserId", uuid_t, nullable=True, comment="Auteur du dernier enregistrement D5 (RT ou gérant à sa place) ; sert au message de conflit."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lastRecordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", name="uq_zlShiftReportCashAdjustment_report"),
        sa.CheckConstraint("\"deductRetainedSales\" OR \"deductRetainedSalesNote\" IS NOT NULL", name="ck_zlShiftReportCashAdjustment_note_if_off"),
        comment="Réglages de la caisse d'un rapport de tour (D5) : règle de déduction lubrifiants/boutique (PC-03) avec motif, version du bloc de saisie.",
    )

    op.create_table(
        _EXP,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False, comment="Ordre d'affichage (1, 2, 3…)."),
        sa.Column("label", sa.String(length=150), nullable=False, comment="Libellé de la dépense (carburant du groupe, réparation…)."),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, comment="Montant de la dépense, strictement positif, 2 décimales."),
        sa.Column("receiptReference", sa.String(length=100), nullable=True, comment="N° du reçu / justificatif ; nul seulement si une note explique pourquoi il n'y en a pas."),
        sa.Column("note", sa.String(length=255), nullable=True, comment="Précision ; obligatoire sans justificatif."),
        sa.Column("origin", sa.String(length=10), server_default="manual", nullable=False, comment="manual (saisie du RT) ; réservé C9 (dépense de caisse en cours de tour)."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi la ligne (RT ou gérant à sa place)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'enregistrement."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_zlShiftReportExpenseLine_amount_positive"),
        sa.CheckConstraint("\"receiptReference\" IS NOT NULL OR note IS NOT NULL", name="ck_zlShiftReportExpenseLine_receipt_or_note"),
        comment="Dépense diverse saisie d'un rapport de tour (D5) : libellé, montant > 0, justificatif ou note.",
    )
    op.create_index(f"ix_{_EXP}_reportId", _EXP, ["reportId"])

    op.create_table(
        _SET,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False, comment="Ordre d'affichage (1, 2, 3…)."),
        sa.Column("commercialAccountId", uuid_t, nullable=True, comment="Compte client qui règle ; nul si le payeur est saisi en texte libre."),
        sa.Column("payerLabel", sa.String(length=150), nullable=True, comment="Payeur en texte libre (quand il n'y a pas de compte client)."),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, comment="Montant du règlement, strictement positif, 2 décimales."),
        sa.Column("mode", sa.String(length=15), nullable=False, comment="cash (espèces) | cheque | loading_card (carte de chargement)."),
        sa.Column("reference", sa.String(length=100), nullable=False, comment="Référence : n° de chèque, « PM SCT »…"),
        sa.Column("paymentId", uuid_t, nullable=True, comment="Paiement existant dont la ligne provient (proposition acceptée) ; lu, jamais modifié ; unique : un paiement ne compte qu'une fois."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi la ligne (RT ou gérant à sa place)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de l'enregistrement."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commercialAccountId"], ["zyloLiquidCommercialAccount.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paymentId"], ["zyloLiquidPayment.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("amount > 0", name="ck_zlShiftReportSettlementLine_amount_positive"),
        sa.CheckConstraint("mode IN ('cash','cheque','loading_card')", name="ck_zlShiftReportSettlementLine_mode"),
        sa.CheckConstraint("\"commercialAccountId\" IS NOT NULL OR \"payerLabel\" IS NOT NULL", name="ck_zlShiftReportSettlementLine_payer"),
        comment="Règlement VAL/CCT reçu pendant un tour (D5) : client ou payeur libre, montant, mode, référence, paiement existant éventuel.",
    )
    op.create_index(f"ix_{_SET}_reportId", _SET, ["reportId"])
    op.create_index("uq_zlShiftReportSettlementLine_payment", _SET, ["paymentId"], unique=True, postgresql_where=sa.text("\"paymentId\" IS NOT NULL"))


def downgrade() -> None:
    op.drop_table(_SET)
    op.drop_table(_EXP)
    op.drop_table(_ADJ)
