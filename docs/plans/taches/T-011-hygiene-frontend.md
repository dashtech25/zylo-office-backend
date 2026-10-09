# T-011 : Hygiène frontend (ui-preview, fichiers parasites, route en doublon)

- **Statut** : Planifiée · **Priorité** : P3 · **Vague** : 1 · **Taille** : S · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : chore
- **Branche suggérée** : `chore/T-011-hygiene-frontend` · **Base de test** : aucune · **Ports** : front prod 3311
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
Supprimer ce qui ne sert pas au produit : `test.txt` suivi, route `ui-preview` exposée, CSS de gabarit, route `zylo-liquid/utilisateurs` en doublon. Le gabarit Storybook (`src/stories/`) est déjà retiré par T-041.

## Problèmes résolus
- FRT-010 (partie CSS du gabarit), FRT-017, FRT-018, FRT-023 (partie restante), ARC-019 (fichiers parasites), ARC-020 (route `ui-preview` et doublon `utilisateurs`)

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-041 (confort : réduit le travail, sans artefact consommé) ; T-008 (confort).

## Fichiers / modules concernés
- `test.txt` (racine, `git rm`)
- `src/app/(app)/ui-preview/` (suppression)
- `src/app/zylo-liquid/utilisateurs/page.tsx` (redirection vers la route de référence `(app)/users`)
- `.storybook/` : déjà retiré (T-041)

## Stratégie
1. `grep -r "ui-preview\|test.txt" src e2e` : aucun import attendu.
2. Supprimer `ui-preview` (option retenue, FRT-018).
3. Remplacer la page `zylo-liquid/utilisateurs` par une redirection.
4. Pas de changement de comportement pour les utilisateurs authentifiés.

## Tests attendus
- `npx tsc --noEmit` et `npm run build` verts.
- `npm run test:unit` vert.
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : navigation de base, login et tableau de bord.

## Critères d'acceptation
- `ui-preview` inaccessible (404 en build de production).
- Route `utilisateurs` unique (redirection, pas de page dupliquée).
- Aucun fichier parasite suivi à la racine du frontend.

## Risque et retour arrière
Faible. Retour arrière : revert.

## Livrable documentaire
- Une ligne dans `docs/process/frontend-structure.md` (créé par T-039).

## Parallélisable avec
T-006, T-007, T-008, T-012 à T-016.
