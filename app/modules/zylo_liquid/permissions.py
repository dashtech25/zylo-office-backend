"""Permissions déclarées par le module zylo_liquid — un fichier dédié par
domaine, jamais une déclaration centralisée (convention actée en Phase 5-6,
reprise de app/identity/permissions.py)."""

FUEL_PRODUCT_READ = "zyloLiquid.fuelProduct.read"
FUEL_PRODUCT_MANAGE = "zyloLiquid.fuelProduct.manage"

STATION_FUEL_PRODUCT_READ = "zyloLiquid.stationFuelProduct.read"
STATION_FUEL_PRODUCT_MANAGE = "zyloLiquid.stationFuelProduct.manage"

STATION_READ = "zyloLiquid.station.read"
STATION_MANAGE = "zyloLiquid.station.manage"

TANK_READ = "zyloLiquid.tank.read"
TANK_MANAGE = "zyloLiquid.tank.manage"

PUMP_READ = "zyloLiquid.pump.read"
PUMP_MANAGE = "zyloLiquid.pump.manage"

TANK_SENSOR_MAPPING_READ = "zyloLiquid.tankSensorMapping.read"
TANK_SENSOR_MAPPING_MANAGE = "zyloLiquid.tankSensorMapping.manage"

TANK_CALIBRATION_READ = "zyloLiquid.tankCalibration.read"
TANK_CALIBRATION_MANAGE = "zyloLiquid.tankCalibration.manage"

HOLYKELL_ACCOUNT_READ = "zyloLiquid.holykellAccount.read"

DELIVERY_READ = "zyloLiquid.delivery.read"

LEAK_EVENT_READ = "zyloLiquid.leakEvent.read"

# ALERT_READ / ALERT_ACKNOWLEDGE / ALERT_MANAGE — déplacées vers
# `app/alerts/permissions.py` (2026-09-15, Phase 3), mêmes valeurs de
# chaîne (déjà seedées en base, jamais renommées par ce déplacement).

PRICE_HISTORY_READ = "zyloLiquid.priceHistory.read"
# La correction (PATCH) exige la même permission que la création (POST) —
# qui peut corriger un prix historique déjà écoulé n'est pas tranché
# (niveau_1_base_de_donnees_et_monetisation.md §27, Point 2 §7.4) ; en
# attendant, option la plus restrictive par défaut, jamais une permission
# distincte plus permissive par supposition.
PRICE_HISTORY_CREATE = "zyloLiquid.priceHistory.create"

CASH_READ = "zyloLiquid.cash.read"

# Couche déclarative (processus-double-sources-verite, Phase 7 §2 de
# 07-formalisation-technique.md) : verbe `create` plutôt que `manage`, même
# raisonnement déjà appliqué à PRICE_HISTORY_CREATE — une correction est
# toujours une nouvelle ligne (Phase 5 §3), jamais une réécriture.
DELIVERY_DECLARATION_READ = "zyloLiquid.deliveryDeclaration.read"
DELIVERY_DECLARATION_CREATE = "zyloLiquid.deliveryDeclaration.create"

SHIFT_CASH_DECLARATION_READ = "zyloLiquid.shiftCashDeclaration.read"
SHIFT_CASH_DECLARATION_CREATE = "zyloLiquid.shiftCashDeclaration.create"

MANUAL_GAUGING_DECLARATION_READ = "zyloLiquid.manualGaugingDeclaration.read"
MANUAL_GAUGING_DECLARATION_CREATE = "zyloLiquid.manualGaugingDeclaration.create"

QUALITY_CHECK_DECLARATION_READ = "zyloLiquid.qualityCheckDeclaration.read"
QUALITY_CHECK_DECLARATION_CREATE = "zyloLiquid.qualityCheckDeclaration.create"

LEAK_TEST_DECLARATION_READ = "zyloLiquid.leakTestDeclaration.read"
LEAK_TEST_DECLARATION_CREATE = "zyloLiquid.leakTestDeclaration.create"

INCIDENT_DECLARATION_READ = "zyloLiquid.incidentDeclaration.read"
INCIDENT_DECLARATION_CREATE = "zyloLiquid.incidentDeclaration.create"

# Transversale aux 6 types de déclaration (Phase 7 §2) : verrouiller est la
# même action quel que soit le type, jamais six permissions distinctes.
DECLARATION_LOCK = "zyloLiquid.declaration.lock"

