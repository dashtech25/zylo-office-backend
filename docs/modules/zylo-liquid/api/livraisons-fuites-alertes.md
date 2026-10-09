# Endpoints 10 à 12 : livraisons, fuites, alertes

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
