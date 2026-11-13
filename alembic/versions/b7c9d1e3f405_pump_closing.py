"""index de fermeture des pompes et volumes vendus (D1)

Revision ID: b7c9d1e3f405
Revises: a3e5c7b9d124
Create Date: 2026-10-01

Scénario D1 : colonnes de fermeture ajoutées à `zyloLiquidShiftReportPumpLine`
(lecture à deux, sorties, retours en cuve, événement compteur, litres vendus, prix
copié, montant) et à `zyloLiquidShiftReport` (version du bloc « fermeture des pompes »,
phase de fermeture), plus la table `zyloLiquidShiftReportPumpLineCorrection`
(historique des ratures, jamais d'écrasement silencieux).

`closingIndex` (ligne de pompe) a DÉJÀ été créée par B3 : elle n'est pas recréée ici,
D1 l'écrit. Migration écrite à la main, avant D2 et D3. Aucune donnée créée (jamais
d'index, de prix ni de litres inventés) : toutes les nouvelles colonnes sont nulles
ou prennent une valeur neutre (`counterEvent = 'none'`, `closingVersion = 0`).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b7c9d1e3f405"
down_revision = "a3e5c7b9d124"
branch_labels = None
depends_on = None

_LINE = "zyloLiquidShiftReportPumpLine"
_REPORT = "zyloLiquidShiftReport"
_CORRECTION = "zyloLiquidShiftReportPumpLineCorrection"


def _ts_columns() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    uuid_t = postgresql.UUID(as_uuid=True)

    # --- Rapport : version du bloc « fermeture des pompes » et phase de fermeture. ---
    op.add_column(_REPORT, sa.Column("closingVersion", sa.Integer(), server_default="0", nullable=False, comment="Version du bloc « fermeture des pompes » (D1) : 0 tant que rien n'est enregistré, +1 à chaque enregistrement ; verrou optimiste (409 closing_version_changed) et base de l'état « à recalculer » de D2/D3."))
    op.add_column(_REPORT, sa.Column("closingPhase", sa.String(length=20), server_default="open", nullable=False, comment="open (en cours) | ready_to_close (index de fermeture enregistrés, D1). La fermeture définitive du tour (statut `closed` de l'occurrence) reste D7 : cette phase ne ferme rien."))
    op.add_column(_REPORT, sa.Column("closingLastRecordedAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage serveur du dernier enregistrement D1 (nul tant que rien n'est enregistré)."))
    op.add_column(_REPORT, sa.Column("closingLastRecordedByUserId", sa.UUID(), nullable=True, comment="Auteur du dernier enregistrement D1 (RT ou gérant à sa place)."))
    op.create_foreign_key("fk_zlShiftReport_closingLastRecordedBy", _REPORT, "user", ["closingLastRecordedByUserId"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_zlShiftReport_closingPhase", _REPORT, "\"closingPhase\" IN ('open','ready_to_close')")

    # --- Ligne de pompe : colonnes de fermeture (closingIndex existe déjà, créée par B3). ---
    op.add_column(_LINE, sa.Column("closingReadWithUserId", sa.UUID(), nullable=True, comment="Personne avec qui l'index de fermeture a été lu à deux (pompiste de la pompe ou chef d'équipe) ; déclaratif, jamais une signature."))
    op.add_column(_LINE, sa.Column("closingReadAt", sa.DateTime(timezone=True), nullable=True, comment="Horodatage SERVEUR de l'enregistrement de l'index de fermeture (≠ heure réelle de lecture, jamais prétendu)."))
    op.add_column(_LINE, sa.Column("closingRecordedByUserId", sa.UUID(), nullable=True, comment="Qui a saisi l'index de fermeture (RT ou gérant à sa place)."))
    op.add_column(_LINE, sa.Column("exitsLiters", sa.Numeric(12, 2), nullable=True, comment="Sorties : litres passés dans la pompe sans être vendus (test, étalonnage) ; nul = non déclaré = 0 (méthode PC-04 provisoire)."))
    op.add_column(_LINE, sa.Column("tankReturnLiters", sa.Numeric(12, 2), nullable=True, comment="Retours en cuve : litres remis en cuve (≤ sorties) ; n'agissent que sur le stock (D2), jamais sur les litres vendus (PC-04)."))
    op.add_column(_LINE, sa.Column("exitsNote", sa.String(length=255), nullable=True, comment="Observation des sorties ; obligatoire si les sorties sont > 0."))
    op.add_column(_LINE, sa.Column("counterEvent", sa.String(length=10), server_default="none", nullable=False, comment="none | rollover (compteur remis à zéro après 999 999,99) | replaced (compteur remplacé)."))
    op.add_column(_LINE, sa.Column("counterEventNote", sa.String(length=300), nullable=True, comment="Précision de l'événement compteur (10 caractères minimum) ; obligatoire si counterEvent ≠ none."))
    op.add_column(_LINE, sa.Column("replacedOldFinalIndex", sa.Numeric(14, 2), nullable=True, comment="Dernier index de l'ancien compteur (compteur remplacé seulement)."))
    op.add_column(_LINE, sa.Column("replacedNewStartIndex", sa.Numeric(14, 2), nullable=True, comment="Index de départ du nouveau compteur (compteur remplacé seulement)."))
    op.add_column(_LINE, sa.Column("zeroSaleConfirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="Vrai si le RT a confirmé « pompe sans vente » (fermeture = ouverture) pour cette ligne."))
    op.add_column(_LINE, sa.Column("soldLiters", sa.Numeric(14, 2), nullable=True, comment="Litres vendus CALCULÉS par le serveur : (fermeture - ouverture) - sorties (méthode PC-04 provisoire, formules spéciales si événement compteur) ; nul tant que l'index de fermeture n'est pas saisi."))
    op.add_column(_LINE, sa.Column("unitPriceAmount", sa.Numeric(14, 4), nullable=True, comment="Prix unitaire en vigueur à l'OUVERTURE du tour, COPIÉ à l'enregistrement (changer le prix plus tard n'altère pas le rapport) ; nul = prix non disponible (jamais un prix inventé)."))
    op.add_column(_LINE, sa.Column("unitPriceCurrencyId", sa.UUID(), nullable=True, comment="Devise du prix copié."))
    op.add_column(_LINE, sa.Column("unitPriceEffectiveFrom", sa.DateTime(), nullable=True, comment="Date d'effet du prix retenu (traçabilité, avertissement « prix modifié pendant le tour »)."))
    op.add_column(_LINE, sa.Column("amount", sa.Numeric(18, 2), nullable=True, comment="Montant de la ligne = litres vendus × prix copié, arrondi à 2 décimales ; nul si le prix est non disponible."))
    op.create_foreign_key("fk_zlShiftReportPumpLine_closingReadWith", _LINE, "user", ["closingReadWithUserId"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_zlShiftReportPumpLine_closingRecordedBy", _LINE, "user", ["closingRecordedByUserId"], ["id"], ondelete="RESTRICT")
    op.create_foreign_key("fk_zlShiftReportPumpLine_unitPriceCurrency", _LINE, "currency", ["unitPriceCurrencyId"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_zlShiftReportPumpLine_counterEvent", _LINE, "\"counterEvent\" IN ('none','rollover','replaced')")
    op.create_check_constraint("ck_zlShiftReportPumpLine_exits_nonneg", _LINE, "(\"exitsLiters\" IS NULL OR \"exitsLiters\" >= 0) AND (\"tankReturnLiters\" IS NULL OR \"tankReturnLiters\" >= 0)")

    # --- Historique des ratures. ---
    op.create_table(
        _CORRECTION,
        sa.Column("id", uuid_t, nullable=False),
        *_ts_columns(),
        sa.Column("reportId", uuid_t, nullable=False),
        sa.Column("pumpLineId", uuid_t, nullable=False, comment="Ligne de pompe corrigée."),
        sa.Column("field", sa.String(length=20), nullable=False, comment="Champ modifié : closingIndex | exitsLiters | tankReturnLiters."),
        sa.Column("oldValue", sa.Numeric(14, 2), nullable=True, comment="Valeur avant la correction (conservée, jamais écrasée) ; nulle si le champ n'était pas déclaré."),
        sa.Column("newValue", sa.Numeric(14, 2), nullable=True, comment="Valeur après la correction ; nulle si le champ est vidé."),
        sa.Column("reasonCode", sa.String(length=20), nullable=False, comment="Motif de la liste : read_error | digits_swapped | decimal_forgotten | read_before_end | other."),
        sa.Column("reasonNote", sa.String(length=255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »)."),
        sa.Column("initialedByUserId", uuid_t, nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif, pompiste ou chef d'équipe)."),
        sa.Column("recordedByUserId", uuid_t, nullable=False, comment="Qui a saisi la correction (RT ou gérant)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction."),
        sa.Column("closingVersion", sa.Integer(), nullable=False, comment="Version du bloc « fermeture des pompes » produite par cette correction."),
        sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpLineId"], [f"{_LINE}.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["initialedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("\"field\" IN ('closingIndex','exitsLiters','tankReturnLiters')", name="ck_zlShiftReportPumpLineCorrection_field"),
        sa.CheckConstraint("\"reasonCode\" IN ('read_error','digits_swapped','decimal_forgotten','read_before_end','other')", name="ck_zlShiftReportPumpLineCorrection_reason"),
        comment="Historique des ratures d'une ligne de pompe du rapport (index de fermeture, sorties, retours) : ancienne valeur conservée, motif, paraphé par.",
    )
    op.create_index(op.f("ix_zyloLiquidShiftReportPumpLineCorrection_reportId"), _CORRECTION, ["reportId"], unique=False)
    op.create_index(op.f("ix_zyloLiquidShiftReportPumpLineCorrection_pumpLineId"), _CORRECTION, ["pumpLineId"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_zyloLiquidShiftReportPumpLineCorrection_pumpLineId"), table_name=_CORRECTION)
    op.drop_index(op.f("ix_zyloLiquidShiftReportPumpLineCorrection_reportId"), table_name=_CORRECTION)
    op.drop_table(_CORRECTION)

    op.drop_constraint("ck_zlShiftReportPumpLine_exits_nonneg", _LINE, type_="check")
    op.drop_constraint("ck_zlShiftReportPumpLine_counterEvent", _LINE, type_="check")
    op.drop_constraint("fk_zlShiftReportPumpLine_unitPriceCurrency", _LINE, type_="foreignkey")
    op.drop_constraint("fk_zlShiftReportPumpLine_closingRecordedBy", _LINE, type_="foreignkey")
    op.drop_constraint("fk_zlShiftReportPumpLine_closingReadWith", _LINE, type_="foreignkey")
    for column in (
        "amount", "unitPriceEffectiveFrom", "unitPriceCurrencyId", "unitPriceAmount", "soldLiters", "zeroSaleConfirmed", "replacedNewStartIndex",
        "replacedOldFinalIndex", "counterEventNote", "counterEvent", "exitsNote", "tankReturnLiters", "exitsLiters", "closingRecordedByUserId",
        "closingReadAt", "closingReadWithUserId",
    ):
        op.drop_column(_LINE, column)

    op.drop_constraint("ck_zlShiftReport_closingPhase", _REPORT, type_="check")
    op.drop_constraint("fk_zlShiftReport_closingLastRecordedBy", _REPORT, type_="foreignkey")
    for column in ("closingLastRecordedByUserId", "closingLastRecordedAt", "closingPhase", "closingVersion"):
        op.drop_column(_REPORT, column)