# Couche Commercial (Phase 7 §2) — portée organisation entière, sauf SALE_*
# qui reste scopée station (comme les entités déclaratives, une vente a
# toujours lieu dans une station précise).
COMMERCIAL_ACCOUNT_READ = "zyloLiquid.commercialAccount.read"
COMMERCIAL_ACCOUNT_MANAGE = "zyloLiquid.commercialAccount.manage"

SALE_READ = "zyloLiquid.sale.read"
SALE_CREATE = "zyloLiquid.sale.create"

RECEIVABLE_READ = "zyloLiquid.receivable.read"
RECEIVABLE_MANAGE = "zyloLiquid.receivable.manage"

PAYMENT_READ = "zyloLiquid.payment.read"
PAYMENT_CREATE = "zyloLiquid.payment.create"

# Modèle documentaire — déplacé vers `app/files/permissions.py`
# (2026-09-15, Phase 1). DOCUMENT_READ/CREATE/MANAGE/DELETE/READ_SENSITIVE
# vivent maintenant là-bas, mêmes valeurs de chaîne.

# Rapprochement (Phase 6, Phase 7 §2) — RECONCILIATION_READ scopé station
# pour les types opérationnels comme les autres déclarations ; les
# tolérances par station restent une gestion de gérant.
RECONCILIATION_READ = "zyloLiquid.reconciliation.read"
RECONCILIATION_SETTINGS_MANAGE = "zyloLiquid.reconciliationSettings.manage"

# Couche Approvisionnement (fusion prototype #/livraisons avec la couche
# réelle — décision commanditaire « créer toutes les tables nécessaires,
# même fournisseur »). Fournisseur/transporteur/camion : référentiels réseau,
# portée organisation entière comme CommercialAccount. Commande
# d'approvisionnement : portée station comme les entités déclaratives.
SUPPLIER_READ = "zyloLiquid.supplier.read"
SUPPLIER_MANAGE = "zyloLiquid.supplier.manage"

CARRIER_READ = "zyloLiquid.carrier.read"
CARRIER_MANAGE = "zyloLiquid.carrier.manage"

TRUCK_READ = "zyloLiquid.truck.read"
TRUCK_MANAGE = "zyloLiquid.truck.manage"

# Boîtiers GPS/tracking — déplacé vers `app/location/permissions.py`
# (2026-09-15, Phase 2). GPS_DEVICE_READ/MANAGE, TRACKING_LOCATION_READ/
# MANAGE, TRACKING_SETTINGS_MANAGE, TRACCAR_CONNECTION_MANAGE vivent
# maintenant là-bas, mêmes valeurs de chaîne. La lecture des positions/
# arrêts reste protégée par TRUCK_READ ci-dessus (pas de permission
# dédiée, éviter la prolifération).

PURCHASE_ORDER_READ = "zyloLiquid.purchaseOrder.read"
PURCHASE_ORDER_MANAGE = "zyloLiquid.purchaseOrder.manage"

# ================================================================
# Centre administratif et opérationnel de la station — domaines Sécurité,
# Fournisseurs (par station) et Finances, absents jusqu'ici de tout modèle
# (audit fait avant d'écrire une ligne de code, voir le plan de mission).
# ================================================================

SECURITY_EQUIPMENT_READ = "zyloLiquid.securityEquipment.read"
SECURITY_EQUIPMENT_MANAGE = "zyloLiquid.securityEquipment.manage"

# Portée station (StationSupplier) — distincte de SUPPLIER_READ/MANAGE
# ci-dessus, qui porte sur le référentiel réseau.
STATION_SUPPLIER_READ = "zyloLiquid.stationSupplier.read"
STATION_SUPPLIER_MANAGE = "zyloLiquid.stationSupplier.manage"

# Même principe que PRICE_HISTORY_READ : une permission dédiée pour un champ
# sensible (bankAccountInfo), distincte de STATION_READ général.
STATION_FINANCIAL_READ = "zyloLiquid.stationFinancial.read"
STATION_FINANCIAL_MANAGE = "zyloLiquid.stationFinancial.manage"

# Module Personnel — création de compte + profil de poste pour un membre du
# personnel d'une station (mockup emalioration/personnel/).
STATION_STAFF_READ = "zyloLiquid.stationStaff.read"
STATION_STAFF_MANAGE = "zyloLiquid.stationStaff.manage"

