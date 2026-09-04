# Zylo Office — Backend

Socle backend de Zylo Office, une plateforme ERP/CRM modulaire inspirée
d'Odoo/Dolibarr : le **socle** (identité, organisations, rôles,
permissions, registre de modules, abonnements) est complété par un premier
**module métier complet, `zylo_liquid`**, qui sert de patron pour les
futurs modules (CRM, Stock, Comptabilité, RH, POS). Voir `grande_phases.md`
(racine du projet, hors ce dépôt) pour l'architecture complète et le détail
des phases.

> **⚠️ Avant toute modification de ce dépôt, lire `/CLAUDE.md`** (directive
> d'architecture — core/shared jamais dépendants d'un module, convention
> stricte de dossier pour tout module métier). C'est la règle qui prime.

## Stack

- **FastAPI** (Python 3.12), API REST versionnée sous `/api/v1`
- **PostgreSQL** + **SQLAlchemy 2.0 (async)** + **Alembic** pour les migrations
- **JWT** (access + refresh, rotation) pour l'authentification
- Noms de tables en **camelCase, en anglais, commentés** (convention imposée)

## Démarrage local

Prérequis : Python 3.12+, PostgreSQL accessible en local.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cp .env.example .env   # puis renseigner DATABASE_URL et JWT_SECRET réels

.venv/bin/alembic upgrade head

.venv/bin/uvicorn app.main:app --reload --port 3007
```

Le serveur écoute sur `http://localhost:3007`. Documentation interactive :
`http://localhost:3007/docs`.

### Base de données locale

```bash
createdb zylo_office
psql -d zylo_office -c "CREATE ROLE zylo_office WITH LOGIN PASSWORD 'changeme';"
psql -d zylo_office -c "GRANT ALL ON SCHEMA public TO zylo_office;"
```

## Tests

```bash
createdb zylo_office_test
psql -d zylo_office_test -c "GRANT ALL ON SCHEMA public TO zylo_office;"
.venv/bin/pytest
```

## Architecture

Chaque dossier structurant a son propre `CLAUDE.md` avec la règle précise à
respecter en y travaillant — cette section n'en est qu'un résumé.

```text
app/
├── core/                    # config, DB engine, sécurité (JWT), logging, erreurs — jamais spécifique à un module
├── shared/                  # pagination, schémas génériques, devises, géo — réutilisable par tous les modules
├── auth/                    # login/register/refresh/logout
├── identity/                # Organization, User, OrganizationUser
├── rbac/                    # Role, Permission, require_permission()
├── modules_registry/        # registre de modules + activation par organisation
├── billing/                 # plan/subscription/invoice (pas de paiement réel)
├── modules/
│   └── zylo_liquid/         # premier module métier complet — patron pour les futurs modules
│       ├── models.py, schemas.py, service.py, router.py, permissions.py
│       └── algorithms.py, seed.py, dev_seed.py
└── api/v1/                  # agrégation des routers, versionnage REST
```

Chaque domaine (socle ou module métier) suit la même convention interne :
`models.py`, `schemas.py`, `service.py`, `router.py`, `permissions.py`. Un
futur module métier (CRM, Stock...) reprend cette structure à l'identique
sous `app/modules/<domaine>/` — voir `app/modules/CLAUDE.md`.
`core/`/`shared/` ne dépendent jamais d'un module métier (sens unique :
modules → shared/core, jamais l'inverse).

## Sauvegarde

```bash
./scripts/backup.sh                              # dump local + rotation 7 jours
./scripts/restore.sh backups/xxx.sql.gz <db_cible>
```

Voir `docs/phase12-offline-readiness-audit.md` pour l'audit de conformité
offline/synchronisation du socle actuel.

## Git

Stratégie : `main` → `develop` → `remy`. Chaque tâche = une issue + une
branche dédiée, fusionnée dans `remy` après vérification réelle (jamais un
merge automatique sans issue associée).
