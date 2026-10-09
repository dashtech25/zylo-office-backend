# Zylo Liquid — Phase 1 : Base de données

> Document de référence complet : [`phase_1_database.md`](../../../phase_1_database.md)
> à la racine du dépôt — nom de livrable imposé tel quel par
> `instruction_2_base_donnees_phase_1.md`. Ce fichier n'en est qu'un résumé
> de navigation, pour rester cohérent avec la convention `docs/modules/<nom>/`
> décrite dans [`docs/README.md`](../../README.md).

## En une phrase

Socle géographique (`country`/`region`/`city`) factorisé dans le Core, et
couches 1-2 (Télémétrie + Référentiel) du module Zylo Liquid (comptes et
capteurs Holykell, mesures immuables, cuves, calibration) créées et testées
en base réelle — les couches 3 à 7 (propriétaires, utilisateurs, quarts,
livraisons, réconciliation, alertes, crédit) restent en attente d'une
décision de classification Core/module (voir le document complet, §20.7).

## Modèles créés dans cette phase

| Fichier | Contenu |
|---|---|
| `app/shared/geo.py` | `Country`, `Region`, `City` (Core) |
| `app/modules/zylo_liquid/models.py` | `HolykellAccount`, `HolykellDeviceRegistry`, `TankMeasurement`, `FuelProduct`, `Station`, `Tank`, `TankSensorMapping`, `TankCalibrationPoint` |

## Prochaine étape

Trancher la classification des 7 tables « À valider » (§20.7 du document
complet) avant de continuer les couches 3-7. Une fois tranchée, la Phase 1
pourra être complétée ; la Phase 2 (API) ne doit démarrer qu'après validation
explicite de la Phase 1 dans son ensemble (règle du prompt d'origine).