# Page Exploitation (Centre administratif de la station) — catalogue de
# services et politique commerciale par produit. Les seuils de réassort
# vivent sur StationFuelProduct, gardés par STATION_FUEL_PRODUCT_READ/MANAGE
# déjà existant, aucune nouvelle permission nécessaire pour eux.
STATION_SERVICE_READ = "zyloLiquid.stationService.read"
STATION_SERVICE_MANAGE = "zyloLiquid.stationService.manage"

PRICING_POLICY_READ = "zyloLiquid.pricingPolicy.read"
PRICING_POLICY_MANAGE = "zyloLiquid.pricingPolicy.manage"

# ================================================================
# Mission « vente-maintenant-reglementation » (06-permissions-par-domaine.md
# de la mission) — nouvelles permissions par domaine, jamais un second
# système de permissions.
# ================================================================

SELLABLE_PRODUCT_READ = "zyloLiquid.sellableProduct.read"
SELLABLE_PRODUCT_MANAGE = "zyloLiquid.sellableProduct.manage"

PRODUCT_SALE_READ = "zyloLiquid.productSale.read"
PRODUCT_SALE_CREATE = "zyloLiquid.productSale.create"
PRODUCT_SALE_CANCEL = "zyloLiquid.productSale.cancel"

EQUIPMENT_READ = "zyloLiquid.equipment.read"
EQUIPMENT_MANAGE = "zyloLiquid.equipment.manage"

INTERVENTION_READ = "zyloLiquid.intervention.read"
INTERVENTION_CREATE = "zyloLiquid.intervention.create"
INTERVENTION_ASSIGN = "zyloLiquid.intervention.assign"
INTERVENTION_CLOSE = "zyloLiquid.intervention.close"

TECHNICIAN_READ = "zyloLiquid.technician.read"
TECHNICIAN_MANAGE = "zyloLiquid.technician.manage"

REGULATORY_DOCUMENT_READ = "zyloLiquid.regulatoryDocument.read"
REGULATORY_DOCUMENT_CREATE = "zyloLiquid.regulatoryDocument.create"
REGULATORY_DOCUMENT_MANAGE = "zyloLiquid.regulatoryDocument.manage"
REGULATORY_DOCUMENT_ARCHIVE = "zyloLiquid.regulatoryDocument.archive"

REGULATORY_DECLARATION_READ = "zyloLiquid.regulatoryDeclaration.read"
REGULATORY_DECLARATION_MANAGE = "zyloLiquid.regulatoryDeclaration.manage"

# ================================================================
# Tracking GPS des camions-citernes — étape 2 (flux métier, 2026-09).
# ================================================================

TRUCK_ORDER_ASSIGNMENT_MANAGE = "zyloLiquid.truckOrderAssignment.manage"


