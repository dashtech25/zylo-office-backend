# Prérequis de déploiement du back-end (état au 2026-11-13, gel ebc7ad0)

## Runtime
- Python : 3.12 pour l'image (`Dockerfile`, `python:3.12-slim`). Le venv local est en 3.13.5 : écart mineur (QE-DEP-03).
- Dépendances épinglées dans `requirements.txt` (FastAPI 0.141.1, SQLAlchemy 2.0.36, asyncpg 0.30.0, alembic 1.14.0).
- Base : PostgreSQL 17 (`postgres:17-alpine` dans le `docker-compose.yml` racine). Pilote `postgresql+asyncpg://`.

## Variables d'environnement
- Obligatoires en production (voir `app/core/config.py` et `docs/operations/deploiement.md`) :
  - `ENVIRONMENT=production` (déjà fixé dans le Dockerfile) ;
  - `DATABASE_URL` : pas de mot de passe de repli `changeme` ;
  - `JWT_SECRET` : au moins 32 caractères, pas la valeur de repli ;
  - `STORAGE_SIGNED_URL_SECRET` : au moins 32 caractères, pas la valeur de repli ;
  - `APP_FIELD_ENCRYPTION_KEY` : requise, au moins 32 caractères.
- Démarrage refusé sinon (`ConfigurationSecretError`). Constaté : `ENVIRONMENT=dev` est refusé hors `development`.
- Optionnelles : `PORT` (3002 par défaut), `CORS_ORIGINS`, `EMAIL_*`, `PASSWORD_RESET_URL_BASE`, `ACTIVATION_URL_BASE`, `VAPID_*`, `HOLYKELL_SYNC_*`, `STORAGE_LOCAL_ROOT` (`./var/storage`), limites de débit `AUTH_RATE_LIMIT_*`.
- Modèle : `.env.example` (aucun secret réel). Le fichier `.env` local ne doit jamais être commité (voir QE-SEC-01).

## Base et migrations
- Migrations à lancer HORS démarrage (le CMD ne migre pas) :
  1. `python -m app.cli verifier-revision` (lecture seule) ;
  2. `python -m app.cli migrer --dry-run` ;
  3. `python -m app.cli migrer` (les migrations destructives exigent `--confirmer-destructives --sauvegarde <fichier>`) ;
  4. `python -m app.cli seed` puis `python -m app.cli backfill` (idempotents).
- Sauvegarde préalable : `pg_dump` (procédure dans `docs/operations/deploiement.md`).
- Une seule tête Alembic attendue (vérifiée sur `develop`, tête `54ba4aaf7237` puis tête unique après `ebc7ad0`).

## Démarrage
- Commande : `uvicorn app.main:app --host 0.0.0.0 --port ${PORT}` (CMD du Dockerfile).
- Point d'entrée : `app/main.py`, objet `app`.
- Port : 3002 par défaut dans l'image. Production documentée sur 3004 derrière Dokploy. Le `docker-compose.yml` racine publie `3007:3007` alors que le conteneur écoute sur `PORT` : incohérence (QE-DEP-01).

## Santé
- `GET /api/v1/health` : vivacité, sans base, réponse `{"status":"ok"}`.
- `GET /api/v1/health/ready` : disponibilité, `SELECT 1`, 200 ou 503.
- Healthcheck intégré dans le Dockerfile (intervalle 30 s, sur `/api/v1/health`).

## Conteneurs
- `Dockerfile` : PRÉSENT (build multi-étapes, utilisateur non root uid 10001, `EXPOSE 3002`, HEALTHCHECK).
- `.dockerignore` : PRÉSENT.
- `docker-compose.yml` : PRÉSENT à la racine du projet (`zylo-office/`), hors dépôt back-end. Il charge `zylo-office-backend/.env` : à ne pas utiliser en production.
- Stockage local : `./var/storage` doit appartenir à uid 10001 sur l'hôte.

## Points d'attention
- Aucun secret réel dans le dépôt courant, mais des identifiants figurent dans l'historique publié (QE-SEC-01). Rotation avant tout déploiement.
- Les tests exigent `TEST_DATABASE_URL` de forme `zylo_t<NNN>_test`.
