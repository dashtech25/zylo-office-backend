# T-004 : Base de référence et espace de travail isolé

- **Statut** : Réalisée (à vérifier) · **Priorité** : P0 · **Vague** : 0 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : process · **Type** : chore
- **Branche suggérée** : `chore/T-004-base-reference` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
Poser la base à partir de laquelle toutes les tâches partent : le travail en cours est trié, le minimum nécessaire aux tâches de la vague 0 et de la vague 1 est commité, le plan et les fiches sont versionnés, et le tag `base-T004` est posé dans les deux dépôts. Aucune autre tâche ne démarre avant ce tag.

Au 2026-10-08 : 54 fichiers modifiés côté backend, 229 côté frontend, 25 fichiers `e2e/` non suivis, `docs/plans/` et `docs/audit/` non suivis.

## Problèmes résolus
- DOC-019, DOC-018 (partie workflow réel), REV-A-02, REV-A-05 (partie base), REV-S-14, REV-D-05, REV-D-17 (versionnement des e2e), REV-D-07 (ignore de `e2e/.auth/`)

## Lot 0 : plan, règles d'ignore et garde (en premier)
1. Dans `zylo-office-backend/.gitignore`, ancrer la règle `taches/` en `/taches/` : les fiches de `docs/plans/taches/` deviennent versionnées.
2. Vérifier avec `git check-ignore -v docs/plans/taches/T-004-base-de-reference.md` (aucune sortie attendue) et `git check-ignore -v docs/audit/index.md` ou équivalent (aucune sortie).
3. Ajouter un hook versionné `.githooks/pre-commit` (refuse `*.sql`, `*.sql.gz`, `*.dump`, `.env*` sauf `.env.example`) et `git config core.hooksPath .githooks` documenté dans `docs/process/git-workflow.md`.
4. Frontend : ajouter à `.gitignore` `e2e/.auth/` et `e2e/fixtures/` (fichiers générés, jetons de session à ne jamais versionner).
5. Frontend : versionner les 25 fichiers `e2e/` non suivis (specs, `global-setup.ts`, `fixtures` non générées) ; ne jamais ajouter `e2e/.auth/`.

## Lot 1 : sauvegarde et tri minimal
1. Sauvegarde hors dépôt avant toute opération : `git bundle create` pour chaque dépôt, copie de `git status` et `git diff` dans un dossier hors dépôt.
2. Artefacts générés : déplacer hors dépôt (sauvegarde, pas suppression) `storybook-static/`, `debug-storybook.log`, `e2e/.auth/` (les jetons qu'il contient sont à révoquer, voir `questions/securite/rotation-credentials.md`).
3. Commiter le **minimum bloquant** en lots thématiques (un lot = un sujet, `tsc` ou `pytest` ciblé avant commit) :
   - backend : `app/core/config.py`, `tests/conftest.py`, `Dockerfile`, `requirements*.txt`, fichiers de `docs/plans/`, `docs/audit/`, `docs/questions/` ;
   - frontend : `package.json`, `package-lock.json`, `playwright.config.ts`, `src/core/api/client.ts`, `e2e/` (sans `.auth`), `.gitignore`.
4. Tout le reste du travail en cours (zylo_liquid, tanker, design system, etc.) n'est **pas** commité ici : il part dans T-004b, sur des branches `wip/…`.
5. Ne jamais utiliser `git stash`, `git checkout --` ou `git reset` sur du travail non commité. Pas de réécriture d'historique.

## Lot 2 : base et espace de travail
1. Tag `base-T004` sur `remy` dans les deux dépôts, après commit des lots du lot 1.
2. Convention de worktrees : dossier `office/worktrees/` (frère des dépôts, hors dépôt), un worktree par tâche et par dépôt, nommé `worktrees/T-XXX-<back|front>`. Le plan §2 est corrigé en conséquence (REV-A-20).
3. Chaque worktree part du tag `base-T004` (ou d'un commit postérieur fusionné).

## Dépendances : justification
Aucune. Bloque toutes les tâches : T-001, T-002, T-003, T-005, T-041, T-016 et les suivantes démarrent de ce tag.

## Tests et vérifications
- `git status --porcelain` vide dans les deux dépôts après le lot 1 (les `wip/` restent hors de `remy`).
- `git ls-files docs/plans docs/audit | wc -l` égal au nombre de fichiers présents sur disque.
- `git ls-files e2e | wc -l` égal au nombre de fichiers `*.spec.ts` + `global-setup.ts` + helpers versionnés.
- `git ls-files | grep -E '\.sql(\.gz)?$|(^|/)\.env'` vide.
- Backend : `pytest` ciblé sur `tests/test_rbac.py` au minimum (les échecs connus sont listés dans `docs/audit/baseline-tests.md`, aucun nouvel échec).
- Frontend : `npx tsc --noEmit` vert.
- Pas de Playwright dans cette tâche.

## Critères d'acceptation
- Working tree propre dans les deux dépôts sur `remy`.
- Tag `base-T004` présent dans les deux dépôts.
- Aucun fichier `*.sql*`, `.env*` (hors exemple), `e2e/.auth/`, `storybook-static/` suivi.
- `docs/plans/taches/` et `docs/audit/` suivis.
- Liste des lots et des commits consignée dans `docs/process/git-workflow.md`.

## Risque et retour arrière
Élevé en cas de mauvais regroupement. Retour arrière : le tag marque le point de départ, la sauvegarde `git bundle` permet de reconstituer l'état initial. Un lot qui ne compile pas est renvoyé au sujet, il n'est pas corrigé en mélangeant les lots.

## Livrable documentaire
- `docs/process/git-workflow.md` (lots et commits, tag, convention de worktrees).

## Parallélisable avec
Rien en amont. T-004b démarre après le tag.

## Résultat (2026-10-08)
- Contrôle indépendant requis : oui, pour le tri du snapshot (T-004b) et la revue des lots `wip/`.
- Lots et commits : `docs/process/git-workflow.md`. Tag `base-T004` posé sur `remy` dans les deux dépôts.
- Sauvegarde hors dépôt : `office/sauvegarde-T004-2026-10-08/` (bundles, statut, diff, archive).
- Écarts par rapport à la fiche : `e2e/fixtures/` n'est pas ignoré (il contient une fixture réelle) ; seul `e2e/.auth/` l'est. Le backend lit `.env` (et non `.env.local`) : le worktree de test écrit `.env`.
- Base de test : la création de `zylo_t<NNN>_test` exige le droit CREATEDB, absent du rôle utilisé.
