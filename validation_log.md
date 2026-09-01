# Journal de validation — Zylo Liquid Niveau 1

> Journal de bord tenu à jour à chaque endpoint, selon la méthodologie
> « Point 4 — Valider une API comme les titans » (adoptée à partir de
> l'endpoint 2, appliquée rétroactivement à l'endpoint 1) : une
> fonctionnalité n'est pas validée parce qu'elle est codée, mais parce
> qu'elle est prouvée, à trois niveaux — algorithme seul (Niveau 1),
> contrat d'endpoint (Niveau 2), scénario métier de bout en bout
> (Niveau 3). Toute preuve consignée ici est une exécution réelle (pytest
> et/ou curl contre un serveur réel), jamais une relecture de code.

---

## Niveau 1 — Tests unitaires algorithmiques

### interpolate_height_to_volume — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Table Point 2 §2.4, H=1073mm | 19729 L (±1) | 19729 L | ✓ (PASS) |
| Point exact de la table | H=1050mm | 19200 L | 19200 L | ✓ |
| Hors plage, en dessous | H=-50mm | Borné au premier point (0 L) | 0 L | ✓ |
| Hors plage, au dessus | H=5000mm | Borné au dernier point (40000 L) | 40000 L | ✓ |
| Aucune calibration | Table vide | `None` (jamais un volume inventé) | `None` | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 2 —
La table de calibration.md` §2.4. Preuve : `tests/test_zylo_liquid_algorithms.py`.

### correct_volume_to_reference_temperature — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | V=19729L, T=35°C, α=0.00085 (Gasoil) | 19394 L (±1) | 19394 L | ✓ (PASS) |
| À la température de référence | V=19729L, T=15°C | Inchangé (19729 L) — **FAIL si différent** | 19729 L | ✓ |
| Sous la référence | V=10000L, T=5°C, α=0.00120 | Volume corrigé > volume mesuré (contraction) | Confirmé (10060 L) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 5 —
Température et densité.md` §5.2. Preuve : `tests/test_zylo_liquid_algorithms.py`.

### detect_deliveries — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Scénario Point 8 §8.5/§8.8 (445→1298→stable 1293) | 1 livraison, start=445mm, end=1293mm | Confirmé | ✓ (PASS) |
| Volume brut combiné à l'interpolation | calibration(1293)-calibration(445) | 10875 L (Point 8.6, sans correction ventes) | 10875 L | ✓ |
| Oscillation sous le seuil (50mm) | Hausse de 20mm | Aucune livraison détectée | `[]` | ✓ (FAIL attendu si détectée à tort) |
| Plateau bref pendant la hausse (<15min) | Hausse→plateau 5min→reprise→fin réelle | 1 seule livraison, sur la vraie fin | Confirmé | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 8 —
Détection de livraison (version corrigée et complète).md` §8.3, §8.5, §8.6,
§8.8. Seuils confirmés par Point 3 §10 (code Odoo audité : hausse ≥50mm,
stabilité <5mm, confirmation 15min — jamais les valeurs d'exemple
génériques 500L/30min de §8.6). Preuve : `tests/test_zylo_liquid_algorithms.py`.

### compute_net_corrected_volume / compute_leak_rate_lph / is_leak_detected — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Seuil EPA (frontière) | 0.38 exactement | Pas de fuite (strictement supérieur requis) | Confirmé | ✓ |
| Seuil EPA (au-dessus) | 0.39 | Fuite détectée | Confirmé (PASS) | ✓ |
| Seuil EPA (en dessous) | 0.37 | Pas de fuite | Confirmé (FAIL attendu si détectée à tort) | ✓ |
| Taux direct (exemple Point 10 §10.3) | ΔV=9.5L/24h | ≈0.396 L/H, fuite détectée | Confirmé | ✓ |
| Faux positif eau (condensation) | Eau +2mm entre début et fin | Volume net carburant diminue en cohérence avec l'eau, pas une fuite fictive isolée | Confirmé | ✓ |
| Faux positif thermique (exemple documenté) | Refroidissement 2°C, cuve 18385L Gasoil α=0.00085 | Sans correction : ~31L/H « fuite » fictive détectée (FAIL) ; avec correction : ≈0, pas de fuite (PASS) | Confirmé (les deux résultats) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 10 —
Détection de fuite.md`, section finale (« Correction de l'algorithme du
point 10 » — version EPA corrigée, pas l'algorithme initial simplifié de
§10.3). Seuil 0.38 L/H confirmé §10.4 (standard EPA). Preuve :
`tests/test_zylo_liquid_algorithms.py`.

