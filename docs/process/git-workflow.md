# Workflow git : base de référence, lots et worktrees (T-004)

- **Statut** : en vigueur depuis T-004 (2026-10-08).
- **Dépôts** : `zylo-office-backend` et `zylo-office-frontend`, branche de travail `remy`.

## 1. Base de référence

- Tag `base-T004` posé sur `remy` dans les deux dépôts, après les lots du §2.
- Aucune tâche du plan ne démarre avant ce tag. Les tâches partent de `base-T004` ou d'un commit postérieur déjà fusionné.

## 2. Lots de T-004 (dans l'ordre)

Un lot = un sujet, testé avant commit. Les commits sont en français, avec les trailers `Co-Authored-By` et `Claude-Session`.

| Dépôt | Lot | Contenu | Vérification |
|---|---|---|---|
| backend | B1 process | `.gitignore` (`/taches/` ancré, `.env.*` ignoré sauf `.env.example`), `.githooks/pre-commit`, ce document, `docs/plans/`, `docs/audit/`, `docs/questions/`, `docs/architecture/bonnes-pratiques/` | hook testé (dumps et `.env*` refusés), `git check-ignore` vide pour `docs/plans/taches/` |
| backend | B2 config | `app/core/config.py` (origine CORS du port e2e 3055, clés VAPID), `requirements.txt` (`pywebpush`) | `pytest tests/test_rbac.py` dans un worktree au commit du lot |
| frontend | F1 e2e | `playwright.config.ts`, `e2e/*.ts` (specs, `global-setup.ts`), `e2e/fixtures/avatar-placeholder.png`, `.gitignore` (`/e2e/.auth/`) | `npx tsc --noEmit` dans un worktree au commit du lot |
| backend et frontend | Snapshot | tout le reste du travail en cours, sur une branche `wip/2026-10-08-snapshot-<dépôt>`, non fusionnée | aucune : sert à préserver. Découpage en lots `wip/…` par T-004b |

Sauvegarde préalable (hors dépôts, dossier `office/sauvegarde-T004-2026-10-08/`) : `git bundle --all` par dépôt, statut et diff, archive de l'arbre de travail. Les jetons de `e2e/.auth/` et les artefacts `storybook-static/`, `debug-storybook.log` y ont été déplacés (rien supprimé). Les jetons doivent être révoqués (voir `docs/questions/securite/rotation-credentials.md`).

## 3. Ce qui n'est pas versionné

- Fichiers d'environnement : `.env*` sauf `.env.example` (`.gitignore` et hook).
- Dumps : `*.sql`, `*.sql.gz`, `*.dump` (hook).
- Frontend : `e2e/.auth/`, `storybook-static/`, `test-results/`, `.next/`.

## 4. Worktrees

- Un worktree par tâche et par dépôt, dans `office/worktrees/T-XXX-<back|front>` (dossier frère des dépôts, hors dépôt).
- Création et suppression : `zylo-office-backend/scripts/dev/env_tache.sh` (voir `docs/process/environnement-taches.md`).
- Ports : table unique dans `docs/process/ports.md` (T-003). Worktree T-NNN : back 3100+n, front dev 3200+n, front prod 3300+n, avec n = NNN.
- Bases de test : `zylo_t<NNN>[a-z]?_test` uniquement. Les bases `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette` ne sont jamais utilisées par un test.

## 5. Interdits

- Pas de `git stash`, `git checkout --`, `git reset --hard`, `git clean` sur du travail non commité.
- Pas de réécriture d'historique et pas de push sans accord écrit.
- Pas de `--no-verify` pour contourner le hook.
