# Niveau 3 : tests d'intégration de flux

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

## Niveau 3 — Tests d'intégration de flux

### Scénario livraison — VALIDÉ le 2026-09-01

```
SCÉNARIO : Une livraison est détectée correctement de bout en bout
ÉTAPE 1 : Insertion d'une série de mesures réelles (445mm → 1298mm → stable 1293mm)
ÉTAPE 2 : Exécution de run_delivery_detection_for_tank (fonction testée
          directement, aucun endpoint HTTP ne la déclenche — Point 2 §3.3)
ÉTAPE 3 : GET /deliveries?tankId=... → 1 livraison, volumeLiters=10875
ÉTAPE 4 : GET /deliveries/{id} → détail identique
RÉSULTAT ATTENDU : ✓ conforme au calcul exact de Point 8 §8.6
```

Preuve : `tests/test_zylo_liquid_deliveries.py::test_delivery_detection_and_read_full_scenario`
+ rejoué contre serveur de développement réel (curl, endpoint 10).

### GET /api/v1/zylo-liquid/leak-events — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (fuite réelle) | 200 + `result:"anomaly"`, taux exact | 200, `leakRateLph=0.5` | ✓ |
| En dessous du seuil | `result:"normal"` | Confirmé | ✓ |
| Filtre par résultat | 200 + sous-ensemble filtré | 200, conforme | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

### GET /api/v1/zylo-liquid/leak-events/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + détail complet | 200, conforme | ✓ |
| Introuvable | 404 `leak_event_not_found` | 404 `leak_event_not_found` | ✓ |

Algorithmes validés séparément : voir Niveau 1 ci-dessus.
Preuve : `tests/test_zylo_liquid_leak_events.py` (7 cas, pytest réel) +
scénario complet rejoué contre serveur de développement.

### Scénario fuite — VALIDÉ le 2026-09-01

```
SCÉNARIO : Une fuite est détectée et classée correctement
ÉTAPE 1 : Insertion de deux mesures (début/fin d'une fenêtre de 8h,
          perte de 4L -> 0.5 L/H, sans variation eau/température)
ÉTAPE 2 : run_leak_test_for_tank (fonction testée directement, aucun
          endpoint HTTP ne la déclenche — station à l'arrêt, Point 10 §10.3)
ÉTAPE 3 : GET /leak-events?tankId=... -> 1 événement, result="anomaly",
          leakRateLph=0.5
ÉTAPE 4 : GET /leak-events/{id} -> détail identique
RÉSULTAT ATTENDU : ✓ conforme au calcul exact (0.5 > seuil 0.38 L/H)
```

Preuve : `tests/test_zylo_liquid_leak_events.py::test_leak_test_detects_anomaly_full_scenario`
+ rejoué contre serveur de développement réel.

### GET/PATCH /api/v1/zylo-liquid/alerts — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (alerte niveau bas) | 200 + alerte active | 200, `type:"level_low"`, `status:"active"` | ✓ |
| Résolution | 200, `status:"resolved"`, `resolvedAt` renseigné | Confirmé | ✓ |
| Double résolution | 409 `alert_already_resolved` | 409 `alert_already_resolved` | ✓ |
| Anti-spam (même condition réévaluée) | Aucune nouvelle alerte créée | 0 créée | ✓ |
| Sonde déconnectée | Alerte `sensor_offline`, pas de comparaison de seuils | Confirmé | ✓ |
| Déclencheur fuite | Alerte `leak` créée automatiquement par l'endpoint 11 | Confirmé | ✓ |
| Filtre type/statut | 200 + sous-ensemble filtré | 200, conforme | ✓ |
| Introuvable | 404 `alert_not_found` | 404 `alert_not_found` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : voir Niveau 1 ci-dessus
(`evaluate_threshold_alarms`).
Preuve : `tests/test_zylo_liquid_alerts.py` (8 cas, pytest réel) +
scénario complet rejoué contre serveur de développement.

### Scénario alerte — VALIDÉ le 2026-09-01

```
SCÉNARIO : Une alerte de niveau bas est détectée et résolue correctement
ÉTAPE 1 : Mesure sous le seuil bas configuré (195mm < 200mm)
ÉTAPE 2 : run_alert_evaluation_for_tank crée une alerte active level_low
ÉTAPE 3 : GET /alerts?tankId=... -> 1 alerte active
ÉTAPE 4 : PATCH /alerts/{id} -> résolue, resolvedAt renseigné
ÉTAPE 5 : PATCH à nouveau -> 409 alert_already_resolved
RÉSULTAT ATTENDU : ✓ conforme au cycle de vie actif→résolue (Point 2 §4.6)
```

Preuve : `tests/test_zylo_liquid_alerts.py::test_low_level_alert_full_scenario`
+ rejoué contre serveur de développement réel.

