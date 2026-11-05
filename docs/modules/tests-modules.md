# Tests transverses des routes de modules (BE-060)

Fichier de test : `tests/test_be060_suite_refus_isolation_modules.py`.

## Ce que la suite prouve

La suite parcourt l'inventaire réel de l'application (`tests/route_inventory.py`) et
retient les routes des familles de modules (BE-042 à BE-059) :

- `/api/v1/admin/modules` (plateforme, BE-042 et BE-044) ;
- `/api/v1/organizations/{organization_id}/modules`, `/entitlements`, `/module-audit`
  (BE-045 à BE-056) ;
- `/api/v1/organizations/current/modules` (BE-048, BE-053) ;
- `/api/v1/modules/organizations/{organization_id}` (activation héritée).

Elle fixe le périmètre à 28 routes, dont 19 portent `{organization_id}` et 17 sont des
mutations. Un ajout ou un retrait de route dans ces familles fait échouer
`test_decompte_du_perimetre` jusqu'à mise à jour du décompte.

| Critère | Cas | Attendu |
|---|---|---|
| CA-1 | membre actif sans rôle de A, sur chaque route à permission | 403 |
| CA-2 | propriétaire de A, chemin avec l'organisation B | 404 |
| CA-3 | mutation sans en-tête d'authentification | 401 |
| CA-4 | décompte exact du périmètre | 28 / 19 / 17 |

Total : 62 cas (25 CA-1, 19 CA-2, 17 CA-3, 1 décompte).

## Exclusions, avec motif

- Lectures ouvertes à tout membre actif, sans 403 attendu : `GET organizations/current/modules`,
  `GET organizations/current/modules/{module_id}/access`, `GET modules/organizations/{organization_id}`.
- Hors périmètre : catalogue public (BE-043), facturation (couverte par
  `test_isolation_organisations.py`), affectation de rôles par module (couverte par
  `test_module_assignment.py` et `test_authorization_matrix.py`), BE-057 et BE-059 (aucune route).

## Conditions de l'exécution

- Une base `zylo_t<NNN>_test` jetable, exportée dans `TEST_DATABASE_URL`.
- Le module `zylo_liquid` est lu en base (`get_or_create_module`) : un identifiant de module
  inconnu répond 404 avant la vérification de permission, ce qui ne testerait pas le 403.
- Les routes plateforme (`/admin/modules`) reçoivent un corps minimal valide : leur garde
  est dans le service, après validation du corps.
- Lancement : un seul run, environ 9 minutes sur la base de test.