### evaluate_threshold_alarms — VALIDÉ le 2026-09-01

| Cas | Entrée | Attendu | Obtenu | Statut |
|-----|--------|---------|--------|--------|
| Cas de référence exact | Point 13 §13.5 : H_carburant=195mm, H_eau=0mm, Low_alarm=200mm | `["level_low"]` | Confirmé | ✓ (PASS) |
| Niveau haut supersede la pré-alarme | H_net=950, alarm=900, alert=800 | `["level_high"]` uniquement | Confirmé (FAIL attendu si les deux) | ✓ |
| Pré-alarme seule | H_net=850, alarm=900, alert=800 | `["level_high_pre_alarm"]` | Confirmé | ✓ |
| Eau indépendante du niveau | Niveau normal + eau au-dessus du seuil | `["water"]` uniquement | Confirmé | ✓ |
| Plage normale | Toutes valeurs sous les seuils | `[]` | Confirmé (FAIL attendu si alerte à tort) | ✓ |

Source exacte : `nouveau-station-simulator/nouveau-zylo-liquid/Point 13 —
Alarmes.md` §13.4-13.5. Preuve : `tests/test_zylo_liquid_algorithms.py`.

Le prochain algorithme à exercer sera défini au moment de construire
l'endpoint suivant (snapshot réseau, item 13).

---

## Niveau 2 — Contract tests d'endpoint

### POST /api/v1/zylo-liquid/fuel-products — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (création) | 201 + produit créé | 201 + `{"id":...,"name":"Super","code":"SP",...}` | ✓ |
| Code déjà utilisé (même organisation) | 409 `fuel_product_code_already_used` | 409 `fuel_product_code_already_used` | ✓ |
| Permission manquante | 403 `permission_denied` | 403 `permission_denied` (avant correction RBAC), puis 201 après activation+octroi automatique | ✓ |
| Non authentifié | 401 | 401 | ✓ |

Algorithmes validés séparément : N/A (référentiel pur, aucun calcul).
Preuve : `tests/test_zylo_liquid_fuel_products.py` (8 cas, pytest réel) +
suite `curl` contre serveur de développement (voir §8 de
`docs/modules/zylo-liquid/phase-2-api.md`).

