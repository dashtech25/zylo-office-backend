"""comptage et remise de caisse par pompiste (D3)

Revision ID: d9e1f3a5b627
Revises: c8d0e2f4a516
Create Date: 2026-10-02

Scénario D3 : trois tables nouvelles (`zyloLiquidShiftReportCashLine` : une ligne par rapport
et par pompiste ; `zyloLiquidShiftReportPumpShare` : répartition MANUELLE et tracée d'une pompe
partagée ; `zyloLiquidShiftReportCashLineCorrection` : historique des ratures) et trois colonnes
sur `zyloLiquidShiftReport` (version du bloc « caisse », dernier enregistrement, auteur).

Migration écrite à la main, après D1 (b7c9d1e3f405) et D2 (c8d0e2f4a516). Aucune donnée créée :
aucune ligne de caisse, répartition ou déduction n'est inventée.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d9e1f3a5b627"
down_revision = "b7c9d1e3f405"
branch_labels = None
depends_on = None

_REPORT = "zyloLiquidShiftReport"
_LINE = "zyloLiquidShiftReportCashLine"
_SHARE = "zyloLiquidShiftReportPumpShare"
_CORRECTION = "zyloLiquidShiftReportCashLineCorrection"


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    # --- Rapport : version du bloc « caisse par pompiste ». ---
    op.add_column(_REPORT, sa.Column("cashVersion", sa.Integer(), server_default="0", nullable=False, comment="Version du bloc « caisse par pompiste » (D3) : 0 tant que rien n'est enregistré, +1 à chaque enregistrement ; verrou optimiste (409 cash_version_changed)."))
    op.add_column(_REPORT, sa.Column("cashLastRecordedAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D3 (nul tant que rien n'est enregistré)."))
    op.add_column(_REPORT, sa.Column("cashLastRecordedByUserId", sa.UUID(), nullable=True, comment="Auteur du dernier enregistrement D3 (RT ou gérant à sa place) ; sert au message de conflit de version."))
    op.create_foreign_key("fk_zlShiftReport_cashLastRecordedBy", _REPORT, "user", ["cashLastRecordedByUserId"], ["id"], ondelete="RESTRICT")

    # --- Ligne de caisse d'un pompiste. ---
    op.create_table(
        _LINE,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("userId", uuid_t, nullable=False, comment="Personne ayant tenu au moins une pompe pendant le tour (chronologie B4/B5)."),
        sa.Column("userNameSnapshot", sa.String(length=200), nullable=False, comment="Nom copié à l'enregistrement : le rapport reste lisible si le personnel change."),
        sa.Column("roleMarker", sa.String(length=15), server_default="attendant", nullable=False, comment="attendant | team_lead (chef d'équipe remplaçant, PC-46/PC-52 : ligne marquée « CE »)."),
        sa.Column("attributedLiters", sa.Numeric(14, 2), nullable=True, comment="Litres vendus attribués au pompiste (règle PC-05) ; nul si une de ses pompes est partagée non répartie."),
        sa.Column("salesValue", sa.Numeric(18, 2), nullable=True, comment="Valeur des ventes attribuées (somme des montants D1 attribués, prix copié) ; nul si non calculable (pompe partagée non répartie, prix absent)."),
        sa.Column("creditVouchersAmount", sa.Numeric(14, 2), server_default="0", nullable=False, comment="Total des bons de crédit signés remis par le pompiste (saisi à la main tant que C2 n'existe pas)."),
        sa.Column("mobilePaymentsAmount", sa.Numeric(14, 2), server_default="0", nullable=False, comment="Total des paiements mobiles encaissés par le pompiste (saisi à la main tant que C3 n'existe pas)."),
        sa.Column("otherDeductionsAmount", sa.Numeric(14, 2), server_default="0", nullable=False, comment="Autres déductions (bons valeur, dépenses autorisées) ; note obligatoire si > 0."),
        sa.Column("otherDeductionsNote", sa.String(length=255), nullable=True, comment="Explication des autres déductions."),
        sa.Column("deductionsSource", sa.String(length=10), server_default="manual", nullable=False, comment="manual (saisie du RT) tant que C2/C3/C5/C9 n'existent pas ; computed ensuite (cellule verrouillée)."),
        sa.Column("theoreticalAmount", sa.Numeric(18, 2), nullable=True, comment="Montant théorique dû = valeur des ventes - déductions ; nul (« non calculé ») si la valeur des ventes est inconnue."),
        sa.Column("attendantCountedAmount", sa.Numeric(14, 2), nullable=False, comment="Espèces comptées par le pompiste."),
        sa.Column("managerRecountedAmount", sa.Numeric(14, 2), nullable=False, comment="Espèces recomptées par le RT devant le pompiste."),
        sa.Column("remittedAmount", sa.Numeric(14, 2), nullable=False, comment="Remis = montant recompté par le RT (ce qu'il a réellement reçu)."),
        sa.Column("countsMatch", sa.Boolean(), nullable=False, comment="Vrai si comptage pompiste = recomptage RT."),
        sa.Column("varianceAmount", sa.Numeric(18, 2), nullable=True, comment="Écart signé = remis - théorique (positif = excédent, négatif = manquant) ; nul si le théorique n'est pas calculé."),
        sa.Column("varianceNature", sa.String(length=10), nullable=True, comment="surplus (> 0) | shortage (< 0) | balanced (= 0) ; nul si non calculé."),
        sa.Column("documentsHandedOver", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="Bons de crédit et notes de paiement mobile physiquement remis (contrôlé en D6)."),
        sa.Column("note", sa.String(length=255), nullable=True, comment="Observation ; obligatoire si les deux comptages diffèrent."),
        sa.Column("basedOnClosingVersion", sa.Integer(), nullable=False, comment="Version de la fermeture des pompes (D1) sur laquelle repose le calcul ; différente de l'actuelle = à recalculer."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi (RT, ou gérant à sa place)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement de la ligne."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["userId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", "userId", name="uq_zlShiftReportCashLine_report_user"),
        sa.CheckConstraint("\"roleMarker\" IN ('attendant','team_lead')", name="ck_zlShiftReportCashLine_roleMarker"),
        sa.CheckConstraint("\"deductionsSource\" IN ('manual','computed')", name="ck_zlShiftReportCashLine_deductionsSource"),
        sa.CheckConstraint("\"varianceNature\" IS NULL OR \"varianceNature\" IN ('surplus','shortage','balanced')", name="ck_zlShiftReportCashLine_varianceNature"),
        sa.CheckConstraint(
            "\"creditVouchersAmount\" >= 0 AND \"mobilePaymentsAmount\" >= 0 AND \"otherDeductionsAmount\" >= 0 AND \"attendantCountedAmount\" >= 0 AND \"managerRecountedAmount\" >= 0",
            name="ck_zlShiftReportCashLine_amounts_nonneg",
        ),
        comment="Caisse d'un pompiste pour un rapport de tour (D3) : ventes attribuées, déductions, comptage pompiste et RT, théorique, remis, écart signé.",
    )
    op.create_index(f"ix_{_LINE}_reportId", _LINE, ["reportId"])
    op.create_index(f"ix_{_LINE}_userId", _LINE, ["userId"])

    # --- Répartition manuelle d'une pompe partagée. ---
    op.create_table(
        _SHARE,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("pumpLineId", uuid_t, nullable=False, comment="Ligne de pompe du rapport."),
        sa.Column("userId", uuid_t, nullable=False, comment="Pompiste ayant tenu cette pompe (chronologie B4/B5)."),
        sa.Column("litersShare", sa.Numeric(14, 2), nullable=False, comment="Litres attribués ; la somme des parts de la pompe égale ses litres vendus (D1)."),
        sa.Column("source", sa.String(length=15), server_default="manual", nullable=False, comment="manual (déclaration du RT) | segment_index (réservé : calculé à la lecture, non stocké)."),
        sa.Column("reason", sa.String(length=255), nullable=True, comment="Comment la répartition a été décidée (10 caractères minimum) ; obligatoire si manual."),
        sa.Column("declaredByUserId", uuid_t, nullable=False, comment="Qui a saisi la répartition."),
        sa.Column("declaredAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la déclaration."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpLineId"], ["zyloLiquidShiftReportPumpLine.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["userId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["declaredByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("pumpLineId", "userId", name="uq_zlShiftReportPumpShare_line_user"),
        sa.CheckConstraint("\"source\" IN ('manual','segment_index')", name="ck_zlShiftReportPumpShare_source"),
        sa.CheckConstraint("\"litersShare\" >= 0", name="ck_zlShiftReportPumpShare_liters_nonneg"),
        comment="Répartition manuelle (déclarée et tracée) des litres d'une pompe partagée entre ses pompistes (D3).",
    )
    op.create_index(f"ix_{_SHARE}_reportId", _SHARE, ["reportId"])
    op.create_index(f"ix_{_SHARE}_pumpLineId", _SHARE, ["pumpLineId"])

    # --- Historique des ratures. ---
    op.create_table(
        _CORRECTION,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("cashLineId", uuid_t, nullable=False, comment="Ligne de caisse corrigée."),
        sa.Column("field", sa.String(length=25), nullable=False, comment="Champ modifié : creditVouchersAmount | mobilePaymentsAmount | otherDeductionsAmount | attendantCountedAmount | managerRecountedAmount."),
        sa.Column("oldValue", sa.Numeric(14, 2), nullable=False, comment="Valeur avant la correction (conservée, jamais écrasée)."),
        sa.Column("newValue", sa.Numeric(14, 2), nullable=False, comment="Valeur après la correction."),
        sa.Column("reasonCode", sa.String(length=20), nullable=False, comment="Motif : count_error | entry_error | voucher_found | index_corrected | other."),
        sa.Column("reasonNote", sa.String(length=255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »)."),
        sa.Column("initialedByUserId", uuid_t, nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif)."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi la correction (RT ou gérant)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction."),
        sa.Column("cashVersion", sa.Integer(), nullable=False, comment="Version du bloc caisse produite par cette correction."),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cashLineId"], [f"{_LINE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initialedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "\"field\" IN ('creditVouchersAmount','mobilePaymentsAmount','otherDeductionsAmount','attendantCountedAmount','managerRecountedAmount')",
            name="ck_zlShiftReportCashLineCorrection_field",
        ),
        sa.CheckConstraint("\"reasonCode\" IN ('count_error','entry_error','voucher_found','index_corrected','other')", name="ck_zlShiftReportCashLineCorrection_reason"),
        comment="Historique des ratures d'une ligne de caisse (comptage, déductions) : ancienne valeur conservée, motif, paraphé par.",
    )
    op.create_index(f"ix_{_CORRECTION}_reportId", _CORRECTION, ["reportId"])
    op.create_index(f"ix_{_CORRECTION}_cashLineId", _CORRECTION, ["cashLineId"])


def downgrade() -> None:
    op.drop_table(_CORRECTION)
    op.drop_table(_SHARE)
    op.drop_table(_LINE)
    op.drop_constraint("fk_zlShiftReport_cashLastRecordedBy", _REPORT, type_="foreignkey")
    op.drop_column(_REPORT, "cashLastRecordedByUserId")
    op.drop_column(_REPORT, "cashLastRecordedAt")
    op.drop_column(_REPORT, "cashVersion")
