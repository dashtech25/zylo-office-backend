# Suivi global de validation

> Découpé depuis [`docs/archive/zylo-liquid/validation_log.md`](../../../archive/zylo-liquid/validation_log.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
| 13 | `/network/snapshot` (GET) | ✓ (réutilisé) | ✓ (1 endpoint, tous cas) | N/A | **VALIDÉ** |
| 14 | `/currencies`, `/exchange-rates` (Core) | N/A | ✓ (5 endpoints, tous cas) | N/A | **VALIDÉ** |
| 15 | `/zylo-liquid/prices` (POST/GET/PATCH) | N/A | ✓ (4 endpoints, tous cas) | N/A | **VALIDÉ** |
| 16 | Valeur monétaire (extension 7/9/13) | N/A | ✓ (6 tests, tous cas) | N/A | **VALIDÉ** |
