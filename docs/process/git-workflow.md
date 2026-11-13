# Workflow git : base de référence, lots et worktrees (T-004)

- **Statut** : en vigueur depuis T-004 (2026-10-08).
- **Dépôts** : `zylo-office-backend` et `zylo-office-frontend`, branche de travail `remy`.

## 1. Base de référence

- Tag `base-T004` posé sur `remy` dans les deux dépôts, après les lots du §2.
- Aucune tâche du plan ne démarre avant ce tag. Les tâches partent de `base-T004` ou d'un commit postérieur déjà fusionné.

## 2. Lots de T-004 (dans l'ordre)

Un lot = un sujet, testé avant commit (le tableau donne le hash du commit de chaque lot ; le détail est dans `git log`). Les commits sont en français, avec les trailers `Co-Authored-By` et `Claude-Session`.

| Dépôt | Lot | Contenu | Vérification |
|---|---|---|---|
| backend | B1 process (`0fbea01`) | `.gitignore` (`/taches/` ancré, `.env.*` ignoré sauf `.env.example`), `.githooks/pre-commit`, ce document, `docs/plans/`, `docs/audit/`, `docs/questions/`, `docs/architecture/bonnes-pratiques/` | hook testé (dumps et `.env*` refusés), `git check-ignore` vide pour `docs/plans/taches/` |
| backend | B2 config (`72dca7d`) | `app/core/config.py` (origine CORS du port e2e 3055, clés VAPID), `requirements.txt` (`pywebpush`) | `pytest tests/test_rbac.py` dans un worktree au commit du lot |
| frontend | F1 e2e (`2e5cd8e`) | `playwright.config.ts`, `e2e/*.ts` (specs, `global-setup.ts`), `e2e/fixtures/avatar-placeholder.png`, `.gitignore` (`/e2e/.auth/`) | `npx tsc --noEmit` dans un worktree au commit du lot |
| backend (`a7329ec`) et frontend (`a32da8d`) | Snapshot | tout le reste du travail en cours, sur une branche `wip/2026-10-08-snapshot-<dépôt>`, non fusionnée | aucune : sert à préserver. Découpage en lots `wip/…` par T-004b |

Sauvegarde préalable (hors dépôts, dossier `office/sauvegarde-T004-2026-10-08/`) : `git bundle --all` par dépôt, statut et diff, archive de l'arbre de travail. Les jetons de `e2e/.auth/` et les artefacts `storybook-static/`, `debug-storybook.log` y ont été déplacés (rien supprimé). Les jetons doivent être révoqués (voir `docs/questions/securite/rotation-credentials.md`).

## 3. Ce qui n'est pas versionné

- Fichiers d'environnement : `.env*` sauf `.env.example` (`.gitignore` et hook).
- Dumps : `*.sql`, `*.sql.gz`, `*.sql.bz2`, `*.sql.xz`, `*.dump`, `*.pgdump` ; dossier `backups/` (`.gitignore`).
- Clés privées et certificats : `*.pem`, `*.key`, `*.p12`, `id_rsa`, `id_ed25519` (`.gitignore`).
- Frontend : `e2e/.auth/`, `storybook-static/`, `test-results/`, `.next/`.

### Contrôle automatisé (T-001)

- Règles dans un seul endroit : `scripts/dev/controle_fichiers_sensibles.sh`.
  - `--index` : fichiers suivis (`git ls-files`). Utilisé par `tests/test_controle_fichiers_sensibles.py`, donc par la suite pytest (et la CI quand T-038a la branchera). Ce test ne dépend pas de l'activation du hook.
  - `--staged` : fichiers à committer. Utilisé par `.githooks/pre-commit`.
- Activation du hook, une fois par clone : `git config core.hooksPath .githooks`. Sans cette commande, seul le test d'index protège le dépôt.
- Si le contrôle signale un fichier déjà suivi : `git rm --cached <fichier>` (le fichier reste sur disque), puis commit. Ne pas réécrire l'historique sans accord écrit (voir `docs/questions/securite/purge-historique-dump.md`).
- Limite : contrôle par nom de fichier, pas par contenu. Un secret placé dans un fichier au nom anodin n'est pas détecté.

## 4. Worktrees

- Un worktree par tâche et par dépôt, dans `office/worktrees/T-XXX-<back|front>` (dossier frère des dépôts, hors dépôt).
- Création et suppression : `scripts/dev/env_tache.sh creer|supprimer <NNN> <back|front>` (dépôt backend). Le préflight vérifie tout avant de créer ; la base n'est créée que si le rôle a CREATEDB.
- Serveur d'administration (back) : `ZYLO_PG_ADMIN_URL`, par défaut le rôle Unix courant via la socket locale (auth peer, sans mot de passe). Ce rôle doit avoir CREATEDB ; il crée la base avec `OWNER zylo_office` sans modifier le rôle `zylo_office` (aucun `ALTER ROLE`, aucun `GRANT`, pas de sudo).
- `creer back` crée `zylo_t<NNN>_test`, applique `alembic upgrade head` sur cette seule base (venv du dépôt backend : `.venv`), puis écrit `.env` dans le worktree. En cas d'échec des migrations, le worktree et la base sont retirés.
- `supprimer back` ne supprime que le motif `zylo_t[0-9]{3}_test`, après `git worktree remove` (sans `--force`).
- Procédure vérifiée : `creer 098 back`, `pytest tests/test_rbac.py` avec `TEST_DATABASE_URL` pris dans le `.env` du worktree, puis `supprimer 098 back`.
- Fichiers d'environnement du worktree : `.env` (backend, lu par `app/core/config.py`) et `.env.local` (frontend), tous deux ignorés par git.
- Ports : table unique des ports (créée par T-003 ; absente tant que T-003 n'est pas fusionnée). Worktree T-NNN : back 3100+n, front dev 3200+n, front prod 3300+n, avec n = NNN.
- Bases de test : `zylo_t<NNN>[a-z]?_test` uniquement. Les bases `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette` ne sont jamais utilisées par un test.

## 5. Interdits

- Pas de `git stash`, `git checkout --`, `git reset --hard`, `git clean` sur du travail non commité.
- Pas de réécriture d'historique et pas de push sans accord écrit.
- Pas de `--no-verify` pour contourner le hook.

## 6. Commits, labels, issues et PR

- Commits en français, un sujet par commit. Trailers en fin de message : `Co-Authored-By: <modèle> <noreply@anthropic.com>` puis `Claude-Session: <lien de session>`.
- Labels : `labels.md`. Issues : `gabarit-issue.md`. Pull requests : `gabarit-pr.md`.
- Contrôle du plan et régénération du registre : `controle-plan.md`.
- Aucune issue ni label n'est créé sur GitHub sans accord écrit ; `check_plan.py --gh` ne fait qu'afficher les commandes.
