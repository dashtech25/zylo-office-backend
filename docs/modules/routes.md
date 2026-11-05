# Routes du domaine modules

Document de référence des routes HTTP du domaine `app/modules_registry` (catalogue,
installation, activation, administration plateforme, réconciliation, audit).
Chaque ligne suit le code réel : la suite `tests/test_be061_documentation_modules.py`
refuse une route absente de ce tableau ou une ligne qui ne correspond plus à une route.

Lecture des colonnes :
- **Permission** : code exigé par `require_permission` ou `require_module_permission`, tel qu'il
  est lu par `tests/route_inventory.py`. « aucune » signifie qu'aucune garde de permission
  n'est posée sur la route.
- **Garde** : « appartenance » si une garde d'appartenance à l'organisation ciblée est posée,
  « sans appartenance » sinon.
- **Codes HTTP** : code de succès de la route, suivi des refus possibles selon QE-MOD-02 :
  401 session absente, 403 `PERMISSION_DENIED` ou `ACCESS_DENIED`, 404 tenant ou ressource
  hors périmètre, 409 garde d'état ou conflit, 422 donnée invalide.

Périmètre et conventions : [README du domaine](README.md) ; installation et cycle de vie :
[installation](installation.md).

## Catalogue et administration plateforme

| Méthode | Chemin | Permission | Garde | Codes HTTP | Handler |
|---|---|---|---|---|---|
| GET | `/api/v1/catalog/modules` | aucune (lecture publique du catalogue) | sans appartenance | 200 | `catalog_router.lister_modules` |
| GET | `/api/v1/catalog/modules/{slug}` | aucune (lecture publique de la fiche) | sans appartenance | 200, 404 | `catalog_router.lire_fiche` |
| GET | `/api/v1/modules` | aucune (lecture publique du catalogue) | sans appartenance | 200 | `router.list_modules` |
| POST | `/api/v1/admin/modules` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 201, 401, 403, 422 | `admin_router.creer_module` |
| GET | `/api/v1/admin/modules/{module_id}` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 200, 401, 403, 404 | `admin_router.lire_module` |
| POST | `/api/v1/admin/modules/{module_id}/versions` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 201, 401, 403, 404, 422 | `admin_router.creer_version` |
| POST | `/api/v1/admin/modules/{module_id}/versions/{version_id}/compatibility-evaluations` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 201, 401, 403, 404, 422 | `admin_router.evaluer_compatibilite` |
| POST | `/api/v1/admin/modules/{module_id}/versions/{version_id}/publish` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 200, 401, 403, 404, 409 | `admin_router.publier_version` |
| POST | `/api/v1/admin/modules/{module_id}/upgrade-plans` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 201, 401, 403, 404, 422 | `admin_router.planifier_mise_a_jour` |
| GET | `/api/v1/admin/reconciliations` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 200, 401, 403 | `reconciliation_router.lister_reconciliations` |
| POST | `/api/v1/admin/reconciliations/{reconciliation_id}/resolve` | aucune (console plateforme, QE-MOD-07) | sans appartenance | 200, 401, 403, 404, 409 | `reconciliation_router.resoudre_reconciliation` |

## Modules de l'organisation

| Méthode | Chemin | Permission | Garde | Codes HTTP | Handler |
|---|---|---|---|---|---|
| GET | `/api/v1/modules/organizations/{organization_id}` | aucune (lecture membre) | appartenance | 200, 401, 404 | `router.list_organization_modules` |
| POST | `/api/v1/modules/organizations/{organization_id}/activate` | `modules.module.manage` | appartenance | 200, 401, 403, 404, 409 | `router.activate` |
| POST | `/api/v1/modules/organizations/{organization_id}/deactivate` | `modules.module.manage` | appartenance | 200, 401, 403, 404, 409 | `router.deactivate` |
| GET | `/api/v1/modules/organizations/{organization_id}/zylo-liquid/protected-demo` | `identity.organization.manage` | appartenance | 200, 401, 403, 404 | `router.protected_demo` |
| GET | `/api/v1/organizations/current/modules` | aucune (lecture membre) | appartenance | 200, 401, 404 | `router.list_current_organization_modules` |
| GET | `/api/v1/organizations/current/modules/{module_id}/access` | aucune (lecture membre) | appartenance | 200, 401, 404 | `router.get_current_organization_module_access` |
| PUT | `/api/v1/organizations/current/modules/{module_id}/activation` | `modules.module.manage` | appartenance | 200, 401, 403, 404, 409 | `router.set_current_organization_module_activation` |
| GET | `/api/v1/organizations/{organization_id}/module-audit` | `organization.audit.read` | appartenance | 200, 401, 403, 404 | `audit_router.list_module_audit` |
| GET | `/api/v1/organizations/{organization_id}/modules/{module_id}` | `organization.module.read` | appartenance | 200, 401, 403, 404 | `router.lire_disponibilite_module` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/installations` | `organization.module.install` | appartenance | 201, 401, 403, 404, 409 | `router.installer_module` |
| GET | `/api/v1/organizations/{organization_id}/modules/{module_id}/installations/{operation_id}` | `organization.module.install` | appartenance | 200, 401, 403, 404 | `router.lire_operation_installation` |
| DELETE | `/api/v1/organizations/{organization_id}/modules/{module_id}/installation` | `organization.module.uninstall` | appartenance | 200, 401, 403, 404, 409 | `router.supprimer_installation_module` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/activation` | `organization.module.activate` | appartenance | 200, 401, 403, 404, 409 | `router.activer_module` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/deactivation` | `organization.module.activate` | appartenance | 200, 401, 403, 404, 409 | `router.desactiver_module` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/upgrades` | `organization.module.upgrade` | appartenance | 200, 401, 403, 404, 409, 422 | `router.mettre_a_jour_module` |
| GET | `/api/v1/organizations/{organization_id}/modules/{module_id}/permissions` | `organization.module.read` | appartenance | 200, 401, 403, 404 | `router.list_module_permissions` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/reactivations` | aucune | sans appartenance | 200, 401, 404, 409 | `router.reprendre_module` |
| POST | `/api/v1/organizations/{organization_id}/modules/{module_id}/suspensions` | aucune | sans appartenance | 200, 401, 404, 409 | `router.suspendre_module` |
