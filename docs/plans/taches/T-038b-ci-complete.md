# T-038b : CI complète (lint, contrats d'architecture, Playwright sur build prod)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : ci · **Type** : ci
- **Branche suggérée** : `ci/T-038b-ci-complete` · **Base de test** : `zylo_t038b_test` · **Ports** : back 3138, front prod 3338
- **Dépendances** : T-038a, T-036
- **Décisions requises** : aucune

## Objectif
Ajouter à la CI minimale les jobs qui exigent les contrats et le lint : `lint-imports` (contrats de T-036), `npm run lint` (sans `storybook-static`), et la suite Playwright sur build de production (T-008, T-009). Le mode régression de pytest est remplacé par « pytest complet bloquant » quand `known_failures.txt` est vide.

## Problèmes résolus
- DOC-001 (partie complète), ARC-002 (contrats non exécutés), baseline section 2 (lint en échec), REV-A-09 (découpe), REV-D-27 (workflow frontend)

## Dépendances : justification
- T-038a : fichiers de workflow à compléter.
- T-036 : contrats `.importlinter` exécutés par `lint-imports`.
- Retirées (confort ou CI, pas de prérequis technique) : T-009 (CI indépendante : job Playwright avec exclusion `@external` et `known_failures`).

## Fichiers / modules concernés
- Backend : `.github/workflows/ci.yml` (job `lint-imports`)
- Frontend : `.github/workflows/frontend.yml` (jobs `lint`, `e2e:prod`)
- `eslint.config.mjs` (`ignores` : `.next`, `storybook-static`)

## Stratégie
1. Job `lint` : `npm run lint` vert, sans erreur due à `storybook-static`.
2. Job `lint-imports` : contrats KEPT.
3. Job Playwright : `npm run e2e:prod`, backend lancé sur la base `zylo_t038b_test`, sans `@external`.
4. Secrets par le système de secrets GitHub. Versions Node et Python fixées.
5. Documenter la correspondance entre `docs/process/ci.md` et les jobs réels.

## Tests attendus
- Workflow vert sur une branche de test.
- Violation volontaire (contrat rompu, lint en erreur) : CI en échec, preuve dans la PR.

## Critères d'acceptation
- `npm run lint` : 0 erreur.
- Jobs listés bloquants sur `remy`.
- `docs/process/ci.md` décrit la CI réelle.

## Risque et retour arrière
Moyen : une CI bloquante arrête les fusions. Retour arrière : passer un job en non bloquant par décision écrite, jamais en le supprimant sans décision.

## Livrable documentaire
- `docs/process/ci.md` (complété).

## Parallélisable avec
T-039, T-040.
