# Endpoints 3 à 5 : cuves, association capteur-cuve, calibration

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

### Endpoint 3 — Cuves (`tanks`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.2.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/tanks` | `zyloLiquid.tank.manage` |
| GET | `/api/v1/zylo-liquid/tanks` | `zyloLiquid.tank.read` |
| GET | `/api/v1/zylo-liquid/tanks/{id}` | `zyloLiquid.tank.read` |
| PATCH | `/api/v1/zylo-liquid/tanks/{id}` | `zyloLiquid.tank.manage` |

`POST /tanks` accepte soit `fuelProductId` (produit déjà connu), soit
`newFuelProductName` + `newFuelProductCode` (création du produit dans le
même geste, conforme à Point 2 §1.2 "sans changer d'écran") — exactement
l'un des deux, jamais les deux ni aucun des deux
(`fuel_product_selection_invalid`, 422). Numéro de cuve unique par station
(`tank_number_already_used`, 409). Isolation tenant vérifiée en traversant
`Tank.stationId → Station.organizationId` (`Tank` lui-même n'a pas
d'`organizationId` propre, cohérent avec le schéma source où une cuve
n'existe que rattachée à une station).

Tests : `tests/test_zylo_liquid_tanks.py` (8 cas). Preuve à 3 niveaux :
`validation_log.md`.

### Endpoint 4 — Association capteur-cuve (`tank-sensor-mappings`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.3.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/tank-sensor-mappings` | `zyloLiquid.tankSensorMapping.manage` |
| GET | `/api/v1/zylo-liquid/tank-sensor-mappings` | `zyloLiquid.tankSensorMapping.read` |
| POST | `/api/v1/zylo-liquid/tank-sensor-mappings/{id}/close` | `zyloLiquid.tankSensorMapping.manage` |

**Point à vérifier avant implémentation (§9.3), résolu par inspection réelle
(issue #29)** : le contrat traduit un `hkSerialNumber` (numéro de série
physique) + un `measurementType` en `hkSensorId` interne. Or un même
numéro de série correspond à plusieurs lignes du registre Holykell (une
par canal : product_level/water_level/temperature). Vérifié sur la base
réelle `zylo_liquid` : `hk_sensor_name` porte explicitement le type de
mesure en préfixe (`"product_level Cuve 1"`, `"water_level Cuve 1"`,
`"temperature Cuve 1"`) pour toutes les lignes inspectées — donnée réelle,
pas une invention. Résolution implémentée via
`hkSerialNumber == ... AND hkSensorName ILIKE '<measurementType>%'`.

**Limite héritée du schéma source, non contournée** : la contrainte
d'unicité `(hkSensorId, measurementType, tankId)` de la table
`tank_sensor_mapping` (confirmée identique en base réelle) empêche de
recréer une association avec exactement le même capteur après l'avoir
close — un remplacement de sonde doit donc toujours porter un `hkSensorId`
différent (nouvelle sonde physique), jamais la réactivation de l'ancienne
ligne. Testé explicitement (`test_close_tank_sensor_mapping_then_replace_with_new_sensor`).

Tests : `tests/test_zylo_liquid_tank_sensor_mappings.py` (8 cas, incluant
la résolution du bon canal parmi plusieurs sur un même numéro de série).
Preuve à 3 niveaux : `validation_log.md`.

### Endpoint 5 — Table de calibration d'une cuve (`tanks/{id}/calibration-points`)

> Note d'ordre : cet endpoint correspond à l'item 4 de la liste de
> construction (§12 de Point 3), sauté par erreur avant l'endpoint 4
> (tank-sensor-mappings, item 5) — corrigé ici pour respecter l'ordre de
> dépendances réel (cette table doit exister avant l'endpoint 7, état
> actuel d'une cuve, qui l'utilise pour tout calcul de volume).

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.4.

| Méthode | Route | Permission |
|---|---|---|
| PUT | `/api/v1/zylo-liquid/tanks/{id}/calibration-points` | `zyloLiquid.tankCalibration.manage` |
| GET | `/api/v1/zylo-liquid/tanks/{id}/calibration-points` | `zyloLiquid.tankCalibration.read` |

`PUT` remplace intégralement la table (jamais une fusion partielle,
conforme à Point 2 §1.4) : suppression de tous les points existants puis
insertion de la nouvelle liste, dans la même transaction. Deux validations
bloquantes : la hauteur maximale de la table ne doit jamais dépasser
`Tank.tankHeightMm` (`calibration_height_exceeds_tank`, 422) ; le volume ne
doit jamais diminuer quand la hauteur augmente
(`calibration_table_not_monotonic`, 422). `GET` sur une cuve sans aucune
table renvoie une liste vide, jamais une erreur (état normal d'une cuve
nouvellement créée, conforme à Point 2 §1.4).

Tests : `tests/test_zylo_liquid_tank_calibration_points.py` (8 cas).
Preuve à 3 niveaux : `validation_log.md`.
