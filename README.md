# Zylo Office : backend

Socle backend de Zylo Office : une plateforme modulaire (ERP/CRM). Le socle
(identité, organisations, rôles, permissions, registre de modules,
abonnements) accueille les modules métier. `zylo_liquid` est le premier module
complet et sert de patron ; `zylo_tanker` est un module en cours.

## Où lire

| Besoin | Document |
|---|---|
| Règles à respecter au quotidien | [`CLAUDE.md`](CLAUDE.md) |
| Index de la documentation | [`docs/README.md`](docs/README.md) |
| Architecture (monolithe modulaire) | [`docs/architecture/`](docs/architecture/README.md) |
| Ports (checkout, worktrees, interdits) | [`docs/process/ports.md`](docs/process/ports.md) |
| Démarrage local, environnement | [`docs/process/local-setup.md`](docs/process/local-setup.md) |
| Git, lots, worktrees | [`docs/process/git-workflow.md`](docs/process/git-workflow.md) |
| Workflow de bout en bout | [`docs/workflows/`](docs/workflows/README.md) |
| Décisions d'architecture | [`docs/architecture/decisions/`](docs/architecture/decisions/README.md) |
| Console support opérateur (lecture seule) | [`docs/modules/operator.md`](docs/modules/operator.md) |
| Contrat facturation | [`docs/modules/facturation.md`](docs/modules/facturation.md) |

## Stack

- FastAPI (Python 3.12), API REST versionnée sous `/api/v1`
- PostgreSQL, SQLAlchemy 2.0 (async), Alembic pour les migrations
- Authentification JWT (access + refresh, rotation), bibliothèque PyJWT
- Tables en camelCase, en anglais, commentées

## Démarrage local (résumé)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # renseigner DATABASE_URL et les secrets
.venv/bin/alembic upgrade head
.venv/bin/uvicorn app.main:app --reload --port 3002
```

Port et procédure complète : [`docs/process/ports.md`](docs/process/ports.md) et
[`docs/process/local-setup.md`](docs/process/local-setup.md).

La console support reste fermée par défaut. Pour un processus backend de support,
configurer `OPERATOR_READ_USER_IDS` avec une liste séparée par des virgules
d'UUID de comptes opérateur dédiés et redémarrer le processus. Une variable
absente, vide ou mal formée n'accorde aucun accès.

## Tests

```bash
.venv/bin/pytest
```

## Sauvegarde

```bash
./scripts/backup.sh                              # dump local, rotation 7 jours
./scripts/restore.sh backups/<fichier> <base_cible>
```

Les dumps ne sont jamais versionnés (`backups/` est ignoré par git).
Audit de conformité offline : [`docs/core/phase-12-offline-readiness-audit.md`](docs/core/phase-12-offline-readiness-audit.md).
