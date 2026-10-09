# T-046 : Fixtures e2e isolées par spec (une organisation et une station par test)

> **Suspendue le 2026-10-09** : Playwright suspendu par décision du client. Voir `docs/process/decision-playwright-suspendu.md`.

- **Statut** : Suspendue · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : test
- **Branche suggérée** : `test/T-046-fixtures-isolees` · **Base de test** : `zylo_t046_test` · **Ports** : back 3146, front prod 3346
- **Dépendances** : T-008
- **Décisions requises** : aucune

## Objectif
Aujourd'hui `global-setup.ts` crée une seule organisation, une station et une cuve, partagées par toutes les specs. Chaque spec, voire chaque test, crée ses propres données, avec des noms suffixés par l'identifiant d'exécution. Plus de compteur global.

## Problèmes résolus
- REV-D-18 (isolation absente), REV-D-23 (durées de test masquant des blocages, partiellement), REV-A-11 (ordre des fichiers chauds `e2e`)

## Dépendances : justification
T-008 (configuration prod, base de test). Sans T-008, l'isolation n'est pas mesurable sur build de production.

## Fichiers / modules concernés
- `e2e/fixtures/` (créé) : fabrique d'organisation, de station et de cuve par test
- `e2e/global-setup.ts` : ne crée plus que le référentiel commun
- `playwright.config.ts` : `workers` explicite, projets par famille si nécessaire
- Specs `e2e/gerant-*.spec.ts`, `e2e/proprietaire-*.spec.ts` : migration progressive

## Stratégie
1. Fabrique de données avec identifiant d'exécution (`runId`) dans chaque nom ; suppression des compteurs globaux (`pumpBase = 3000 + stamp % 6000`).
2. `workers` fixé dans la configuration ; exécution en parallèle seulement si les données sont isolées.
3. Migration spec par spec, un commit par famille de specs.

## Conventions (REV-D-25, REV-D-23)
- Nommage : `*.mock.spec.ts` pour les specs sur mocks (`installMockBackend`), `*.real.spec.ts` pour les parcours métier sur backend réel. Un parcours métier est `real`. La convention est écrite dans `docs/process/tests.md`.
- Aucun `test.setTimeout` supérieur à 60 secondes sans justification écrite dans la spec (liste de 18 occurrences à réduire).

## Tests attendus
- Suite complète `npm run e2e:prod` vert deux fois de suite sur base de test.
- Exécution d'une seule spec isolée produit le même résultat que dans la suite.

## Critères d'acceptation
- Convention de nommage `mock`/`real` appliquée et contrôlée par script ; aucun `setTimeout` de test au-delà de 60 s sans justification.
- Aucun compteur global ni donnée partagée entre specs (contrôle `grep` des fixtures).
- Suite exécutée sur `zylo_t046_test` sans seed manuel.

## Risque et retour arrière
Moyen : les specs dépendent aujourd'hui des données du global-setup. Retour arrière : garder l'ancien global-setup dans l'historique et revenir au commit précédent.

## Livrable documentaire
- `docs/process/tests.md` (section fixtures).

## Parallélisable avec
T-006, T-007, T-010 (fichiers distincts).
