# Environnement de test par tâche (T-005)

- **Statut** : en vigueur depuis T-005 (branche `test/T-005-garde-base`, à vérifier).
- **Décision** : une base de test par tâche, nommée `zylo_t<NNN>_test` (voir `docs/process/git-workflow.md` §4). Aucune base partagée entre tâches.

## 1. Créer l'environnement d'une tâche

```bash
scripts/dev/env_tache.sh creer <NNN> back [branche]
```

- Crée le worktree `office/worktrees/T-<NNN>-back`, la base `zylo_t<NNN>_test` et son `.env` (`TEST_DATABASE_URL` compris), puis applique `alembic upgrade head`.
- Le script affiche la ligne à lancer pour exporter `TEST_DATABASE_URL` depuis le `.env` du worktree.
- Supprimer : `scripts/dev/env_tache.sh supprimer <NNN> back`.

## 2. Lancer pytest

```bash
export TEST_DATABASE_URL="$(sed -n 's/^TEST_DATABASE_URL=//p' .env)"
/chemin/du/depot-backend/.venv/bin/pytest
```

Le venv est partagé : il se trouve dans le dépôt `zylo-office-backend`, pas dans le worktree. Sans `TEST_DATABASE_URL`, pytest refuse de démarrer. Le message indique la commande ci-dessus.

## 3. Garde de base (`tests/conftest.py`)

pytest vide toutes les tables de la base de test à chaque session. La garde refuse donc le démarrage si :

- `TEST_DATABASE_URL` est absente ou vide (aucune valeur de repli) ;
- le nom de base ne suit pas le motif `zylo_t<NNN>[a-z]?_test` (les noms `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette` sont refusés, quel que soit le port ou l'hôte).

Exception unique : `zylo_office_test` (ancien repli) n'est acceptée que si `ZYLO_TEST_TOLERER_ZYLO_OFFICE_TEST=1` est posée explicitement.

Le test `tests/test_garde_base_test.py` vérifie ces règles dans des sous-processus pytest.

## 4. Limites

- Le garde-fou Playwright (`e2e/global-setup.ts`) relève du dépôt frontend et n'est pas couvert ici.
- `README.md` mentionne encore `createdb zylo_office_test` : cette base ne sert plus de cible par défaut.