### GET /api/v1/zylo-liquid/network/snapshot — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | Dernière mesure ≤ instant demandé utilisée, jamais une postérieure | Confirmé (500mm/10000L retenu, pas 1000mm/20000L postérieur) | ✓ |
| Cuve sans mesure antérieure | Exclue du total (jamais 0) | 200, `products=[]`, `totalVolumeLiters=0` | ✓ |
| Date future | 422 `snapshot_date_in_future` | 422 `snapshot_date_in_future` | ✓ |
| Paramètre `at` manquant | 422 (obligatoire, Point 2 §5.4) | 422 | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : réutilisation de
`interpolate_height_to_volume` (déjà validé, endpoint 7) — aucun nouveau
calcul.
Preuve : `tests/test_zylo_liquid_network_snapshot.py` (5 cas, pytest réel)
+ suite `curl` réelle contre serveur de développement.

### POST/GET/PATCH /api/v1/currencies — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (création/liste) | 201/200 | Confirmé | ✓ |
| Code dupliqué | 409 `currency_code_already_used` | 409 `currency_code_already_used` | ✓ |
| Format invalide (pas 3 lettres majuscules) | 422 | 422 | ✓ |
| Modification (jamais le code) | 200, `code` inchangé | 200, conforme | ✓ |
| Introuvable | 404 `currency_not_found` | 404 `currency_not_found` | ✓ |
| Non authentifié | 401 | 401 | ✓ |

### POST/GET /api/v1/exchange-rates — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (création/liste) | 201/200 | Confirmé | ✓ |
| Devise source = devise cible | 422 `exchange_rate_same_currency` | 422 `exchange_rate_same_currency` | ✓ |
| Doublon (même paire, même date) | 409 `exchange_rate_already_exists` | 409 `exchange_rate_already_exists` | ✓ |
| Taux négatif | 422 (validation) | 422 | ✓ |

Algorithmes validés séparément : N/A (référentiel Core pur, aucun calcul).
Preuve : `tests/test_shared_currency.py` (10 cas, pytest réel) + suite
`curl` réelle contre serveur de développement.

### POST/GET/PATCH /api/v1/zylo-liquid/prices — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Création, devise explicite | 201 + ligne créée | 201, conforme | ✓ |
| Création, devise résolue automatiquement | 201, `currencyId` = devise du pays de la station | 201, conforme | ✓ |
| Ville non associée, devise absente | 422 `station_currency_not_resolvable` | 422 `station_currency_not_resolvable` | ✓ |
| Conflit de période (même station+produit+date) | 409 `price_conflict_same_period` | 409 `price_conflict_same_period` | ✓ |
| Date future | 201 + `isFuture:true` (jamais rejeté) | 201, `isFuture:true` | ✓ |
| Correction ciblée (montant/motif) | 200, station/produit/période inchangés | 200, conforme | ✓ |
| Correction, ligne introuvable | 404 `price_history_not_found` | 404 `price_history_not_found` | ✓ |
| Liste filtrée par station | 200 + sous-ensemble | 200, conforme | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : N/A (résolution de référentiel, pas un
calcul physique).
Preuve : `tests/test_zylo_liquid_prices.py` (9 cas, pytest réel) + suite
`curl` réelle contre serveur de développement.

### Extension valeur monétaire (current-state, network/summary, network/snapshot) — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Prix applicable | `monetaryValue` = volume net × prix | 200, `14 600 000` (20000L × 730) confirmé en réel | ✓ |
| Aucun prix applicable | `monetaryValue: null`, `monetaryValueNotCalculableReason:"no_applicable_price"` (jamais 0) | Confirmé | ✓ |
| Prix planifié dans le futur | Jamais utilisé pour l'instant présent | Confirmé (prix antérieur retenu, pas le prix futur) | ✓ |
| `network/summary`, une seule devise | Total monétaire par produit calculé | 200, conforme | ✓ |
| `network/summary`, une cuve sans prix | `totalMonetaryValue: null`, `monetaryValueNotCalculableReason:"incomplete_pricing"` (jamais une somme partielle) | Confirmé | ✓ |
| `network/snapshot`, prix applicable à la date | Même règle que `current-state`, à une date passée | Confirmé | ✓ |

Algorithmes validés séparément : réutilisation complète de la résolution
de prix (`_resolve_applicable_price`) et des volumes déjà validés
(endpoints 7, 9, 13) — aucun nouveau calcul physique.
Preuve : `tests/test_zylo_liquid_monetary_value.py` (6 cas, pytest réel)
+ suite `curl` réelle contre serveur de développement.

---

**Les 16 endpoints du Niveau 1 Zylo Liquid sont tous VALIDÉS — voir le
tableau de suivi global ci-dessous.**

Aucun scénario métier de bout en bout (livraison, fuite) n'est encore
implémenté à ce stade — les endpoints 1 et 2 sont du référentiel pur, sans
flux de mesures. Cette section sera complétée à partir des endpoints 10
(livraisons) et 11 (fuites), une fois le moteur de calcul (endpoint 7,
état actuel d'une cuve) construit et le simulateur capable d'injecter des
mesures réelles dans `TankMeasurement`.

---