### GET /api/v1/zylo-liquid/fuel-products/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + produit | 200 + produit | ✓ |
| Introuvable | 404 `fuel_product_not_found` | 404 `fuel_product_not_found` | ✓ |
| Autre organisation (isolation) | 404 (jamais 403, ne révèle pas l'existence) | 404 (liste vide côté autre organisation, testé via `GET` liste) | ✓ |
| Permission manquante | 403 `permission_denied` | 403 `permission_denied` | ✓ |

### GET /api/v1/zylo-liquid/fuel-products — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (pagination) | 200 + `{"data","meta"}` | 200 + total=1 | ✓ |
| Isolation multi-tenant | 0 résultat pour une autre organisation | `meta.total == 0` | ✓ |

### PATCH /api/v1/zylo-liquid/fuel-products/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + champs modifiés | 200, `currentPriceFcfa` et `active` modifiés, `code` inchangé | ✓ |
| Introuvable | 404 `fuel_product_not_found` | 404 `fuel_product_not_found` | ✓ |

---

### POST /api/v1/zylo-liquid/stations — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 201 + station créée, statut "active" | 201 + `{"status":"active","activeTankCount":0,...}` | ✓ |
| Ville inconnue | 422 `city_not_found` | 422 `city_not_found` | ✓ |
| Code déjà utilisé (même organisation) | 409 `station_code_already_used` | 409 `station_code_already_used` | ✓ |
| Permission manquante / module inactif | 403 `module_inactive` (module non activé) | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : N/A.
Preuve : `tests/test_zylo_liquid_stations.py` (8 cas, pytest réel) +
suite `curl` réelle contre serveur de développement (cas 1 à 4 ci-dessous).

```text
CAS 1 — normal            → HTTP 201, station créée
CAS 2 — station inconnue  → HTTP 404 station_not_found
CAS 3 — ville inconnue    → HTTP 422 city_not_found
CAS 4 — autre tenant      → HTTP 404 station_not_found (jamais 403 — isolation
                             stricte, ne révèle pas l'existence à un autre tenant,
                             conforme à Point 2 §1.1 "Cas d'erreur")
```

### GET /api/v1/zylo-liquid/stations/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + station | 200 + station | ✓ |
| Introuvable | 404 `station_not_found` | 404 `station_not_found` | ✓ |
| Autre tenant | 404 (jamais 403) | 404 `station_not_found` | ✓ (preuve curl ci-dessus, CAS 4) |

### GET /api/v1/zylo-liquid/stations — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (pagination) | 200 + `{"data","meta"}` | 200, total=1 | ✓ |
| Isolation multi-tenant | 0 résultat pour une autre organisation | vérifié (pytest) | ✓ |

### PATCH /api/v1/zylo-liquid/stations/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + champs modifiés, `status` inchangé | 200, `name`/`phone` modifiés, `status` toujours "active" | ✓ |
| Introuvable | 404 `station_not_found` | 404 `station_not_found` | ✓ |

### POST /api/v1/zylo-liquid/stations/{id}/deactivate — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200, `status` → "inactive" | 200, `status`="inactive" | ✓ |
| Déjà désactivée | 409 `station_already_inactive` | 409 `station_already_inactive` | ✓ |
| Historique préservé | GET après désactivation toujours 200 | 200 | ✓ |

### POST /api/v1/zylo-liquid/stations/{id}/reactivate — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200, `status` → "active" | 200, `status`="active" | ✓ |
| Déjà active | 409 `station_already_active` | 409 `station_already_active` | ✓ |

---

### POST /api/v1/zylo-liquid/tanks — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (produit existant) | 201 + cuve créée | 201 + `{"fuelProductId":...,"heightAlarmMm":2800,...}` | ✓ |
| Cas normal (produit créé à la volée) | 201 + cuve créée + nouveau `fuelProductId` | 201, produit confirmé existant ensuite via `GET /fuel-products/{id}` | ✓ |
| Station introuvable | 404 `station_not_found` | 404 `station_not_found` | ✓ |
| Sélection produit invalide (ni l'un ni l'autre, ou les deux) | 422 `fuel_product_selection_invalid` | 422 `fuel_product_selection_invalid` | ✓ |
| Numéro de cuve déjà utilisé dans la station | 409 `tank_number_already_used` | 409 `tank_number_already_used` | ✓ |
| Module inactif sur une autre organisation | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : N/A (aucun calcul à ce stade — la
conversion mm→litres n'intervient qu'à partir de l'endpoint 7).
Preuve : `tests/test_zylo_liquid_tanks.py` (8 cas, pytest réel) + suite
`curl` réelle contre serveur de développement (4 cas minimum ci-dessus).

### GET /api/v1/zylo-liquid/tanks/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + cuve | 200 + cuve | ✓ |
| Introuvable | 404 `tank_not_found` | 404 `tank_not_found` | ✓ |
| Autre tenant (cuve rattachée à une station d'une autre organisation) | 404 (jamais 403) | 404 `tank_not_found` | ✓ |

### GET /api/v1/zylo-liquid/tanks — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (filtre par station, pagination) | 200 + `{"data","meta"}` | 200, total=1 | ✓ |

### PATCH /api/v1/zylo-liquid/tanks/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (modification d'un seuil) | 200 + seuil modifié | 200, `heightAlarmMm` modifié | ✓ |

---

### POST /api/v1/zylo-liquid/tank-sensor-mappings — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 201 + association créée | 201 + `{"hkSensorId":999001,"measurementType":"product_level","active":true,...}` | ✓ |
| Numéro de série inconnu du registre Holykell | 422 `sensor_not_found_in_holykell_registry` | 422 `sensor_not_found_in_holykell_registry` | ✓ |
| Cuve introuvable | 404 `tank_not_found` | 404 `tank_not_found` | ✓ |
| Association déjà active pour cette cuve+type | 409 `tank_sensor_mapping_already_active` | 409 `tank_sensor_mapping_already_active` | ✓ |
| Module inactif sur une autre organisation | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Cas supplémentaire spécifique à cet endpoint : un même numéro de série
porte plusieurs capteurs logiques (product_level/water_level/temperature)
— la résolution doit choisir le bon `hkSensorId` selon `measurementType`,
jamais le premier trouvé. Vérifié (`test_create_tank_sensor_mapping_resolves_correct_channel_by_measurement_type`).

Algorithmes validés séparément : N/A (résolution de référentiel, pas un
algorithme métier de Point 1-16).
Preuve : `tests/test_zylo_liquid_tank_sensor_mappings.py` (8 cas, pytest
réel) + suite `curl` réelle contre serveur de développement (4 cas
minimum ci-dessus).

### GET /api/v1/zylo-liquid/tank-sensor-mappings — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (filtre par cuve) | 200 + `{"data","meta"}` | 200, total=1 | ✓ |

### POST /api/v1/zylo-liquid/tank-sensor-mappings/{id}/close — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200, `active`→false, `validUntil` renseigné | 200, conforme | ✓ |
| Déjà close | 409 `tank_sensor_mapping_already_closed` | 409 `tank_sensor_mapping_already_closed` | ✓ |
| Introuvable | 404 `tank_sensor_mapping_not_found` | 404 `tank_sensor_mapping_not_found` | ✓ |

---

### PUT /api/v1/zylo-liquid/tanks/{id}/calibration-points — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (remplacement complet) | 200 + points créés triés par hauteur | 200, `pointCount=3`, triés [0,1000,2000] | ✓ |
| Cuve introuvable | 404 `tank_not_found` | 404 `tank_not_found` | ✓ |
| Hauteur maximale dépasse la cuve | 422 `calibration_height_exceeds_tank` | 422 `calibration_height_exceeds_tank` | ✓ |
| Table non monotone (volume qui diminue) | 422 `calibration_table_not_monotonic` | 422 `calibration_table_not_monotonic` | ✓ |
| Liste vide | 422 (validation) | 422 | ✓ |
| Module inactif sur une autre organisation | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Cas supplémentaire : un second `PUT` remplace intégralement la table
précédente, jamais une fusion (`test_replace_calibration_points_is_a_full_replacement`).

Algorithmes validés séparément : N/A (validation de cohérence, pas
l'algorithme d'interpolation lui-même — celui-ci sera testé à l'endpoint 7).
Preuve : `tests/test_zylo_liquid_tank_calibration_points.py` (8 cas, pytest
réel) + suite `curl` réelle contre serveur de développement (4 cas
minimum ci-dessus).

### GET /api/v1/zylo-liquid/tanks/{id}/calibration-points — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + liste triée | 200 | ✓ |
| Aucune table chargée | 200 + liste vide (jamais une erreur) | 200, `[]` | ✓ |

---

### GET /api/v1/zylo-liquid/holykell-accounts/{id}/sync-status — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (statut réussi) | 200 + `lastSyncStatus:"success"` | 200, conforme | ✓ |
| Statut échoué avec message | 200 + `lastSyncError` renseigné | 200, conforme | ✓ |
| Compte introuvable | 404 `holykell_account_not_found` | 404 `holykell_account_not_found` | ✓ |
| Compte d'une autre organisation | 404 (isolation stricte) | 404 `holykell_account_not_found` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : N/A (lecture pure).
Écart de contrat documenté (`docs/modules/zylo-liquid/phase-2-api.md` §Endpoint 6) :
Point 2 §2.1 affirmait une contrainte d'unicité par organisation qui
n'existe pas réellement en base — vérifié, non corrigé arbitrairement.
Preuve : `tests/test_zylo_liquid_holykell_sync_status.py` (5 cas, pytest
réel) + suite `curl` réelle contre serveur de développement.

---

### GET /api/v1/zylo-liquid/tanks/{id}/current-state — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Aucun capteur configuré | 200, `sensorStatus:"not_configured"`, tous les volumes `null` | 200, conforme | ✓ |
| Mesure normale (avec calibration) | 200, `volumeLiters` calculé par interpolation | 200, `heightMm=1073`, `volumeLiters≈21460` | ✓ |
| Eau + correction thermique | `volumeLiters` = brut - eau ; `volumeLiters15C` corrigé | 200, `volumeLiters=20460`, `volumeLiters15C≈20121` | ✓ |
| Sonde déconnectée (`hkLastStatus=0`) | `sensorStatus:"offline"` | 200, `sensorStatus:"offline"` | ✓ |
| Sans table de calibration | `volumeLiters:null`, `volumeNotCalculableReason:"no_calibration_table"`, `heightMm` brut renvoyé | 200, conforme | ✓ |
| Cuve introuvable | 404 `tank_not_found` | 404 `tank_not_found` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : voir Niveau 1 ci-dessus
(`interpolate_height_to_volume`, `correct_volume_to_reference_temperature`).
Preuve : `tests/test_zylo_liquid_current_state.py` (9 cas, pytest réel) +
suite `curl` réelle contre serveur de développement (4 cas minimum).

### GET /api/v1/zylo-liquid/stations/{id}/current-state — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + liste des cuves actives de la station | 200, conforme | ✓ |
| Station introuvable | 404 `station_not_found` | 404 `station_not_found` | ✓ |

---

### GET /api/v1/zylo-liquid/tanks/{id}/measurements — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + liste triée par `measuredAt` croissant, volume converti | 200, conforme | ✓ |
| Filtre `fromDate`/`toDate` | 200 + sous-ensemble filtré | 200, conforme | ✓ |
| Plage de dates invalide (`fromDate > toDate`) | 422 `invalid_date_range` | 422 `invalid_date_range` | ✓ |
| Aucun capteur jamais associé | 200 + liste vide (jamais une erreur) | 200, `total=0` | ✓ |
| Remplacement de sonde | L'historique de l'ancienne sonde reste visible | 200, `total=2` (ancienne + nouvelle sonde) | ✓ |
| Cuve introuvable | 404 `tank_not_found` | 404 `tank_not_found` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : réutilisation de
`interpolate_height_to_volume` (déjà validé, endpoint 7) — aucun nouveau
test Niveau 1 nécessaire.
Preuve : `tests/test_zylo_liquid_tank_measurements.py` (7 cas, pytest
réel) + suite `curl` réelle contre serveur de développement.

---

### GET /api/v1/zylo-liquid/network/summary — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (2 produits, 2 stations) | 200 + totaux par produit + total général | 200, `totalVolumeLiters=30000` (20000+10000) | ✓ |
| Cuve sans volume calculable | Exclue du total (jamais 0) | 200, `products=[]`, `totalVolumeLiters=0` | ✓ |
| Isolation multi-tenant | Totaux limités à l'organisation connectée | 200, conforme | ✓ |
| Période demandée (`fromDate`/`toDate`) | 422 `historical_network_summary_not_supported` (contradiction de sources documentée, non résolue arbitrairement) | 422 `historical_network_summary_not_supported` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

Algorithmes validés séparément : réutilisation de `get_tank_current_state`
(déjà validé, endpoint 7) — aucun nouveau calcul.
Preuve : `tests/test_zylo_liquid_network_summary.py` (5 cas, pytest réel) +
suite `curl` réelle contre serveur de développement.

---

### GET /api/v1/zylo-liquid/deliveries — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal (après détection) | 200 + livraison avec volume exact | 200, `volumeLiters=10875` | ✓ |
| Filtre par cuve/date | 200 + sous-ensemble filtré | 200, conforme | ✓ |
| Plage de dates invalide | 422 `invalid_date_range` | 422 `invalid_date_range` | ✓ |
| Module inactif | 403 `module_inactive` | 403 `module_inactive` | ✓ |

### GET /api/v1/zylo-liquid/deliveries/{id} — VALIDÉ le 2026-09-01

| Cas | Attendu | Obtenu | Statut |
|-----|---------|--------|--------|
| Cas normal | 200 + détail complet | 200, conforme | ✓ |
| Introuvable | 404 `delivery_not_found` | 404 `delivery_not_found` | ✓ |

Algorithmes validés séparément : voir Niveau 1 ci-dessus (`detect_deliveries`
+ `interpolate_height_to_volume`, déjà validé endpoint 7).
Preuve : `tests/test_zylo_liquid_deliveries.py` (6 cas, pytest réel) +
scénario complet rejoué contre serveur de développement.

---

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

Aucun scénario métier de bout en bout (livraison, fuite) n'est encore
implémenté à ce stade — les endpoints 1 et 2 sont du référentiel pur, sans
flux de mesures. Cette section sera complétée à partir des endpoints 10
(livraisons) et 11 (fuites), une fois le moteur de calcul (endpoint 7,
état actuel d'une cuve) construit et le simulateur capable d'injecter des
mesures réelles dans `TankMeasurement`.

---

## Suivi global

| # | Endpoint | Niveau 1 | Niveau 2 | Niveau 3 | Statut |
|---|---|---|---|---|---|
| 1 | `/fuel-products` (POST/GET/PATCH) | N/A | ✓ (4 endpoints, tous cas) | N/A | **VALIDÉ** |
| 2 | `/stations` (POST/GET/PATCH/deactivate/reactivate) | N/A | ✓ (5 endpoints, tous cas) | N/A | **VALIDÉ** |
| 3 | `/tanks` (POST/GET/PATCH) | N/A | ✓ (4 endpoints, tous cas) | N/A | **VALIDÉ** |
| 4 | `/tank-sensor-mappings` (POST/GET/close) | N/A | ✓ (3 endpoints, tous cas) | N/A | **VALIDÉ** |
| 5 | `/tanks/{id}/calibration-points` (PUT/GET) | N/A | ✓ (2 endpoints, tous cas) | N/A | **VALIDÉ** |
| 6 | `/holykell-accounts/{id}/sync-status` (GET) | N/A | ✓ (1 endpoint, tous cas) | N/A | **VALIDÉ** |
| 7 | `/tanks/{id}/current-state`, `/stations/{id}/current-state` (GET) | ✓ (2 algorithmes, 8 tests) | ✓ (2 endpoints, tous cas) | N/A | **VALIDÉ** |
| 8 | `/tanks/{id}/measurements` (GET) | ✓ (réutilisé) | ✓ (1 endpoint, tous cas) | N/A | **VALIDÉ** |
| 9 | `/network/summary` (GET) | ✓ (réutilisé) | ✓ (1 endpoint, tous cas) | N/A | **VALIDÉ** |
| 10 | `/deliveries` (GET) | ✓ (4 tests) | ✓ (2 endpoints, tous cas) | ✓ (scénario complet) | **VALIDÉ** |
| 11 | `/leak-events` (GET) | ✓ (6 tests) | ✓ (2 endpoints, tous cas) | ✓ (scénario complet) | **VALIDÉ** |
| 12 | `/alerts` (GET/PATCH) | ✓ (5 tests) | ✓ (3 endpoints, tous cas) | ✓ (scénario complet) | **VALIDÉ** |
