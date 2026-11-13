# Endpoint 1 : produits carburant (`fuel-products`)

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
