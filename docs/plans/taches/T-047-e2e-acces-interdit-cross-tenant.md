# T-047 : Tests d'accès interdit et inter-organisations (API et e2e)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend et backend · **Domaine** : iam · **Type** : test
- **Branche suggérée** : `test/T-047-acces-interdit` · **Base de test** : `zylo_t047_test` · **Ports** : back 3147, front prod 3347
- **Dépendances** : T-010, T-022, T-046
- **Décisions requises** : `rbac/code-http-acces-interdit.md`

## Objectif
Prouver, sur build de production, que l'accès interdit et l'isolation entre organisations tiennent : un utilisateur d'A ne voit ni n'agit sur B, et un module non affecté ne répond pas. Les tests sont écrits à partir de la matrice de T-023 et s'exécutent sur des données isolées (T-046).

## Problèmes résolus
- REV-D-19 (aucun test d'accès interdit ni inter-organisations), coordination (e) : tests d'accès interdit et inter-organisations

## Dépendances : justification
- T-010 : isolation testée.
- T-022 : affectations testées.
- T-046 : fixtures e2e isolées.

## Fichiers / modules concernés
- `e2e/acces-interdit.spec.ts` (créé) : cas navigateur
- `e2e/cross-tenant.spec.ts` (créé) : cas navigateur
- `tests/test_e2e_api_acces.py` (créé) : appels API directs, sans navigateur

## Stratégie
1. API directe : membre de A avec l'en-tête de B : 404 (code décidé par T-010), aucune écriture.
2. API directe : membre sans permission sur un module : 403.
3. Navigateur : URL directe d'un écran d'un module non affecté : aucune donnée affichée.
4. Navigateur : jeton de A et en-tête de B : pas de donnée de B affichée.
5. Trois exécutions consécutives sans échec (stabilité).

## Tests attendus
- Les quatre assertions ci-dessus, chacune pour au moins deux routes.
- Exécution sur `zylo_t047_test`, configuration de production (T-008).

## Critères d'acceptation
- Aucun cas autorisé par erreur ; chaque refus est une assertion.
- Trois exécutions consécutives vertes.

## Risque et retour arrière
Faible. Retour arrière : retirer les specs de la CI, sans toucher au code.

## Livrable documentaire
- `docs/process/tests.md` (section accès interdit).

## Parallélisable avec
T-024, T-025 (les specs n'utilisent pas les écrans de ces tâches).
