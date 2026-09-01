# Zylo Liquid — Phase 2 : API

> Document vivant, complété endpoint par endpoint au fur et à mesure de leur
> construction (procédure : `Point 3 — Définir la procédure de développement
> endpoint par endpoint.md`, `nouveau-station-simulator/etude-nouveau-zylo/`).
> Un seul endpoint en cours de développement à la fois — cette section ne
> couvre que les endpoints déjà `TERMINÉ` selon le cycle d'état du §19 de
> Point 3.

## 1. Quelle architecture est appliquée

Modular Monolith with Layered Domain Model (`grande_phases.md` §5-6) : le
module `app/modules/zylo_liquid/` porte ses propres `models.py`,
`schemas.py`, `service.py`, `router.py`, `permissions.py`, `seed.py` —
jamais mêlés au Core. Pagination `limit`/`offset` + enveloppe
`{"data","meta"}`, erreurs `{"error":{"code","message","details"}}`,
authentification JWT + `X-Organization-Id` + `require_permission` +
`require_module_active("zylo_liquid")` — repris tels quels du socle
(`grande_phases.md` §14, §7-9).

## 2. Ce qui a été construit

### Endpoint 1 — Produits carburant (`fuel-products`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.5.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/fuel-products` | `zyloLiquid.fuelProduct.manage` |
| GET | `/api/v1/zylo-liquid/fuel-products` | `zyloLiquid.fuelProduct.read` |
| GET | `/api/v1/zylo-liquid/fuel-products/{id}` | `zyloLiquid.fuelProduct.read` |
| PATCH | `/api/v1/zylo-liquid/fuel-products/{id}` | `zyloLiquid.fuelProduct.manage` |

Fichiers : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
câblage dans `app/api/v1/router.py` (préfixe `/zylo-liquid`).

Tests : `tests/test_zylo_liquid_fuel_products.py` (8 cas : création/lecture,
pagination + isolation multi-tenant, code dupliqué → 409, modification,
404, permission manquante → 403, en-tête organisation manquant → 422, non
authentifié → 401). Preuve à 3 niveaux : `validation_log.md`.

### Endpoint 2 — Stations (`stations`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.1.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/stations` | `zyloLiquid.station.manage` |
| GET | `/api/v1/zylo-liquid/stations` | `zyloLiquid.station.read` |
| GET | `/api/v1/zylo-liquid/stations/{id}` | `zyloLiquid.station.read` |
| PATCH | `/api/v1/zylo-liquid/stations/{id}` | `zyloLiquid.station.manage` |
| POST | `/api/v1/zylo-liquid/stations/{id}/deactivate` | `zyloLiquid.station.manage` |
| POST | `/api/v1/zylo-liquid/stations/{id}/reactivate` | `zyloLiquid.station.manage` |

