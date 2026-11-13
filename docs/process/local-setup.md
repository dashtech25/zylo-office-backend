# Démarrage local, environnements et tests

- **Statut** : en vigueur (T-017). Les ports sont fixés par [`ports.md`](ports.md) (table unique, T-003) : ce document ne les recopie pas.

## 1. Prérequis

- Python 3.12 ou plus, PostgreSQL accessible en local (base `zylo_office` pour le checkout principal).
- Pas de Docker requis pour le développement local.

## 2. Premier démarrage

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env            # renseigner DATABASE_URL et les secrets (voir section 4)
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 3002
```

Port du checkout principal : 3002 ([`ports.md`](ports.md), section 1). Documentation interactive : `http://localhost:3002/docs` (désactivée hors développement, T-015).

## 3. Base de données locale

```bash
createdb zylo_office
psql -d zylo_office -c "CREATE ROLE zylo_office WITH LOGIN PASSWORD '<mot_de_passe_local>';"
psql -d zylo_office -c "GRANT ALL ON SCHEMA public TO zylo_office;"
```

Le mot de passe est un secret local : ne jamais le consigner dans un fichier versionné.

## 4. Variables d'environnement

- Fichier `.env` (ignoré par git) lu par `app/core/config.py`. Modèle : `.env.example`.
- Le démarrage est refusé hors développement si un secret est absent ou par défaut (T-002, [ADR 0003](../architecture/decisions/0003-echec-ferme-secrets.md)).
- Clé de chiffrement `APP_FIELD_ENCRYPTION_KEY` : obligatoire hors développement et test ([ADR 0005](../architecture/decisions/0005-chiffrement-champs-holykell.md)).
- Origines CORS : variable `CORS_ORIGINS` (liste JSON), voir [`ports.md`](ports.md), section 3.

## 5. Tests

```bash
.venv/bin/pytest                      # suite complète
.venv/bin/pytest tests/test_rbac.py   # un fichier
```

- Base de test : `zylo_office_test` pour le checkout principal. Dans un worktree de tâche, la base est `zylo_t<NNN>_test`, créée par `scripts/dev/env_tache.sh creer <NNN> back` ([`git-workflow.md`](git-workflow.md), section 4). Un test n'utilise jamais une base de dev, de recette ou de production.
- Playwright est suspendu : [ADR 0006](../architecture/decisions/0006-playwright-suspendu.md).

## 6. Environnements

| Environnement | Où | Remarque |
|---|---|---|
| Local (checkout principal) | machine du développeur, port 3002 | `.env` local |
| Worktree de tâche | `office/worktrees/T-NNN-back`, port 3100+n | base `zylo_t<NNN>_test` |
| Recette et production | hors de ce dépôt | `app/core/database.py` mentionne Neon ; `Dockerfile` cite `backend.zylooffice.com`. Environnement par défaut non tranché : [`docs/questions/architecture/environnement-par-defaut.md`](../questions/architecture/environnement-par-defaut.md) |

## 7. Vérifications avant de conclure

- `scripts/check_ports.sh` : aucun port interdit dans les fichiers de configuration.
- `scripts/dev/controle_fichiers_sensibles.sh --index` : aucun dump ni `.env` suivi.
- Voir aussi [`docs/workflows/validation-avant-livraison.md`](../workflows/validation-avant-livraison.md).
