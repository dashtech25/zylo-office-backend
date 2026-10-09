"""rubriques 2 à 7 du rapport de tour (D4)

Revision ID: e0f2a4b6c738
Revises: d9e1f3a5b627
Create Date: 2026-10-02

Scénario D4 : huit tables nouvelles. `zyloLiquidShiftReportSection` (état, mode de détail, total calculé, version de chaque rubrique 2 à 7),
une table de lignes par rubrique (lubrifiants, gaz, boutique, crédits clients, bons valeur, paiements électroniques) et
`zyloLiquidShiftReportSectionCorrection` (ratures paraphées). Migration écrite à la main, après D3 (d9e1f3a5b627). Aucune donnée créée :
aucune ligne, aucun prix, aucun client, aucun code de paiement n'est inventé. `saleId`/`receivableId` des bons de crédit sont réservés à E7.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "e0f2a4b6c738"
down_revision = "d9e1f3a5b627"
branch_labels = None
depends_on = None

_REPORT = "zyloLiquidShiftReport"
_SECTION = "zyloLiquidShiftReportSection"
_LUB = "zyloLiquidShiftReportLubricantLine"
_GAS = "zyloLiquidShiftReportGasLine"
_SHOP = "zyloLiquidShiftReportShopLine"
_CREDIT = "zyloLiquidShiftReportCreditVoucher"
_VALUE = "zyloLiquidShiftReportValueVoucherLine"
_ELEC = "zyloLiquidShiftReportElectronicPayment"
_CORR = "zyloLiquidShiftReportSectionCorrection"


def _ts() -> list:
    return [
        sa.Column("createdAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updatedAt", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    u = postgresql.UUID(as_uuid=True)

    def report_fk(on_delete: str):
        return sa.ForeignKeyConstraint(["reportId"], [f"{_REPORT}.id"], ondelete=on_delete)

    # --- État d'une rubrique. ---
    op.create_table(
        _SECTION,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("sectionNumber", sa.SmallInteger(), nullable=False, comment="Numéro de rubrique du rapport : 2 lubrifiants, 3 gaz, 4 boutique, 5 crédits clients, 6 bons valeur, 7 paiements électroniques."),
        sa.Column("status", sa.String(length=15), server_default="not_started", nullable=False, comment="not_started | saved (enregistrée, modifiable jusqu'à D7) | ras (barrée « rien à signaler », aucune ligne)."),
        sa.Column("rasNote", sa.String(length=255), nullable=True, comment="Remarque facultative saisie en barrant la rubrique RAS."),
        sa.Column("detailMode", sa.String(length=10), nullable=True, comment="Rubriques 4 et 7 : detailed (par catégorie / un paiement par ligne) | summary (« sans détail » / cumul par opérateur) ; nul ailleurs."),
        sa.Column("totalAmount", sa.Numeric(18, 2), server_default="0", nullable=False, comment="Total de la rubrique CALCULÉ par le serveur (somme des montants de lignes), recopié pour D5 ; jamais saisi."),
        sa.Column("orangeBalance", sa.Numeric(14, 2), nullable=True, comment="Rubrique 7 : solde du compte Orange Money noté en en-tête du papier ; informatif, jamais utilisé dans un calcul."),
        sa.Column("mtnBalance", sa.Numeric(14, 2), nullable=True, comment="Rubrique 7 : solde du compte MTN Mobile Money noté en en-tête du papier ; informatif, jamais utilisé dans un calcul."),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False, comment="Version de la rubrique : 1 au premier enregistrement, +1 ensuite ; verrou optimiste (409 shift_report_sections_version_changed)."),
        sa.Column("savedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur du dernier enregistrement."),
        sa.Column("savedByUserId", u, nullable=False, comment="Auteur du dernier enregistrement (RT ou gérant à sa place)."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.ForeignKeyConstraint(["savedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", "sectionNumber", name="uq_zlShiftReportSection_report_number"),
        sa.CheckConstraint("\"sectionNumber\" BETWEEN 2 AND 7", name="ck_zlShiftReportSection_number"),
        sa.CheckConstraint("status IN ('not_started','saved','ras')", name="ck_zlShiftReportSection_status"),
        sa.CheckConstraint("\"detailMode\" IS NULL OR \"detailMode\" IN ('detailed','summary')", name="ck_zlShiftReportSection_detailMode"),
        comment="État d'une rubrique 2 à 7 d'un rapport de tour (D4) : statut, mode de détail, total calculé, version (verrou optimiste).",
    )
    op.create_index(f"ix_{_SECTION}_reportId", _SECTION, ["reportId"])

    # --- Rubrique 2 : lubrifiants. ---
    op.create_table(
        _LUB,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("lineNumber", sa.SmallInteger(), nullable=False, comment="Position de la ligne dans le tableau."),
        sa.Column("lineKey", sa.String(length=220), nullable=False, comment="Identité de la ligne dans le rapport : p:<id produit> (catalogue) ou d:<désignation normalisée> (hors catalogue)."),
        sa.Column("sellableProductId", u, nullable=True, comment="Produit vendable du catalogue ; nul = référence hors catalogue (avertissement D6)."),
        sa.Column("designation", sa.String(length=200), nullable=False, comment="Désignation COPIÉE (instantané) : le rapport reste lisible si le catalogue change."),
        sa.Column("openingQty", sa.Numeric(14, 2), nullable=False, comment="Stock d'ouverture déclaré (jamais lu dans SellableProduct.stockQuantity, stock vif non fiable pour cette déclaration)."),
        sa.Column("openingSource", sa.String(length=20), nullable=False, comment="carried (fermeture du rapport précédent) | initial (première fois, saisi) | continuity_break (écart déclaré avec motif)."),
        sa.Column("openingNote", sa.String(length=300), nullable=True, comment="Motif de l'écart avec la fermeture précédente (10 caractères minimum)."),
        sa.Column("previousLineId", u, nullable=True, comment="Ligne du rapport précédent dont la fermeture a été reportée (traçabilité)."),
        sa.Column("entryQty", sa.Numeric(14, 2), server_default="0", nullable=False, comment="Entrées du tour ; vide = 0."),
        sa.Column("soldQty", sa.Numeric(14, 2), nullable=False, comment="Quantités vendues pendant le tour (≤ ouverture + entrées)."),
        sa.Column("closingQty", sa.Numeric(14, 2), nullable=False, comment="Fermeture CALCULÉE = ouverture + entrées - ventes."),
        sa.Column("countedQty", sa.Numeric(14, 2), nullable=True, comment="Stock physiquement compté (facultatif) ; l'écart avec la fermeture est un avertissement D6."),
        sa.Column("unitPriceAmount", sa.Numeric(14, 4), nullable=True, comment="Prix unitaire figé : prix en vigueur à l'ouverture du tour (catalogue) ou saisi (hors catalogue) ; nul = prix non disponible, jamais inventé."),
        sa.Column("unitPriceSource", sa.String(length=10), nullable=True, comment="catalogue | manual (« prix saisi »)."),
        sa.Column("unitPriceCurrencyId", u, nullable=True, comment="Devise du prix catalogue ; nulle pour un prix saisi."),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True, comment="Montant = ventes x prix arrondi à 2 décimales ; nul si le prix est indisponible."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.ForeignKeyConstraint(["sellableProductId"], ["zyloLiquidSellableProduct.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previousLineId"], [f"{_LUB}.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["unitPriceCurrencyId"], ["currency.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", "lineKey", name="uq_zlShiftReportLubricantLine_report_key"),
        sa.CheckConstraint("\"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportLubricantLine_openingSource"),
        sa.CheckConstraint("\"unitPriceSource\" IS NULL OR \"unitPriceSource\" IN ('catalogue','manual')", name="ck_zlShiftReportLubricantLine_priceSource"),
        sa.CheckConstraint("\"openingQty\" >= 0 AND \"entryQty\" >= 0 AND \"soldQty\" >= 0 AND \"closingQty\" >= 0", name="ck_zlShiftReportLubricantLine_qty_nonneg"),
        comment="Rubrique 2 du rapport de tour : une ligne par référence de lubrifiant (ouverture, entrée, ventes, fermeture, prix, montant).",
    )
    op.create_index(f"ix_{_LUB}_reportId", _LUB, ["reportId"])

    # --- Rubrique 3 : gaz. ---
    op.create_table(
        _GAS,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("sizeKg", sa.Numeric(5, 1), nullable=False, comment="Taille de la bouteille en kg : 6, 12.5, 26 ou 35 (tailles par défaut tant qu'aucun catalogue gaz n'existe, A3)."),
        sa.Column("lineKind", sa.String(length=20), nullable=False, comment="bottle (bouteille) | deposit (consignation) | deposit_refund (déconsignation, montant négatif)."),
        sa.Column("openingQty", sa.Integer(), nullable=True, comment="Bouteilles : stock d'ouverture (reporté du rapport précédent ou saisi) ; nul pour consignation/déconsignation."),
        sa.Column("openingSource", sa.String(length=20), nullable=True, comment="carried | initial | continuity_break (bouteilles seulement)."),
        sa.Column("openingNote", sa.String(length=300), nullable=True, comment="Motif de l'écart avec la fermeture précédente (10 caractères minimum)."),
        sa.Column("previousLineId", u, nullable=True, comment="Ligne du rapport précédent dont la fermeture a été reportée."),
        sa.Column("entryQty", sa.Integer(), nullable=True, comment="Bouteilles : entrées du tour ; nul pour consignation/déconsignation."),
        sa.Column("soldQty", sa.Integer(), nullable=False, comment="Quantité vendue (bouteilles), consignées ou déconsignées pendant le tour."),
        sa.Column("closingQty", sa.Integer(), nullable=True, comment="Bouteilles : fermeture CALCULÉE = ouverture + entrées - ventes."),
        sa.Column("unitPriceAmount", sa.Numeric(14, 4), nullable=True, comment="Prix unitaire SAISI par le RT (aucun catalogue gaz en base : jamais de prix inventé)."),
        sa.Column("amount", sa.Numeric(18, 2), nullable=True, comment="Montant CALCULÉ = quantité x prix ; négatif pour la déconsignation."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.ForeignKeyConstraint(["previousLineId"], [f"{_GAS}.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("reportId", "sizeKg", "lineKind", name="uq_zlShiftReportGasLine_report_size_kind"),
        sa.CheckConstraint("\"lineKind\" IN ('bottle','deposit','deposit_refund')", name="ck_zlShiftReportGasLine_lineKind"),
        sa.CheckConstraint("\"openingSource\" IS NULL OR \"openingSource\" IN ('carried','initial','continuity_break')", name="ck_zlShiftReportGasLine_openingSource"),
        sa.CheckConstraint("\"soldQty\" >= 0 AND (\"openingQty\" IS NULL OR \"openingQty\" >= 0) AND (\"entryQty\" IS NULL OR \"entryQty\" >= 0) AND (\"closingQty\" IS NULL OR \"closingQty\" >= 0)", name="ck_zlShiftReportGasLine_qty_nonneg"),
        comment="Rubrique 3 du rapport de tour : gaz domestique par taille de bouteille (bouteille, consignation, déconsignation).",
    )
    op.create_index(f"ix_{_GAS}_reportId", _GAS, ["reportId"])

    # --- Rubrique 4 : boutique. ---
    op.create_table(
        _SHOP,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("categoryCode", sa.String(length=30), nullable=False, comment="Code de catégorie de l'imprimé (telecards, insecticides, alcoholic_drinks…) ou `total` (mode sans détail)."),
        sa.Column("categoryLabel", sa.String(length=100), nullable=False, comment="Libellé français copié (instantané)."),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, comment="Montant déclaré de la catégorie (≥ 0, 2 décimales)."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.UniqueConstraint("reportId", "categoryCode", name="uq_zlShiftReportShopLine_report_category"),
        sa.CheckConstraint("amount >= 0", name="ck_zlShiftReportShopLine_amount_nonneg"),
        comment="Rubrique 4 du rapport de tour : ventes boutique par catégorie, ou total sans détail.",
    )
    op.create_index(f"ix_{_SHOP}_reportId", _SHOP, ["reportId"])

    # --- Rubrique 5 : bons de crédit clients. ---
    op.create_table(
        _CREDIT,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("stationId", u, nullable=False, comment="Station du rapport (copie) : le numéro de bon est unique par station."),
        sa.Column("lineNumber", sa.SmallInteger(), nullable=False, comment="Position de la ligne dans le tableau."),
        sa.Column("voucherNumber", sa.String(length=30), nullable=False, comment="Numéro imprimé sur le bon ; unique par station, tous rapports confondus."),
        sa.Column("commercialAccountId", u, nullable=False, comment="Compte client à crédit existant et actif (jamais de texte libre)."),
        sa.Column("accountNameSnapshot", sa.String(length=150), nullable=False, comment="Nom du compte copié : le rapport reste lisible si la fiche change."),
        sa.Column("vehicleId", u, nullable=True, comment="Véhicule de la fiche du compte ; nul si plaque en texte libre."),
        sa.Column("plateText", sa.String(length=50), nullable=True, comment="Plaque : plaque de la fiche (copie) ou texte libre SIGNALÉ en D6 (jamais ajouté à la fiche)."),
        sa.Column("driverId", u, nullable=True, comment="Chauffeur de la fiche (jamais un utilisateur Zylo) ; nul si texte libre."),
        sa.Column("driverNameText", sa.String(length=150), nullable=True, comment="Nom du chauffeur : fiche (copie) ou texte libre signalé en D6."),
        sa.Column("fuelProductId", u, nullable=False, comment="Produit carburant ; doit être celui de la cuve de la pompe indiquée."),
        sa.Column("fuelProductName", sa.String(length=100), nullable=False, comment="Nom du produit copié (instantané)."),
        sa.Column("pumpLineId", u, nullable=False, comment="Pompe qui a servi le bon (ligne de pompe du rapport) : nécessaire à D3 (crédits servis par pompiste)."),
        sa.Column("quantityLiters", sa.Numeric(14, 2), nullable=False, comment="Litres servis (> 0, 2 décimales)."),
        sa.Column("unitPriceAmount", sa.Numeric(14, 4), nullable=True, comment="Prix en vigueur à l'OUVERTURE du tour, figé à la première écriture ; nul = prix non disponible (jamais inventé)."),
        sa.Column("voucherAmount", sa.Numeric(18, 2), nullable=False, comment="Montant INSCRIT sur le bon (> 0) : c'est lui qui est cumulé ; un écart avec quantité x prix est un avertissement, jamais un blocage."),
        sa.Column("servedAt", sa.DateTime(timezone=False), nullable=False, comment="Date et heure du bon, heure locale de la station."),
        sa.Column("signedConfirmed", sa.Boolean(), server_default=sa.text("false"), nullable=False, comment="« Bon signé en main » : le RT atteste détenir le bon papier signé (déclaratif, audité) ; faux bloque D6 et D7."),
        sa.Column("note", sa.String(length=255), nullable=True, comment="Observation (exigée en D6 si écart de montant ou plaque/chauffeur hors fiche)."),
        sa.Column("saleId", u, nullable=True, comment="RÉSERVÉ à E7 : vente à crédit créée au report sur la fiche client ; nul en D4."),
        sa.Column("receivableId", u, nullable=True, comment="RÉSERVÉ à E7 : créance créée au report ; nul en D4."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commercialAccountId"], ["zyloLiquidCommercialAccount.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["vehicleId"], ["zyloLiquidVehicle.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["driverId"], ["zyloLiquidDriver.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["fuelProductId"], ["zyloLiquidFuelProduct.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpLineId"], ["zyloLiquidShiftReportPumpLine.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["saleId"], ["zyloLiquidSale.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["receivableId"], ["zyloLiquidReceivable.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", "voucherNumber", name="uq_zlShiftReportCreditVoucher_report_number"),
        sa.CheckConstraint("\"quantityLiters\" > 0 AND \"voucherAmount\" > 0", name="ck_zlShiftReportCreditVoucher_positive"),
        comment="Rubrique 5 du rapport de tour : un bon de crédit client par ligne (client, produit, pompe, quantité, montant, plaque, chauffeur, signature déclarée).",
    )
    op.create_index(f"ix_{_CREDIT}_reportId", _CREDIT, ["reportId"])
    op.create_index(f"ix_{_CREDIT}_commercialAccountId", _CREDIT, ["commercialAccountId"])
    op.create_index(f"ix_{_CREDIT}_pumpLineId", _CREDIT, ["pumpLineId"])
    op.create_index("uq_zlShiftReportCreditVoucher_station_number", _CREDIT, ["stationId", "voucherNumber"], unique=True)

    # --- Rubrique 6 : bons valeur. ---
    op.create_table(
        _VALUE,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("denomination", sa.Integer(), nullable=False, comment="Valeur d'un bon (10000, 5000 ou 3000)."),
        sa.Column("voucherColumn", sa.String(length=10), nullable=False, comment="daily (a : bons du jour) | value (c : bons en valeur)."),
        sa.Column("voucherCount", sa.Integer(), nullable=False, comment="Nombre de bons (entier > 0)."),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, comment="Montant CALCULÉ = nombre x coupure."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.UniqueConstraint("reportId", "denomination", "voucherColumn", name="uq_zlShiftReportValueVoucherLine_report_denom_col"),
        sa.CheckConstraint("\"voucherColumn\" IN ('daily','value')", name="ck_zlShiftReportValueVoucherLine_column"),
        sa.CheckConstraint("\"voucherCount\" > 0", name="ck_zlShiftReportValueVoucherLine_count_positive"),
        comment="Rubrique 6 du rapport de tour : nombre de bons valeur par coupure et par colonne (du jour / en valeur).",
    )
    op.create_index(f"ix_{_VALUE}_reportId", _VALUE, ["reportId"])

    # --- Rubrique 7 : paiements électroniques. ---
    op.create_table(
        _ELEC,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("stationId", u, nullable=False, comment="Station du rapport (copie) : un code de paiement est unique par station et par opérateur."),
        sa.Column("lineNumber", sa.SmallInteger(), nullable=False, comment="Position de la ligne dans le tableau."),
        sa.Column("lineKey", sa.String(length=80), nullable=False, comment="Identité de la ligne : tomcard | <opérateur>:<code> (détail) | <opérateur>:summary (cumul)."),
        sa.Column("kind", sa.String(length=10), nullable=False, comment="tomcard (Tomcard / E-Pay Box) | mobile (mobile money)."),
        sa.Column("operator", sa.String(length=15), nullable=True, comment="orange_money | mtn_momo (paiements mobile money seulement)."),
        sa.Column("cardCount", sa.Integer(), nullable=True, comment="Tomcard : nombre de cartes ; nul sinon."),
        sa.Column("ticketCount", sa.Integer(), nullable=True, comment="Tomcard : nombre de tickets ; nul sinon."),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, comment="Montant de la ligne (≥ 0, 2 décimales)."),
        sa.Column("transactionCode", sa.String(length=40), nullable=True, comment="Code du paiement mobile (majuscules) : obligatoire en mode détail, unique par station et opérateur ; nul en mode cumul."),
        sa.Column("origin", sa.String(length=10), nullable=True, comment="Origine d'un paiement mobile en mode détail : pump (reçu à une pompe) | shop (boutique) | other ; nulle en mode cumul et pour Tomcard. La pompe n'est obligatoire que si origin = pump."),
        sa.Column("pumpLineId", u, nullable=True, comment="Pompe qui a reçu le paiement (obligatoire si origin = pump, nulle sinon) : sert à D3 (paiements mobiles par pompiste)."),
        sa.Column("receivedAt", sa.DateTime(timezone=False), nullable=True, comment="Heure du paiement, heure locale de la station (facultative)."),
        sa.PrimaryKeyConstraint("id"), report_fk("CASCADE"),
        sa.ForeignKeyConstraint(["stationId"], ["zyloLiquidStation.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pumpLineId"], ["zyloLiquidShiftReportPumpLine.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("reportId", "lineKey", name="uq_zlShiftReportElectronicPayment_report_key"),
        sa.CheckConstraint("kind IN ('tomcard','mobile')", name="ck_zlShiftReportElectronicPayment_kind"),
        sa.CheckConstraint("operator IS NULL OR operator IN ('orange_money','mtn_momo')", name="ck_zlShiftReportElectronicPayment_operator"),
        sa.CheckConstraint("(kind = 'mobile') = (operator IS NOT NULL)", name="ck_zlShiftReportElectronicPayment_operator_iff_mobile"),
        sa.CheckConstraint("amount >= 0", name="ck_zlShiftReportElectronicPayment_amount_nonneg"),
        sa.CheckConstraint("origin IS NULL OR origin IN ('pump','shop','other')", name="ck_zlShiftReportElectronicPayment_origin"),
        sa.CheckConstraint("COALESCE(origin, '') = 'pump' OR \"pumpLineId\" IS NULL", name="ck_zlShiftReportElectronicPayment_pump_only_if_origin_pump"),
        comment="Rubrique 7 du rapport de tour : Tomcard / E-Pay Box et paiements Orange Money / MTN Mobile Money.",
    )
    op.create_index(f"ix_{_ELEC}_reportId", _ELEC, ["reportId"])
    op.create_index(f"ix_{_ELEC}_pumpLineId", _ELEC, ["pumpLineId"])
    op.create_index(
        "uq_zlShiftReportElectronicPayment_station_operator_code", _ELEC, ["stationId", "operator", "transactionCode"],
        unique=True, postgresql_where=sa.text('"transactionCode" IS NOT NULL'),
    )

    # --- Ratures paraphées. ---
    op.create_table(
        _CORR,
        sa.Column("id", u, nullable=False), *_ts(),
        sa.Column("reportId", u, nullable=False),
        sa.Column("sectionNumber", sa.SmallInteger(), nullable=False, comment="Rubrique corrigée (2 à 7)."),
        sa.Column("lineKey", sa.String(length=220), nullable=False, comment="Identité de la ligne corrigée (voir la table de la rubrique)."),
        sa.Column("field", sa.String(length=40), nullable=False, comment="Champ modifié, ou `line` pour une ligne retirée."),
        sa.Column("oldValue", sa.String(length=300), nullable=True, comment="Valeur avant la correction (texte, conservée) ; nulle si le champ était vide."),
        sa.Column("newValue", sa.String(length=300), nullable=True, comment="Valeur après la correction ; nulle si le champ est vidé ou la ligne retirée."),
        sa.Column("reasonCode", sa.String(length=20), nullable=False, comment="Motif : entry_error | count_error | voucher_found | price_corrected | other."),
        sa.Column("reasonNote", sa.String(length=255), nullable=True, comment="Précision du motif (10 caractères minimum si « other »)."),
        sa.Column("initialedByUserId", u, nullable=False, comment="« Paraphé par » : personne qui a confirmé la correction (déclaratif)."),
        sa.Column("recordedByUserId", u, nullable=False, comment="Qui a saisi la correction (RT ou gérant)."),
        sa.Column("recordedAt", sa.DateTime(timezone=True), nullable=False, comment="Horodatage serveur de la correction."),
        sa.Column("sectionVersion", sa.Integer(), nullable=False, comment="Version de la rubrique produite par cette correction."),
        sa.PrimaryKeyConstraint("id"), report_fk("RESTRICT"),
        sa.ForeignKeyConstraint(["initialedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["recordedByUserId"], ["user.id"], ondelete="RESTRICT"),
        sa.CheckConstraint("\"sectionNumber\" BETWEEN 2 AND 7", name="ck_zlShiftReportSectionCorrection_number"),
        sa.CheckConstraint("\"reasonCode\" IN ('entry_error','count_error','voucher_found','price_corrected','other')", name="ck_zlShiftReportSectionCorrection_reason"),
        comment="Historique des ratures des rubriques 2 à 7 du rapport de tour : ancienne valeur conservée, motif, paraphé par.",
    )
    op.create_index(f"ix_{_CORR}_reportId", _CORR, ["reportId"])


def downgrade() -> None:
    op.drop_table(_CORR)
    op.drop_table(_ELEC)
    op.drop_table(_VALUE)
    op.drop_table(_CREDIT)
    op.drop_table(_SHOP)
    op.drop_table(_GAS)
    op.drop_table(_LUB)
    op.drop_table(_SECTION)
