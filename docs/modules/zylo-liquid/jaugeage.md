# Jaugeage des cuves à la fermeture du tour (D2, lot B-L3)

- **Statut** : code et migration `c8d0e2f4a516` dans le commit B-L3 de `feat/T-004b-lot-liquid`. Non exécuté en base (voir [exploitation.md](exploitation.md)).
- **Routes** : `GET|PUT /zylo-liquid/shift-reports/{report_id}/closing-gauging` (`rotes/jauge.py`), gardes `tankGauging.read` / `tankGauging.manage`.

## Règles

- Le jaugeage réutilise `ManualGaugingDeclaration` (une déclaration par cuve et par enregistrement, rature = `correctsDeclarationId`). Aucune seconde table de jaugeage.
- Le rapprochement avec la télémétrie passe par `_evaluate_manual_gauging_declaration_reconciliation_core` (`service.py`), sans contrôle de permission : le jaugeage de fermeture est protégé par `tankGauging.manage`, pas par `reconciliation.read`. La fonction publique garde son contrôle.
- Litres : table de jaugeage (`TankCalibrationPoint`) ou table papier (`realStockSource = paper_table`, référence obligatoire).
- Stock théorique = ouverture + reçu − vendu − sorties hors vente nettes ; le vendu vient du lot D1, jamais saisi.
- Verrou optimiste : `gaugingVersion` sur toutes les lignes du rapport.

## Migration

`c8d0e2f4a516` ajoute des colonnes nullables (ou à défaut `0`) à `zyloLiquidShiftReportTankLine` et la contrainte `realStockSource`. Aucune donnée n'est supprimée. Le downgrade supprime les colonnes ajoutées.
