"""jaugeage des cuves à la fermeture du tour (D2)

Revision ID: c8d0e2f4a516
Revises: b7c9d1e3f405
Create Date: 2026-10-02

Scénario D2 : colonnes ajoutées à `zyloLiquidShiftReportTankLine` (lien vers la
`ManualGaugingDeclaration` courante, copie de la hauteur, heure de mesure, source du stock
réel, référence de la table papier, préleveur/aide, reçu, vendu, sorties nettes, stock
théorique, écart de stock, version D1 de référence, verrou optimiste du jaugeage, auteur
du dernier enregistrement, note d'écart, « paraphé par » de la dernière rature).

`closingRealStockLiters` (stock réel de fermeture) a DÉJÀ été créée par B3 : elle n'est
pas recréée ici, D2 l'écrit. Aucune nouvelle table (l'historique des ratures est la chaîne
`correctsDeclarationId` de `zyloLiquidManualGaugingDeclaration`). Migration écrite à la
main ; D3 (d9e1f3a5b627) s'enchaîne derrière. Aucune donnée créée : toutes les colonnes
sont nulles, sauf `gaugingVersion` (0 = rien d'enregistré).
"""

from alembic import op
import sqlalchemy as sa

revision = "c8d0e2f4a516"
down_revision = "b7c9d1e3f405"
branch_labels = None
depends_on = None

_LINE = "zyloLiquidShiftReportTankLine"


def upgrade() -> None:
    op.add_column(_LINE, sa.Column("gaugingDeclarationId", sa.UUID(), nullable=True, comment="D2 : ManualGaugingDeclaration COURANTE de la cuve pour ce tour (la hauteur, la méthode et le rapprochement restent portés par la déclaration)."))
    op.add_column(_LINE, sa.Column("gaugingHeightMm", sa.Numeric(10, 2), nullable=True, comment="D2 : copie de declaredHeightMm (toujours lue à la règle, même si les litres viennent de la table papier) pour la lecture rapide du rapport."))
    op.add_column(_LINE, sa.Column("gaugedAt", sa.DateTime(timezone=True), nullable=True, comment="D2 : heure de la mesure (UTC) ; = eventAt de la déclaration."))
    op.add_column(_LINE, sa.Column("realStockSource", sa.String(length=20), nullable=True, comment="D2 : calibration_table (hauteur convertie par la table de jaugeage) | paper_table (litres lus sur la table papier, table absente)."))
    op.add_column(_LINE, sa.Column("paperTableReference", sa.String(length=100), nullable=True, comment="D2 : référence du document papier, obligatoire si realStockSource = paper_table."))
    op.add_column(_LINE, sa.Column("measuredByUserId", sa.UUID(), nullable=True, comment="D2 : préleveur (déclaratif)."))
    op.add_column(_LINE, sa.Column("assistedByUserId", sa.UUID(), nullable=True, comment="D2 : aide à la règle (facultatif, déclaratif)."))
    op.add_column(_LINE, sa.Column("receivedLiters", sa.Numeric(12, 2), nullable=True, comment="D2 : litres reçus (réceptions DÉCLARÉES depuis l'ouverture) figés à l'enregistrement ; jamais la télémétrie."))
    op.add_column(_LINE, sa.Column("soldOutLiters", sa.Numeric(14, 2), nullable=True, comment="D2 : litres vendus par les pompes de la cuve (D1) figés à l'enregistrement ; nul si D1 pas encore enregistré."))
    op.add_column(_LINE, sa.Column("nonSaleOutLiters", sa.Numeric(14, 2), nullable=True, comment="D2 : sorties hors vente nettes (somme exits - retours en cuve des pompes, D1) ; nul si D1 pas encore enregistré."))
    op.add_column(_LINE, sa.Column("theoreticalStockLiters", sa.Numeric(14, 2), nullable=True, comment="D2 : ouverture + reçu - vendu - sorties hors vente nettes ; nul tant que D1 n'est pas enregistré (jamais inventé)."))
    op.add_column(_LINE, sa.Column("stockVarianceLiters", sa.Numeric(14, 2), nullable=True, comment="D2 : écart de stock = réel - théorique, signé (positif = excédent, négatif = manquant)."))
    op.add_column(_LINE, sa.Column("basedOnClosingVersion", sa.Integer(), nullable=True, comment="D2 : version de la fermeture des pompes (D1) sur laquelle repose le calcul ; différente de l'actuelle = ligne à recalculer."))
    op.add_column(_LINE, sa.Column("gaugingVersion", sa.Integer(), server_default="0", nullable=False, comment="D2 : verrou optimiste du bloc jaugeage (identique sur toutes les lignes du rapport, incrémenté à chaque enregistrement)."))
    op.add_column(_LINE, sa.Column("gaugingUpdatedByUserId", sa.UUID(), nullable=True, comment="D2 : dernier utilisateur ayant enregistré le jaugeage (message de conflit de version)."))
    op.add_column(_LINE, sa.Column("gaugingUpdatedAt", sa.DateTime(timezone=True), nullable=True, comment="D2 : horodatage (UTC) du dernier enregistrement du jaugeage."))
    op.add_column(_LINE, sa.Column("varianceNote", sa.String(length=255), nullable=True, comment="D2 : explication facultative de l'écart de stock."))
    op.add_column(_LINE, sa.Column("lastCorrectionInitialedByUserId", sa.UUID(), nullable=True, comment="D2 : « paraphé par » de la dernière rature (correction d'une mesure enregistrée)."))

    op.create_foreign_key("fk_zlShiftReportTankLine_gaugingDeclaration", _LINE, "zyloLiquidManualGaugingDeclaration", ["gaugingDeclarationId"], ["id"], ondelete="SET NULL")
    for column, name in (
        ("measuredByUserId", "measuredBy"), ("assistedByUserId", "assistedBy"), ("gaugingUpdatedByUserId", "gaugingUpdatedBy"), ("lastCorrectionInitialedByUserId", "lastCorrectionInitialedBy"),
    ):
        op.create_foreign_key(f"fk_zlShiftReportTankLine_{name}", _LINE, "user", [column], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_zlShiftReportTankLine_realStockSource", _LINE, "\"realStockSource\" IS NULL OR \"realStockSource\" IN ('calibration_table','paper_table')")


def downgrade() -> None:
    op.drop_constraint("ck_zlShiftReportTankLine_realStockSource", _LINE, type_="check")
    for name in ("lastCorrectionInitialedBy", "gaugingUpdatedBy", "assistedBy", "measuredBy"):
        op.drop_constraint(f"fk_zlShiftReportTankLine_{name}", _LINE, type_="foreignkey")
    op.drop_constraint("fk_zlShiftReportTankLine_gaugingDeclaration", _LINE, type_="foreignkey")
    for column in (
        "lastCorrectionInitialedByUserId", "varianceNote", "gaugingUpdatedAt", "gaugingUpdatedByUserId", "gaugingVersion", "basedOnClosingVersion", "stockVarianceLiters",
        "theoreticalStockLiters", "nonSaleOutLiters", "soldOutLiters", "receivedLiters", "assistedByUserId", "measuredByUserId", "paperTableReference", "realStockSource",
        "gaugedAt", "gaugingHeightMm", "gaugingDeclarationId",
    ):
        op.drop_column(_LINE, column)
