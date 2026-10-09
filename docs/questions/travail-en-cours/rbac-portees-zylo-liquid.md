# Gardes de portée par station (rbac) : intégrer ou reprendre sur la base T-018 ?

- **État** : ouverte (2026-10-09). Non intégré.
- **Lot concerné** : B-L5 (`app/rbac/service.py` +156 lignes, `app/modules/zylo_liquid/permissions.py`, `app/shared/currency_router.py`, `app/shared/geo_router.py`, `tests/test_zylo_liquid_rbac_scope_guard.py`).

## Question

Faut-il intégrer les nouvelles gardes de portée (`require_permission_any_scope`, `require_permission_scoped`) et le passage des routeurs devise et géographie à `any_scope`, ou les reprendre sur la base de T-018 (rôles par module) et T-010 (isolation par organisation) déjà fusionnées ?

## Contexte

- `app/rbac/service.py` est modifié à la fois dans le snapshot (base `72dca7d`) et dans `remy` (T-021, T-022, T-027 et la suite). Conflit direct.
- `assign_role` et `unassign_role` sont modifiés dans le snapshot : ce sont des points d'autorisation sensibles.
- Les routeurs `currency_router` et `geo_router` passent de `require_permission(...)` à `require_permission_any_scope(...)`. Cela élargit l'accès : une permission sur une seule station suffit désormais pour lire un référentiel global. Ce changement n'est pas justifié dans le code du snapshot.
- Le test de garde de portée n'a pas été exécuté contre `remy`.

## Options

1. Intégrer tel quel après résolution de conflit : risque d'élargir l'accès aux référentiels globaux et de contourner T-010.
2. Reprendre les gardes sur la base de T-018 et T-010, en gardant les tests de portée du snapshot comme cahier des charges. Garder `require_permission` pour les référentiels globaux.
3. Ne rien reprendre et laisser les routes de station sans garde de portée (dette à inscrire dans `route_baseline_sans_permission.txt`).

## Recommandation vérifiée

Option 2. Vérifié : `remy` contient déjà `require_permission` et les tests `test_route_inventory.py` (la liste des routes sans garde de permission ne doit que diminuer). Le snapshot ne doit pas réintroduire de route sans garde.

## Décision attendue

- Valider l'option (1, 2 ou 3).
- Confirmer que `currency_router` et `geo_router` gardent la permission simple (sans portée).

## État d'avancement

- Aucun changement fait sur `remy` ni sur les branches wip.
