# T-042 : Mise en place minimale de Vitest, sans Storybook, pour la logique pure

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 0 · **Taille** : S · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : test
- **Branche suggérée** : `test/T-042-vitest-minimal` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-041
- **Décisions requises** : `tests/couche-tests-unitaires.md` (appliquée, décision du coordinateur)

## Objectif
Réintroduire un runner de tests unitaires minimal, sans Storybook, pour la logique pure (fonctions de `src/shared/lib`, validations, calculs de permission). Les composants restent couverts par Playwright.

## Problèmes résolus
- REV-D-03 (suppression de Vitest sans remplacement), REV-A-04 (T-024, T-025, T-033 sans moyen de test unitaire)

## Dépendances : justification
- T-041 : Storybook retiré : Vitest est réintroduit sur une base sans sa configuration.

## Fichiers / modules concernés
- `vitest.config.ts` (créé), `package.json` (`vitest` en dev, script `test:unit`)
- `src/shared/lib/*.test.ts` (créés) : au moins `formatDateTime` et la validation de mot de passe / e-mail (T-013 l'étendra)

## Stratégie
1. Environnement `node` par défaut. `jsdom` seulement si un test l'exige (pas de Testing Library au départ).
2. Pas de fichier `*.stories.*`, pas de dépendance Storybook.
3. `npm run test:unit` : exécution locale et en CI (T-038a).

## Tests attendus
- `npm run test:unit` vert, au moins 5 cas sur la logique pure de `src/shared/lib`.
- Un test échoue volontairement sur une fonction modifiée : le runner est bien branché (vérification consignée).

## Critères d'acceptation
- Un runner unitaire, pas de Storybook.
- `npm run test:unit` vert, documenté dans `docs/process/tests.md`.
- Décision consignée dans `docs/questions/tests/couche-tests-unitaires.md`.

## Risque et retour arrière
Faible. Retour arrière : supprimer `vitest.config.ts` et le script.

## Livrable documentaire
- `docs/questions/tests/couche-tests-unitaires.md`
- `docs/process/tests.md` (section tests unitaires)

## Parallélisable avec
T-043, T-011.
