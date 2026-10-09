# IAM par module : ordre des tâches de la priorité n°1

Ordre demandé : orga, puis utilisateurs, puis affectation par module, puis droits effectifs. Les dépendances listées sont les prérequis techniques retenus après décision du coordinateur. Une contrainte technique impose de placer le modèle de rôles par module (T-018) avant la création d'utilisateurs (T-021) : il est donc rangé à l'étape 5, et son nom de section reste « affectation » pour ne pas le perdre.

| Ordre | ID | Étape | Dépendances techniques réelles | Fichiers touchés |
|---|---|---|---|---|
| 1 | T-010 | Orga : isolation inter-organisations | aucune | `app/rbac/dependencies.py`, `app/rbac/service.py`, `app/rbac/router.py`, `app/identity/router.py` et `service.py`, `app/modules_registry/router.py` et `service.py`, `app/billing/router.py` |
| 2 | T-019 | Orga : garde-fous IAM | T-010 (gardes d'isolation étendus) | `app/rbac/service.py`, `app/billing/router.py` et `service.py`, `app/identity/router.py` et `schemas.py`, `app/core/security.py` |
| 3 | T-036 | Socle : registre de seeders et contrats | aucune | `.importlinter`, `app/modules_registry/service.py`, `app/shared/permissions.py` |
| 4 | T-007 | Socle : droit du rôle manager (décision client) | aucune | `app/modules/zylo_liquid/roles_seed.py`, `seed.py` |
| 5 | T-018 | Affectation : rôles par module (modèle, prérequis de T-021) | T-007, T-019, T-036 | `app/rbac/models.py` et migration, `app/rbac/service.py`, `app/rbac/router.py`, `app/modules_registry/service.py` |
| 6 | T-012 | Utilisateurs : limitation de débit auth | aucune | `app/auth/router.py`, `app/auth/service.py`, `app/core/config.py` |
| 7 | T-013 | Utilisateurs : politique de mot de passe et e-mail | T-012 (limitation de l'inscription) | `app/auth/schemas.py`, `app/auth/service.py`, `app/identity/service.py`, `src/shared/lib/validation.ts` |
| 8 | T-030 | Front : coquille unique (prérequis de T-024 et T-025) | aucune | `src/core/layout/ModuleShell.tsx`, `CoreProviders.tsx`, `src/app/(app)/layout.tsx` |
| 9 | T-021 | Utilisateurs : création via API, statut `pending` | T-013, T-018, T-019 | `app/identity/router.py`, `service.py`, `schemas.py`, `permissions.py`, `app/core/security.py` |
| 10 | T-024 | Utilisateurs : écran de création | T-013, T-021, T-030 | `src/app/(app)/users/page.tsx`, `src/core/screens/UsersScreen.tsx`, `src/core/rbac/PermissionContext.tsx` |
| 11 | T-022 | Affectation : API par module | T-018, T-019, T-021 | `app/rbac/router.py`, `app/rbac/service.py`, `app/modules_registry/service.py` |
| 12 | T-025 | Affectation : écrans par module | T-022, T-024, T-030 | `src/core/rbac/PermissionContext.tsx`, `src/core/api/rbac.ts`, `src/modules/zylo-liquid/screens/`, `ZyloTankerShell.tsx` |
| 13 | T-023 | Droits effectifs : matrice et inventaire des routes | T-010, T-019 (parallélisable dès l'étape 2) | `tests/test_route_inventory.py`, `tests/test_authorization_matrix.py` |
| 14 | T-046 | Droits effectifs : fixtures e2e isolées | aucune | `e2e/fixtures/`, `e2e/global-setup.ts`, `playwright.config.ts` |
| 15 | T-047 | Droits effectifs : accès interdit cross-tenant | T-010, T-022, T-046 | `e2e/acces-interdit.spec.ts`, `e2e/cross-tenant.spec.ts`, `tests/test_e2e_api_acces.py` |
| 16 | T-026 | Droits effectifs : parcours E2E socle | T-024, T-025, T-046 | `e2e/proprietaire-socle-utilisateurs-modules.spec.ts` |

Chemin critique IAM : T-010, T-019, T-018, T-021, T-022, T-025, T-026 (7 tâches, niveaux 0 à 6).

Hors de cette liste : T-050 (décision client), T-048 et T-049 (dépendent de T-020, sessions, hors priorité n°1).
