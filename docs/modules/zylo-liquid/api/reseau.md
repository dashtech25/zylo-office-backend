# Endpoints 9 et 13 : vue réseau et snapshot

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
