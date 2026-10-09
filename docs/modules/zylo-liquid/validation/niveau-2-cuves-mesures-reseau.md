# Niveau 2 : contrats d'endpoint, cuves et mesures

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
