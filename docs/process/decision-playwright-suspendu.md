# Décision : suspension de Playwright

- **Date** : 2026-10-09
- **Décideur** : client (décision produit)
- **Statut** : en vigueur jusqu'à la reprise décrite plus bas

## Décision

Tous les travaux Playwright (tests e2e, configurations `playwright*.config.ts`, smoke sur build de production) sont suspendus. Aucune nouvelle spec n'est écrite et aucune exécution Playwright n'est exigée pour clore une tâche.

## Motif

L'interface frontend sera refaite. Les tests e2e actuels ciblent une interface appelée à disparaître : les maintenir ou les corriger serait un travail jeté.

## Ce qui est suspendu

- T-008 (Playwright sur build de production, e2e versionnés) ;
- T-009 (corrections des scénarios Playwright en échec) ;
- T-026 (parcours e2e organisation, utilisateur, module) ;
- T-041 (smoke Playwright sur build de production ; le retrait de Storybook reste une partie séparée) ;
- T-046 (fixtures e2e isolées).

Les critères Playwright des autres tâches sont remplacés par « tests pytest / tsc / lint / build locaux », avec la mention « Playwright suspendu ». Le comportement qui n'est plus couvert par un test automatisé est listé dans chaque fiche, pour qu'il reste visible.

## Conditions de reprise

Playwright reprend seulement si les quatre conditions suivantes sont réunies :

1. la nouvelle interface frontend est validée par le client ;
2. le client confirme par écrit la reprise des tests e2e ;
3. les fiches suspendues sont réévaluées (les sélecteurs et parcours sont à réécrire, pas à relancer tels quels) ;
4. la base de test et les ports sont recréés via `scripts/dev/env_tache.sh creer` (aucune base de test n'est conservée).

## Branches conservées

Aucune branche n'est supprimée. Elles servent de point de départ documenté, pas de référence à rejouer :

- `test/T-008-playwright-prod` (frontend) : commit `wip(T-008)` contenant le travail non terminé (configuration, global-setup, environnement de test, specs gérant) ;
- `chore/t041-retirer-storybook` (frontend) : smoke `playwright.prod.config.ts` et `e2e/smoke-prod.spec.ts`.

Les worktrees de test T-008 et la base `zylo_t008_test` ont été supprimés le 2026-10-09 après vérification qu'aucune modification n'était perdue.

## Points ouverts

- T-038b (CI complète) dépend de T-009 et de son job Playwright : il doit être reconsidéré avant d'être planifié.