Modèle `Station` déjà existant (Phase 1), déjà `organizationId`-scopé —
aucune extension de modèle nécessaire (§9.3 confirmé : réutiliser tel quel).
`GET /stations` inclut `activeTankCount` par station (compté via jointure
sur `Tank.active`, conforme au contrat Point 2 §1.1 "nombre de cuves
actives"). Statut modifiable uniquement via `deactivate`/`reactivate`,
jamais via `PATCH` (garde-fou de transition d'état, Point 2 §1.1).

Tests : `tests/test_zylo_liquid_stations.py` (8 cas). Ville inconnue du
référentiel géo Core → `city_not_found` (422). Isolation tenant stricte :
accès à une station d'une autre organisation → 404 `station_not_found`
(jamais 403, pour ne rien révéler de l'existence des données d'un autre
tenant, conforme à Point 2 §1.1). Preuve à 3 niveaux : `validation_log.md`.

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

### Endpoint 6 — État de synchronisation Holykell (`holykell-accounts/{id}/sync-status`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 2.1.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/holykell-accounts/{id}/sync-status` | `zyloLiquid.holykellAccount.read` |

**Écart documenté entre le contrat et le modèle réel (§9.3, issue #33)** :
Point 2 §2.1 affirme « chaque organisation a exactement un compte Holykell
(contrainte déjà en base) » — vérifié faux : aucune `UniqueConstraint` sur
`HolykellAccount.organizationId`. L'endpoint reste correct malgré tout
(adressé par son identifiant explicite dans le chemin, pas déduit de
l'organisation courante), mais l'affirmation du contrat est erronée et
n'a pas été corrigée arbitrairement — si un jour une organisation doit
strictement n'avoir qu'un compte, la contrainte devra être ajoutée après
validation métier explicite, pas devinée ici.

Tests : `tests/test_zylo_liquid_holykell_sync_status.py` (5 cas, incluant
isolation tenant stricte : compte d'une autre organisation → 404).
Preuve à 3 niveaux : `validation_log.md`.

### Endpoint 7 — État actuel d'une cuve/station (`current-state`)

**Premier endpoint exerçant un algorithme métier validé** (Point 3 §10).
Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 3.1.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/tanks/{id}/current-state` | `zyloLiquid.tank.read` |
| GET | `/api/v1/zylo-liquid/stations/{id}/current-state` | `zyloLiquid.station.read` |

**Algorithmes** (`app/modules/zylo_liquid/algorithms.py`, fonctions pures,
testées seules avant branchement — Niveau 1 de `validation_log.md`) :
- `interpolate_height_to_volume` — interpolation linéaire entre les deux
  points de calibration encadrants, bornée (clamp) hors plage. Référence
  exacte vérifiée : 1073 mm → 19729 L (nouveau-zylo-liquid/Point 2 §2.4).
- `correct_volume_to_reference_temperature` — `V15 = V × [1 - α×(T-15)]`.
  Référence exacte vérifiée : V=19729L, T=35°C, α=0.00085 → 19394L
  (nouveau-zylo-liquid/Point 5 §5.2).

**Extension de modèle** : `FuelProduct.thermalExpansionCoefficient` (α),
confirmé absent en Phase 1 (Point 2 §7), ajouté ici — nullable : sans
valeur connue, aucune correction n'est appliquée (`volumeLiters15C: null`),
jamais un coefficient inventé.

**Décision de conception (issue #35)** : la mesure instantanée est lue
depuis `HolykellDeviceRegistry.lastValue`/`lastValueAt`/`hkLastStatus` —
jamais une requête sur `TankMeasurement` (réservé à l'historique, table à
potentiellement des millions de lignes) — conforme à
nouveau-zylo-liquid/Point 6 §6.4. Le statut sonde (`online`/`offline`)
provient directement de `hkLastStatus`, déjà maintenu par la
synchronisation Holykell — aucun seuil d'ancienneté arbitraire inventé.

**Règles de non-invention respectées** (Point 2 §3.1) :
- Aucune association capteur active → `sensorStatus: "not_configured"`,
  tous les champs de volume à `null`, jamais un zéro.
- Aucune table de calibration → `heightMm` brut renvoyé,
  `volumeNotCalculableReason: "no_calibration_table"`, jamais un volume
  inventé.
- Absence de capteur eau → volume eau traité comme 0 (normal, pas une
  erreur) ; absence de capteur température → pas de correction 15°C
  (`volumeLiters15C: null`), jamais une température supposée.

Tests : `tests/test_zylo_liquid_current_state.py` (9 cas, incluant le
calcul complet carburant+eau+correction thermique avec valeurs numériques
vérifiées). Preuve à 3 niveaux : `validation_log.md` (Niveau 1 : 8 tests
algorithmiques ; Niveau 2 : contrats des 2 endpoints).

### Endpoint 8 — Historique des mesures d'une cuve (`tanks/{id}/measurements`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 5.1.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/tanks/{id}/measurements` | `zyloLiquid.tank.read` |

**Point non tranché par le contrat, résolu ici (issue #37)** : Point 2
§5.1 note lui-même qu'une valeur par défaut de période (ex. « dernières
24h ») reste « à confirmer avec le commanditaire ». Décision : aucune
fenêtre par défaut inventée — sans `fromDate`/`toDate`, la pagination seule
s'applique sur tout l'historique disponible.

**Décision de conception** : l'historique porte sur tous les capteurs
`product_level` ayant un jour été associés à cette cuve (mapping actif ou
clos), pas seulement le mapping courant — un remplacement de sonde
(endpoint 4) ne doit jamais faire disparaître les mesures déjà collectées
par l'ancienne sonde. Testé explicitement
(`test_list_measurements_survives_sensor_replacement`).

Tri par `measuredAt` croissant (jamais `receivedAt`, conforme à Point 2
§5.1). Volume converti via `interpolate_height_to_volume` (algorithme déjà
validé à l'endpoint 7, jamais réimplémenté) si une table de calibration
existe pour la cuve, sinon `null`.

Tests : `tests/test_zylo_liquid_tank_measurements.py` (7 cas). Preuve à 3
niveaux : `validation_log.md` (aucun nouvel algorithme, réutilisation de
celui de l'endpoint 7).

### Endpoint 9 — Vue réseau complète (`network/summary`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 3.2.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/network/summary` | `zyloLiquid.station.read` |

**Contradiction entre sources, résolue explicitement (issue #39)** :
Point 2 §3.2 mentionne un paramètre de période (`fromDate`/`toDate`,
« pour n'importe quelle période ») ; Point 3 §11/§12 documente pourtant
cet endpoint comme dépendant **uniquement** de l'endpoint 7 (état actuel),
jamais de l'historique des mesures. Décision : seul l'instant présent est
implémenté (agrégation de l'état actuel de chaque cuve active, réutilisant
`get_tank_current_state` de l'endpoint 7, jamais réimplémenté) ; si
`fromDate`/`toDate` sont fournis, l'endpoint retourne explicitement
`historical_network_summary_not_supported` (422) plutôt que d'inventer une
résolution rétroactive — cette capacité reviendra, si besoin, avec
l'endpoint 13 (`network/snapshot`), seul endroit où l'historique est
spécifié.

**Règle de non-invention (Point 2 §3.2, cohérente avec l'endpoint 7)** :
une cuve sans volume calculable (pas de capteur configuré, pas de
calibration) est exclue du total, jamais comptée comme 0. Testé
explicitement (`test_network_summary_excludes_tank_without_calculable_volume`).

Tests : `tests/test_zylo_liquid_network_summary.py` (5 cas). Preuve à 3
niveaux : `validation_log.md` (aucun nouvel algorithme).

### Endpoint 10 — Livraisons détectées (`deliveries`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 3.3.
Premier endpoint avec un test d'intégration Niveau 3 complet (Point 4).

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/deliveries` | `zyloLiquid.delivery.read` |
| GET | `/api/v1/zylo-liquid/deliveries/{id}` | `zyloLiquid.delivery.read` |

**Modèle créé** : `DeliveryDetected` (confirmé absent, Point 2 §7), CRÉER
justifié — table alimentée uniquement par détection automatique, jamais
par une saisie manuelle (contrat explicite, cohérent avec l'exclusion MVP
« pas de bons de livraison manuels »).

**Algorithme** (`detect_deliveries`, `app/modules/zylo_liquid/algorithms.py`) :
seuils exacts du code Odoo audité cités en Point 3 §10 — hausse ≥ 50mm
déclenche le suivi, stabilité < 5mm confirmée après 15 min de continuité
signe la fin. Volume = calibration(fin) - calibration(début), **sans**
correction des ventes simultanées (Point 8 §8.6 : l'index compteurs
nécessaire à cette correction est explicitement hors périmètre MVP,
`fonctionnalite-mvp.md`). Testé avec le scénario numérique exact de Point 8
§8.5/§8.8 : 445mm→1293mm, volume brut 10875L (Niveau 1,
`tests/test_zylo_liquid_algorithms.py`).

**Limite de portée documentée (issue #41)** : comme `TankMeasurement` et
`HolykellDeviceRegistry`, cette table est censée être alimentée par un
traitement de fond (scan périodique de l'historique des mesures) —
construire ce scheduler est hors périmètre d'un « endpoint » API (Point 3
§12 ne liste que des endpoints). La fonction `run_delivery_detection_for_tank`
existe et est testée directement (idempotente via la contrainte
`tankId+startTime`), mais n'est appelée par aucune route HTTP, conforme au
contrat (« aucun endpoint de création manuelle »).

Tests : `tests/test_zylo_liquid_deliveries.py` (6 cas, incluant un
scénario d'intégration Niveau 3 complet : mesures réelles → détection →
persistance → lecture API, volume exact 10875L vérifié de bout en bout).
Preuve à 3 niveaux : `validation_log.md`.

### Endpoint 11 — Événements de fuite détectés (`leak-events`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 3.4.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/leak-events` | `zyloLiquid.leakEvent.read` |
| GET | `/api/v1/zylo-liquid/leak-events/{id}` | `zyloLiquid.leakEvent.read` |

**Modèle créé** : `LeakageRecord` (confirmé absent, Point 2 §7).

**Algorithme, version finale corrigée EPA** (`compute_net_corrected_volume`,
`compute_leak_rate_lph`, `is_leak_detected` — `app/modules/zylo_liquid/algorithms.py`) :
contrairement à la version initiale simplifiée de Point 10 §10.3
(`Volume perdu = Start Volume - End Volume` brut), la version finale
(Point 10, correction post-§10.3) exige deux garde-fous, testés
individuellement (Niveau 1) pour prouver qu'ils préviennent des faux
positifs documentés :
- **Soustraction de l'eau avant le calcul** — sinon une variation d'eau
  normale (condensation) fausse le taux de fuite carburant.
- **Correction thermique à 15°C** — sinon un refroidissement nocturne
  normal de 2°C sur une cuve de Gasoil (α=0.00085) produit ~31L de « fuite »
  fictive (exemple documenté, reproduit exactement dans
  `test_compute_net_corrected_volume_thermal_correction_prevents_false_positive`).

Seuil 0.38 L/H strictement supérieur (standard EPA, Point 10 §10.4).

**Portée volontairement limitée (issue #43)** : seule la détection
**statique** (Point 10 §10.3) est implémentée — la détection dynamique par
tendance sur 7 jours (Point 10 §10.6) est explicitement exclue « pour le
moment » par la source elle-même, pas une omission. Un test de fuite porte
sur une fenêtre explicite (`startTime`/`endTime`), contrairement aux
livraisons qui scannent tout l'historique en continu — cohérent avec la
réalité opérationnelle (« station à l'arrêt », un test à la fois).

Tests : `tests/test_zylo_liquid_leak_events.py` (7 cas, incluant un
scénario d'intégration Niveau 3 : mesures réelles → test de fuite →
`result: "anomaly"` avec le taux exact → lecture API). Preuve à 3 niveaux :
`validation_log.md`.

### Endpoint 12 — Alertes (`alerts`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 4
(4.1-4.6, un seul jeu d'endpoints partagé par les 5 déclencheurs).

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/alerts` | `zyloLiquid.alert.read` |
| GET | `/api/v1/zylo-liquid/alerts/{id}` | `zyloLiquid.alert.read` |
| PATCH | `/api/v1/zylo-liquid/alerts/{id}` | `zyloLiquid.alert.manage` |

**Modèle créé** : `Alert` (confirmé absent, Point 2 §7), table unique
partagée par les 6 types (`level_high`, `level_high_pre_alarm`,
`level_low`, `water`, `leak`, `sensor_offline`) — conforme à Point 2 §4
(« un seul type d'enregistrement »).

**Algorithme** (`evaluate_threshold_alarms`, testé avec l'exemple exact de
Point 13 §13.5 : H_carburant=195mm, H_eau=0mm, Low_alarm=200mm → alerte
niveau bas) : `H_net = H_carburant - H_eau`, comparé aux 4 seuils déjà
saisis sur `Tank` (endpoint 3), jamais réimplémenté. Alerte pleine et
pré-alarme de niveau haut mutuellement exclusives (escalade) ; alerte eau
indépendante.

**Déclencheurs couverts et leur source, chacun sans invention** :
- Niveau haut/pré-alarme/bas/eau : évaluation à la demande de l'état
  instantané (`HolykellDeviceRegistry.lastValue`, même source que
  l'endpoint 7, jamais `TankMeasurement`).
- Fuite : déclenchée automatiquement par `run_leak_test_for_tank`
  (endpoint 11) quand `result="anomaly"` — aucune logique dupliquée.
- Sonde déconnectée : basée sur `hkLastStatus` déjà maintenu par la
  synchronisation Holykell — **aucun seuil d'ancienneté inventé**, même
  principe déjà retenu pour l'endpoint 7 (issue #35).

**Anti-spam** : jamais deux alertes actives du même type simultanément
pour une même cuve — une nouvelle évaluation qui retrouve la même
condition ne recrée rien tant que l'alerte précédente n'est pas résolue.

**Résolution strictement manuelle** (`PATCH`) : jamais automatique, y
compris pour « sonde déconnectée » — Point 2 §4.6 laisse ce cas
explicitement comme « point à confirmer avec le commanditaire, non
tranché ici » ; non tranché non plus dans cette implémentation.

Tests : `tests/test_zylo_liquid_alerts.py` (8 cas, incluant un scénario
d'intégration Niveau 3 complet : mesure sous seuil → alerte → lecture API
→ résolution → tentative de double résolution rejetée). Preuve à 3
niveaux : `validation_log.md`.

### Endpoint 13 — Snapshot réseau à une date donnée (`network/snapshot`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 5.4.
« La fonctionnalité la plus avancée du MVP » — dernier endpoint de lecture
construit, conforme à l'ordre du §12 de Point 3.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/zylo-liquid/network/snapshot` | `zyloLiquid.station.read` |

Même structure de réponse que l'endpoint 9 (`network/summary`),
réutilisée sans duplication (`NetworkSummaryResponse`) — seule la source
de la mesure change : dernière valeur **connue avant ou égale** à
l'instant demandé dans `TankMeasurement` (jamais une mesure postérieure),
au lieu de `HolykellDeviceRegistry.lastValue` (instant présent). Volume
converti via `interpolate_height_to_volume`, déjà validé à l'endpoint 7.

**Règles de non-invention reprises de l'endpoint 9** : une cuve sans
mesure antérieure à l'instant demandé est exclue du total, jamais comptée
comme 0 ; date dans le futur → 422 `snapshot_date_in_future`.

**Point de vigilance technique déjà documenté par le contrat lui-même,
non traité ici (issue #47)** : la reconstitution interroge l'historique
complet à chaque appel, potentiellement coûteux sur un grand volume de
mesures (~590 000 lignes déjà en base de test). Un snapshot pré-calculé
périodiquement est explicitement laissé à une Phase 2 ultérieure par le
contrat — pas une omission de cet endpoint.

Tests : `tests/test_zylo_liquid_network_snapshot.py` (5 cas). Preuve à 3
niveaux : `validation_log.md` (aucun nouvel algorithme, réutilisation de
celui de l'endpoint 7).

## 3. Ce qui a été factorisé dans le Core (correction de portée, pas une extension du périmètre initial)

**`app/modules_registry/service.grant_module_permissions_to_owner`** —
constat fait en construisant cet endpoint 1 : aucun endpoint HTTP RBAC
n'existe pour attribuer une permission à un rôle (`app/rbac/` n'a ni
`router.py` ni `schemas.py`) — un module activé restait donc inutilisable
par quiconque, y compris son propre owner, tant qu'aucune permission ne lui
était accordée manuellement en base. Corrigé dans le Core (`modules_registry`,
pas dans `zylo_liquid`, car applicable à tout module futur) : l'activation
d'un module accorde désormais automatiquement au rôle `owner` de
l'organisation toutes les permissions déjà déclarées (table `permission`)
pour ce `moduleCode`. Testé dans `tests/test_modules.py::test_activating_module_grants_its_permissions_to_owner`.

**`app/modules/zylo_liquid/seed.py::seed_known_permissions`** — permissions
zylo_liquid pré-enregistrées au démarrage (`app/main.py`), symétrique à
`seed_known_modules` déjà existant — nécessaire pour que
`grant_module_permissions_to_owner` trouve des lignes `Permission` à
accorder dès la première activation.

## 4. Ce qui reste propre au module

Le modèle `FuelProduct`, son service, ses schémas et son router restent
entièrement dans `app/modules/zylo_liquid/` — aucune notion Core nouvelle
introduite par cet endpoint hors la correction RBAC ci-dessus.

## 5. Comparaison aux sources de vérité

- `schema_complet_base_de_donnees.sql` : table `fuel_products`, aucune
  colonne d'organisation (schéma source pensé pour un réseau unique).
- Base réelle `zylo_liquid` : `fuel_products.code` UNIQUE globalement,
  confirmé identique au schéma (Phase 1, `phase_1_database.md`).
- `niveau_1_base_de_donnees_et_monetisation.md` : ne couvre pas
  l'isolation multi-tenant de `FuelProduct` (hors de son périmètre, centré
  sur le sujet monétaire) — décision ci-dessous prise indépendamment.

## 6. Décisions prises

**`FuelProduct.organizationId` ajouté (ÉTENDRE, pas CRÉER)** — absent du
schéma source et de la base réelle testée (réseau unique, jamais
multi-tenant dans ce contexte), mais requis par cohérence avec l'isolation
déjà appliquée à `Station`, `Tank`, `HolykellAccount` et toute autre table
Zylo Liquid : sans cette colonne, une organisation aurait vu et modifié le
référentiel carburant de toutes les autres. `code` redevient unique par
organisation (`uq_zlFuelProduct_org_code`) plutôt que globalement unique.
Migration `7ffb9473d45e_fuel_product_organization_id.py` — une seule ligne
de développement supprimée (`TRUNCATE ... CASCADE`), aucune donnée de
production concernée. Décision prise dans le cadre de la procédure §8/§9.3
de Point 3 (vérification du modèle avant tout endpoint), pas une
alternative business — c'est une exigence d'isolation déjà actée pour
toutes les tables sœurs.

**`Tank` : 3 champs pourcentage remplacés par 3 champs millimètres
(ÉTENDRE)** — `alertLowPercent`/`alertCriticalPercent`/`alertHighPercent`
(Phase 1) remplacés par `heightAlarmMm`/`heightAlertMm`/`lowAlarmMm`.
`fonctionnalite-mvp.md` §1.2 et Point 2 §1.2 exigent explicitement des
seuils en millimètres, saisis par cuve — cohérent avec l'algorithme
d'alarme du Point 13 qui compare `H_net` directement à des seuils en mm,
jamais à un pourcentage de capacité. Les champs pourcentage n'avaient
jamais été exposés par aucun endpoint (`tanks` est le premier endpoint à
toucher ce modèle) et la table était vide en développement — remplacement
sans donnée perdue, migration `82fd37bd908f_tank_mm_alarm_thresholds.py`.
`alertWaterMaxMm` déjà conforme (mm), conservé sans changement.

**Permissions de module accordées automatiquement au owner à l'activation**
— voir §3 ci-dessus. Décision structurelle du socle, pas spécifique à Zylo
Liquid, mais découverte et corrigée à l'occasion de ce premier endpoint.

## 7. Points encore à confirmer

- Aucun rôle autre que `owner` ne peut aujourd'hui recevoir une permission
  zylo_liquid (aucun endpoint RBAC HTTP pour associer un rôle non-owner à
  une permission) — hors périmètre de l'endpoint 1, à traiter si/quand un
  besoin de rôle non-owner apparaît sur un module métier.

## 8. Rapport final — Endpoint 1

- Fichiers créés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  `tests/test_zylo_liquid_fuel_products.py`, cette documentation.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (colonne
  `organizationId`), `app/api/v1/router.py` (câblage), `app/main.py` (seed
  des permissions), `app/modules_registry/service.py`
  (`grant_module_permissions_to_owner`), `tests/conftest.py` (fixture
  `zylo_liquid_organization`), `tests/test_modules.py` (test de
  régression du nouveau comportement d'activation).
- Migration : `7ffb9473d45e_fuel_product_organization_id.py`, appliquée en
  développement.
- Tests : 22/22 verts (`python -m pytest`), y compris les 21 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` complète (create/get/list/patch,
  code dupliqué → 409, introuvable → 404, permission manquante → 403 avant
  correction RBAC puis 201 après) contre le serveur de développement
  (`uvicorn`, base `zylo_office`).
- Statut : **TERMINÉ**.

## 9. Rapport final — Endpoint 2

- Fichiers créés : `tests/test_zylo_liquid_stations.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  `tests/conftest.py` (fixture `test_city`), cette documentation,
  `validation_log.md` (à la racine du dépôt, nouveau — journal de preuve à 3
  niveaux, méthodologie adoptée à cet endpoint et appliquée
  rétroactivement à l'endpoint 1).
- Migration : aucune (modèle `Station` déjà conforme depuis la Phase 1).
- Tests : 30/30 verts (`python -m pytest`), y compris les 22 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` complète des 4 cas minimum imposés par
  la méthodologie de validation (normal, introuvable, donnée invalide,
  autre tenant) contre le serveur de développement.
- Statut : **TERMINÉ**.

## 10. Rapport final — Endpoint 3

- Fichiers créés : `tests/test_zylo_liquid_tanks.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (3 champs mm
  remplaçant 3 champs pourcentage sur `Tank`), `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  cette documentation, `validation_log.md`.
- Migration : `82fd37bd908f_tank_mm_alarm_thresholds.py`, appliquée en
  développement (table vide, aucune donnée perdue).
- Tests : 38/38 verts (`python -m pytest`), y compris les 30 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (création avec
  produit créé à la volée, introuvable → 404, sélection produit invalide →
  422, module inactif sur une autre organisation → 403) contre le serveur
  de développement.
- Statut : **TERMINÉ**.

## 11. Rapport final — Endpoint 4

- Fichiers créés : `tests/test_zylo_liquid_tank_sensor_mappings.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  `tests/conftest.py` (fixture `register_holykell_sensor` — insertion
  directe, aucun endpoint HTTP ne crée de registre Holykell, alimenté par
  la synchronisation de fond hors périmètre API), cette documentation,
  `validation_log.md`.
- Migration : aucune (modèles `TankSensorMapping`/`HolykellDeviceRegistry`
  déjà conformes depuis la Phase 1).
- Tests : 46/46 verts (`python -m pytest`), y compris les 38 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (création normale,
  clôture d'une association inexistante → 404, numéro de série inconnu →
  422, module inactif sur une autre organisation → 403) contre le serveur
  de développement, avec un capteur Holykell réellement inséré en base.
- Statut : **TERMINÉ**.

## 12. Rapport final — Endpoint 5

- Fichiers créés : `tests/test_zylo_liquid_tank_calibration_points.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  cette documentation, `validation_log.md`.
- Migration : aucune (modèle `TankCalibrationPoint` déjà conforme depuis la
  Phase 1).
- Tests : 54/54 verts (`python -m pytest`), y compris les 46 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (remplacement
  normal, hauteur dépassant la cuve → 422, table non monotone → 422, cuve
  introuvable → 404) contre le serveur de développement.
- Statut : **TERMINÉ**.

## 13. Rapport final — Endpoint 6

- Fichiers créés : `tests/test_zylo_liquid_holykell_sync_status.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  cette documentation, `validation_log.md`.
- Migration : aucune (modèle `HolykellAccount` déjà conforme depuis la
  Phase 1 ; écart de contrat documenté ci-dessus, non corrigé sans
  validation métier).
- Tests : 59/59 verts (`python -m pytest`), y compris les 54 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (statut réussi,
  compte introuvable → 404, isolation tenant → 404, module inactif → 403)
  contre le serveur de développement.
- Statut : **TERMINÉ**.

## 14. Rapport final — Endpoint 7

- Fichiers créés : `app/modules/zylo_liquid/algorithms.py`,
  `tests/test_zylo_liquid_algorithms.py` (Niveau 1, 8 cas),
  `tests/test_zylo_liquid_current_state.py` (Niveau 2, 9 cas).
- Fichiers modifiés : `app/modules/zylo_liquid/models.py`
  (`FuelProduct.thermalExpansionCoefficient`), `app/modules/zylo_liquid/{schemas,service,router}.py`,
  cette documentation, `validation_log.md`.
- Migration : `fecaf414f49e_fuel_product_thermal_expansion_coefficient.py`
  (colonne nullable, aucune donnée existante affectée).
- Tests : 76/76 verts (`python -m pytest`), y compris les 59 tests
  préexistants (non-régression) + 8 tests Niveau 1 (algorithmes purs) + 9
  tests Niveau 2 (contrats des 2 endpoints).
- Vérification réelle : suite `curl` des 4 cas minimum (cuve sans capteur
  configuré, calcul complet avec capteur réel, cuve introuvable → 404,
  module inactif → 403) contre le serveur de développement.
- Statut : **TERMINÉ**.

## 15. Rapport final — Endpoint 8

- Fichiers créés : `tests/test_zylo_liquid_tank_measurements.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router}.py`,
  cette documentation, `validation_log.md`.
- Migration : aucune (modèle `TankMeasurement` déjà conforme depuis la
  Phase 1).
- Tests : 83/83 verts (`python -m pytest`), y compris les 76 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (historique
  normal avec volume converti, filtre de dates, plage de dates invalide →
  422, cuve introuvable → 404) contre le serveur de développement.
- Statut : **TERMINÉ**.

## 16. Rapport final — Endpoint 9

- Fichiers créés : `tests/test_zylo_liquid_network_summary.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{schemas,service,router}.py`,
  cette documentation, `validation_log.md`.
- Migration : aucune.
- Tests : 88/88 verts (`python -m pytest`), y compris les 83 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` des 4 cas minimum (agrégation
  normale par produit, cuve non configurée exclue, période demandée → 422,
  module inactif → 403) contre le serveur de développement.
- Statut : **TERMINÉ**.

## 17. Rapport final — Endpoint 10

- Fichiers créés : `tests/test_zylo_liquid_deliveries.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (`DeliveryDetected`,
  nouveau), `app/modules/zylo_liquid/algorithms.py` (`detect_deliveries`),
  `tests/test_zylo_liquid_algorithms.py` (Niveau 1, +3 cas),
  `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  cette documentation, `validation_log.md`.
- Migration : `83f1a725f86b_delivery_detected.py` (nouvelle table).
- Tests : 97/97 verts (`python -m pytest`), y compris les 88 tests
  préexistants (non-régression) + 3 Niveau 1 + 6 Niveau 2/3.
- Vérification réelle : scénario complet rejoué contre le serveur de
  développement (série de mesures réelles → détection → lecture API,
  volume exact 10875L confirmé), plus cas introuvable/plage invalide/
  permission manquante.
- Statut : **TERMINÉ**.

## 18. Rapport final — Endpoint 11

- Fichiers créés : `tests/test_zylo_liquid_leak_events.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (`LeakageRecord`,
  nouveau), `app/modules/zylo_liquid/algorithms.py`
  (`compute_net_corrected_volume`, `compute_leak_rate_lph`,
  `is_leak_detected`), `tests/test_zylo_liquid_algorithms.py` (Niveau 1,
  +4 cas), `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  cette documentation, `validation_log.md`.
- Migration : `f049b4c60e80_leakage_record.py` (nouvelle table).
- Tests : 108/108 verts (`python -m pytest`), y compris les 97
  tests préexistants (non-régression) + 4 Niveau 1 + 7 Niveau 2/3.
- Vérification réelle : scénario complet rejoué contre le serveur de
  développement (mesures réelles → test de fuite → `result:"anomaly"`,
  taux exact confirmé → lecture API).
- Statut : **TERMINÉ**.

## 19. Rapport final — Endpoint 12

- Fichiers créés : `tests/test_zylo_liquid_alerts.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (`Alert`,
  nouveau), `app/modules/zylo_liquid/algorithms.py`
  (`evaluate_threshold_alarms`), `tests/test_zylo_liquid_algorithms.py`
  (Niveau 1, +5 cas), `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`
  (dont un appel dans `run_leak_test_for_tank` pour créer l'alerte fuite),
  cette documentation, `validation_log.md`.
- Migration : `fb5b32ada7ce_alert.py` (nouvelle table).
- Tests : 121/121 verts (`python -m pytest`), y compris les 108
  tests préexistants (non-régression) + 5 Niveau 1 + 8 Niveau 2/3.
- Vérification réelle : scénario complet rejoué contre le serveur de
  développement (mesure sous seuil → alerte → résolution → tentative de
  double résolution rejetée).
- Statut : **TERMINÉ**.

## 20. Rapport final — Endpoint 13

- Fichiers créés : `tests/test_zylo_liquid_network_snapshot.py`.
- Fichiers modifiés : `app/modules/zylo_liquid/{service,router}.py`,
  cette documentation, `validation_log.md`.
- Migration : aucune.
- Tests : 126/126 verts (`python -m pytest`), y compris les 121
  tests préexistants (non-régression) + 5 Niveau 2.
- Vérification réelle : suite `curl` (mesure la plus proche antérieure
  confirmée, cuve exclue sans mesure antérieure, date future → 422,
  module inactif → 403) contre le serveur de développement.
- Statut : **TERMINÉ**.
