# Zylo Office — Backend

Socle backend de Zylo Office, une plateforme ERP/CRM modulaire inspirée
d'Odoo/Dolibarr. Cette première phase construit uniquement le **socle**
(identité, organisations, rôles, permissions, modules, abonnements) — aucun
module métier (CRM, Stock, zylo_liquid...) n'est encore implémenté. Voir
`grande_phases.md` (racine du projet, hors ce dépôt) pour l'architecture
complète et le détail des 15 phases.

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

```text
app/
├── core/              # config, DB engine, sécurité (JWT), logging, erreurs
├── shared/            # pagination, schémas génériques, mixins de modèles
├── auth/              # login/register/refresh/logout
├── identity/          # Organization, User, OrganizationUser
├── rbac/              # Role, Permission, require_permission()
├── modules_registry/  # registre de modules + activation par organisation
├── billing/           # plan/subscription/invoice (pas de paiement réel)
└── api/v1/            # agrégation des routers
```

Chaque domaine du socle suit la même convention interne :
`models.py`, `schemas.py`, `service.py`, `router.py`, `permissions.py` — un
futur module métier (ex: `zylo_liquid`) reprendra exactement cette structure
sous `app/modules/`.

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
