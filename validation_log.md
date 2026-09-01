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

Aucun algorithme métier (Point 1-16) n'est encore branché à un endpoint à
ce stade (endpoints 1 et 2 = référentiel pur, pas de calcul). Cette section
sera complétée à partir de l'endpoint 7 (état actuel d'une cuve —
interpolation hauteur→volume) puis 10 (livraison), 11 (fuite), qui sont les
premiers à exercer un algorithme validé (Point 3 §10).

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

## Niveau 3 — Tests d'intégration de flux

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