# --- Lot B-L2 (T-004b) : exploitation de station (tours, pointage, passation, pompes, jauge, caisse, rapport) ---
SHIFT_DEFINITION_READ = "zyloLiquid.shiftDefinition.read"
SHIFT_DEFINITION_MANAGE = "zyloLiquid.shiftDefinition.manage"
SHIFT_PLANNING_READ = "zyloLiquid.shiftPlanning.read"
SHIFT_PLANNING_MANAGE = "zyloLiquid.shiftPlanning.manage"
# Pointage des présences du tour (B1) : RT, gérant (manage + read), auditeur et
# direction (read). Ni le chef d'équipe, ni le pompiste, ni le caissier.
SHIFT_ATTENDANCE_READ = "zyloLiquid.shiftAttendance.read"
SHIFT_ATTENDANCE_MANAGE = "zyloLiquid.shiftAttendance.manage"
# Passation entre responsables de tour (B2) : mêmes porteurs que le pointage.
SHIFT_HANDOVER_READ = "zyloLiquid.shiftHandover.read"
SHIFT_HANDOVER_MANAGE = "zyloLiquid.shiftHandover.manage"
# Remplacement et pauses en cours de tour (B5) : le RT et le gérant saisissent
# (manage + read) ; le chef d'équipe décide oralement et ne fait que lire ;
# caissier et auditeur lisent. Le pompiste n'a ni l'une ni l'autre (sa carte
# « Mon affectation du tour » relève de pumpAssignment.read, B4).
SHIFT_REPLACEMENT_READ = "zyloLiquid.shiftReplacement.read"
SHIFT_REPLACEMENT_MANAGE = "zyloLiquid.shiftReplacement.manage"
# Ouverture du tour et rapport de tour (B3) : RT et gérant (manage + read) ;
# chef d'équipe, caissier, auditeur (read). Sera étendue par D1 à D8.
SHIFT_REPORT_READ = "zyloLiquid.shiftReport.read"
SHIFT_REPORT_MANAGE = "zyloLiquid.shiftReport.manage"
HOLYKELL_ACCOUNT_MANAGE = "zyloLiquid.holykellAccount.manage"
# Affectation réelle des pompistes aux pompes au début du tour (B4) : le RT et
# le gérant saisissent/confirment (manage + read, le gérant possède tout ce que
# possède le RT) ; chef d'équipe, caissier, auditeur et pompiste lisent (le
# pompiste ne voit que SES pompes via /my-shift-assignment). Le chef d'équipe
# décide oralement, il n'écrit pas.
PUMP_ASSIGNMENT_READ = "zyloLiquid.pumpAssignment.read"
PUMP_ASSIGNMENT_MANAGE = "zyloLiquid.pumpAssignment.manage"
# Jaugeage des cuves à la fermeture du tour (D2) : le RT et le gérant saisissent
# et corrigent (manage + read ; le gérant possède tout ce que possède le RT) ;
# chef d'équipe, caissier et auditeur lisent (le chef d'équipe aide à la règle,
# il n'écrit pas). Distinctes de `manualGaugingDeclaration.create` (déclaration
# isolée existante), qui n'est pas modifiée.
TANK_GAUGING_READ = "zyloLiquid.tankGauging.read"
TANK_GAUGING_MANAGE = "zyloLiquid.tankGauging.manage"
# Index de fermeture des pompes et volumes vendus (D1) : le RT et le gérant saisissent
# et corrigent par rature paraphée (manage + read ; le gérant possède tout ce que
# possède le RT, anti-élévation) ; chef d'équipe, caissier et auditeur lisent (le chef
# d'équipe confirme la lecture à voix haute, il n'écrit pas). Le pompiste n'a rien.
PUMP_CLOSING_READ = "zyloLiquid.pumpClosing.read"
PUMP_CLOSING_MANAGE = "zyloLiquid.pumpClosing.manage"
# Comptage et remise de caisse par pompiste (D3) : le RT et le gérant saisissent, répartissent une
# pompe partagée et corrigent par rature paraphée (manage + read ; le gérant possède tout ce que
# possède le RT, anti-élévation) ; caissier et auditeur lisent. Le CHEF D'ÉQUIPE n'a AUCUN droit
# (« aucun pouvoir » sur l'écart de caisse, à confirmer terrain PC-22), le pompiste non plus.
# Distinctes de `cash.read` et `shiftCashDeclaration.*` (caisse par cuve, télémétrie), non modifiées.
CASH_COLLECTION_READ = "zyloLiquid.cashCollection.read"
CASH_COLLECTION_MANAGE = "zyloLiquid.cashCollection.manage"
# Calcul de la caisse A à H et du NOTA (D5) : le RT et le gérant saisissent les dépenses diverses, les règlements VAL/CCT et
# la règle de déduction lubrifiants/boutique (manage + read ; gérant ⊇ RT, anti-élévation) ; caissier et auditeur lisent.
# Le CHEF D'ÉQUIPE n'a AUCUN droit (comme D3, PC-22), le pompiste non plus. Distinctes de `cashCollection.*` (comptage D3).
CASH_SUMMARY_READ = "zyloLiquid.cashSummary.read"
CASH_SUMMARY_MANAGE = "zyloLiquid.cashSummary.manage"
# Rubriques 2 à 7 du rapport de tour (D4 : lubrifiants, gaz, boutique, crédits clients, bons valeur,
# paiements électroniques) : le RT et le gérant saisissent en brouillon sauvegardable jusqu'à la
# signature (manage + read ; le gérant possède tout ce que possède le RT, anti-élévation) ; le chef
# d'équipe et l'auditeur lisent. Le pompiste n'a rien (il remet ses bons papier au RT). Le RT n'a PAS
# `commercialAccount.read` : le contexte de crédit (noms, plaques, chauffeurs, reste disponible) passe
# par ces permissions-ci, jamais par la fiche complète du compte.
REPORT_SECTIONS_READ = "zyloLiquid.reportSections.read"
REPORT_SECTIONS_MANAGE = "zyloLiquid.reportSections.manage"
