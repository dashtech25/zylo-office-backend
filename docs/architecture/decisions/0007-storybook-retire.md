# ADR 0007 : Retrait de Storybook

- **Date** : 2026-10-08 (constat de l'audit DOC-017).
- **Statut** : Acceptée. Exécution planifiée : T-041 (frontend), branche `chore/retirer-storybook`.
- **Source** : [`docs/plans/taches/T-041-retrait-storybook.md`](../../plans/taches/T-041-retrait-storybook.md), [`docs/audit/documentation-issues.md`](../../audit/documentation-issues.md) (DOC-017).

## Contexte

Le gabarit Storybook (`src/stories/`, dont `Configure.mdx` de 446 lignes et des CSS locaux) contredit la règle « aucun nouveau fichier CSS local » du frontend.

## Décision

Retirer Storybook et son gabarit du frontend. Le retrait est une partie séparée du smoke Playwright, lui suspendu ([ADR 0006](0006-playwright-suspendu.md)).

## Conséquences

- Aucun outil de catalogue de composants ; le catalogue de composants (T-043) reste à décider.
