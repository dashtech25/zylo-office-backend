# Couche de tests unitaires du frontend après le retrait de Storybook

- **Question** : quelle couche de tests unitaires garder après le retrait de Storybook et de Vitest ?
- **Tâches concernées** : T-042, T-033a, T-024, T-025
- **Contexte** : le commit `64c97e1` (branche `chore/retirer-storybook`) supprime `vitest.config.ts` et les 223 tests Vitest de la baseline, sans remplacement. Plusieurs critères de tâches supposaient Storybook.
- **Options** :
  - A. Vitest minimal sur la logique pure (`src/shared/lib`, validations, calculs de permission), sans Storybook, sans Testing Library au départ (recommandation, appliquée).
  - B. Vitest et Testing Library sur les composants partagés : plus de couverture, plus de maintenance ; à décider après A.
  - C. Playwright seul : aucun test unitaire ; les règles pures sont alors testées indirectement.
- **Recommandation vérifiée** : option A. Vérification : le commit `64c97e1` supprime `vitest.config.ts` (vérifié par `git show --stat`).
- **État** : Appliquée (décision du coordinateur, à confirmer)
