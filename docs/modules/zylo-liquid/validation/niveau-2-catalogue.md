# Niveau 2 : contrats d'endpoint, catalogue

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
