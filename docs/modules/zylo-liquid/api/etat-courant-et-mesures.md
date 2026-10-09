# Endpoints 7 et 8 : état courant et historique des mesures

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
