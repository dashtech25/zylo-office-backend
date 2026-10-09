# ADR 0006 : Suspension de Playwright

- **Date** : 2026-10-09.
- **Statut** : Acceptée (décision client, décideur : client, produit).
- **Source** : `docs/process/decision-playwright-suspendu.md` (branche `docs/playwright-suspendu`, commit `c107c3c`).

## Contexte

L'interface frontend sera refaite. Les tests e2e actuels ciblent une interface appelée à disparaître.

## Décision

Tous les travaux Playwright sont suspendus (tests e2e, configurations, smoke sur build de production). Aucune nouvelle spec n'est écrite. Les critères Playwright des tâches sont remplacés par `pytest`, `tsc`, lint et build locaux, avec la mention « Playwright suspendu ».

## Conséquences

- Le comportement non couvert par un test automatisé est listé dans chaque fiche suspendue.
- Reprise seulement si les quatre conditions du document de décision sont réunies. Les fiches T-008, T-009, T-026, T-041 (partie smoke) et T-046 sont suspendues.
- Les branches `test/T-008-playwright-prod` et `chore/t041-retirer-storybook` sont conservées comme point de départ documenté.
