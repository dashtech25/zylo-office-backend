# Prérequis de déploiement du back-end Zylo Office sur Dokploy (lecture seule)

Périmètre analysé : `/home/remy/Desktop/travail/dashtech/zylo/projet en cours/zylo-office/office/zylo-office-backend` (branche `develop`, HEAD `ebc7ad0`). Aucun fichier du dépôt modifié, aucun test lancé. Les valeurs secrètes ne sont pas reproduites.

## 1. Runtime et démarrage
- Python 3.12 (`python:3.12-slim`, build multi-étapes), FastAPI 0.141.1, Uvicorn 0.52.4, SQLAlchemy 2.0.36 + asyncpg 0.30.0, Alembic 1.14.0.
- Point d'entrée : `app/main.py`, objet `app`. CMD : `sh -c "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"`. Le CMD ne migre rien.
- Port : variable `PORT`, défaut 3002 (ENV de l'image). `EXPOSE 3002` est purement indicatif. Dokploy doit fournir `PORT` et router vers ce même port (la doc évoque 3004 en production).
- Contexte de build : le dossier `zylo-office-backend/` (le Dockerfile copie `app`, `alembic`, `alembic.ini`, `scripts`). Aucune dépendance système : toutes les dépendances Python ont des wheels manylinux pour 3.12.
- Utilisateur d'exécution : uid/gid 10001, non root.

## 2. Dockerfile et compose
- `zylo-office-backend/Dockerfile` : PRÉSENT, complet, cohérent avec `app/cli.py` et la doc de déploiement. HEALTHCHECK sur `/api/v1/health`.
- `zylo-office-backend/.dockerignore` : PRÉSENT, exclut `.env*`, `var`, `backups`, `tests`, `docs`, `*.md`, dumps.
- `docker-compose.yml` : présent seulement à la racine `zylo-office/` (hors dépôt back-end), à usage dev uniquement (port backend 3007 alors que le conteneur écoute sur `PORT`, `env_file` sur `.env`). Ne pas l'utiliser pour Dokploy. Dokploy doit builder depuis le Dockerfile.

## 3. Santé
- `GET /api/v1/health` : vivacité, sans base, `{"status":"ok"}`.
- `GET /api/v1/health/ready` : `SELECT 1`, 200 ou 503.
- Route de démonstration `GET /api/v1/health/error-demo` (HTTP 418) exposée hors développement : à retirer (signalé par son propre docstring).
- Au démarrage (`on_startup`) : `verifie_revision_a_jour()`. Si la base n'est pas à la tête Alembic, le process refuse de démarrer.

## 4. Base de données
- PostgreSQL, pilote `postgresql+asyncpg://` obligatoire (`DATABASE_URL`, lu par `app/core/config.py` et `alembic/env.py`).
- Version : la doc (`implementation-backend/PREREQUIS-DEPLOIEMENT.md`) et le compose disent PostgreSQL 17 ; les tests ont tourné sur PG 16. Version cible à confirmer (QE à ouvrir si besoin).
- Extensions : aucune `CREATE EXTENSION` trouvée. `gen_random_uuid()` est natif (PG 13+). Une doc de revue mentionne `UNIQUE NULLS NOT DISTINCT` (PG 15+) : à vérifier dans les migrations avant de figer la version.
- Pool SQLAlchemy : `pool_size=20`, `max_overflow=20`, par réplica : prévoir `max_connections` Postgres en conséquence.
- Piège probable : avec Neon, le paramètre SSL doit être `?ssl=require` (asyncpg), pas `sslmode=` (à vérifier sur la base réelle).

## 5. Migrations et seed (manuelles, hors démarrage)
Dans l'ordre, une fois par déploiement, avec le même environnement que le conteneur :
1. `python -m app.cli verifier-revision` (lecture seule)
2. `python -m app.cli migrer --dry-run`
3. `python -m app.cli migrer` (si révision destructive : `--confirmer-destructives --sauvegarde <fichier>`)
4. `python -m app.cli seed`
5. `python -m app.cli backfill`
Sauvegarde `pg_dump` préalable, faite hors conteneur (le conteneur n'a pas `pg_dump`/`psql`).
Dokploy n'exécute pas ces commandes automatiquement : il faut un lancement one-off (terminal du conteneur ou `docker run --env-file`). Le premier démarrage échoue tant que l'étape 3 n'est pas faite.

## 6. Variables d'environnement lues par `app/core/config.py` (classe `Settings`)
Obligatoire = le démarrage est refusé sans elle (hors `development`). Sinon le défaut s'applique. « None » = non défini, la fonctionnalité répond 503 ou est désactivée.

### Démarrage et sécurité (obligatoires en production)
- `DATABASE_URL` : OBLIGATOIRE en pratique. Défaut local avec mot de passe `changeme`, refusé hors développement.
- `JWT_SECRET` : OBLIGATOIRE. Au moins 32 caractères, pas la valeur de repli. Refus sinon.
- `STORAGE_SIGNED_URL_SECRET` : OBLIGATOIRE. Au moins 32 caractères, pas la valeur de repli.
- `APP_FIELD_ENCRYPTION_KEY` : OBLIGATOIRE (vide par défaut). Au moins 32 caractères.
- `ENVIRONMENT` : défaut `production` ; la valeur `production` doit rester. Dockerfile la fixe déjà.

### Application, réseau, CORS
- `PORT` : défaut 3002 (Dokploy doit le fixer).
- `APP_NAME` : défaut « Zylo Office Backend ».
- `CORS_ORIGINS` : liste JSON. Défaut : localhost 3001 et 3055 uniquement. À CONFIGURER pour l'origine du frontend de production, sinon le navigateur est bloqué (pas de refus au démarrage). Jamais `*`.
- `HEALTH_INTERNAL_NETWORKS` : défaut vide (route `/internal/ready` en 404). Optionnel.
- `AUTH_RATE_LIMIT_TRUSTED_PROXIES` : défaut vide. À renseigner si Traefik/Dokploy est un proxy de confiance (sinon l'IP vue est celle du proxy).

### Base et JWT (optionnels avec défauts)
- `JWT_ALGORITHM` : HS256 (défaut). `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` : 15. `JWT_REFRESH_TOKEN_EXPIRE_DAYS` : 30.

### Sessions et cookies
- `AUTH_COOKIE_SECURE` : défaut None, donc Secure hors développement. Le frontend doit être servi en HTTPS.
- `AUTH_COOKIE_SAMESITE` : lax (défaut). `AUTH_COOKIE_DOMAIN` : None (hôte exact).
- `AUTH_PUBLIC_REGISTRATION_ENABLED` : false (défaut). `true` refusé hors development/test.
- `AUTH_HEADER_ACCEPTED_UNTIL` : 2026-11-30 00:00 UTC (défaut, date proposée à CONFIRMER avant déploiement). Après cette date, plus de jeton dans le corps JSON, cookies seuls.

### Stockage documentaire
- `STORAGE_BACKEND` : `local` (défaut) ou `s3`.
- `STORAGE_LOCAL_ROOT` : `./var/storage` (défaut, soit `/app/var/storage` dans l'image). Volume persistant requis si `local` (propriétaire uid 10001).
- `STORAGE_SIGNED_URL_TTL_SECONDS` : 900.
- `STORAGE_S3_ENDPOINT_URL` : None. `STORAGE_S3_BUCKET` : `zylo-office-documents`. `STORAGE_S3_REGION` : `us-east-1`. `STORAGE_S3_ACCESS_KEY` et `STORAGE_S3_SECRET_KEY` : None (requis si `s3`, pas de refus explicite constaté au démarrage).

### E-mail (invitations, réinitialisation)
- `EMAIL_BACKEND` : `none` (défaut). Tant que ce n'est pas `smtp`, la création de comptes par invitation est désactivée (503). Pour `smtp` en production, validateur strict.
- `EMAIL_SMTP_HOST`, `EMAIL_SMTP_FROM_ADDRESS` : requis si `smtp`. `EMAIL_SMTP_USERNAME`, `EMAIL_SMTP_PASSWORD` (secret) : requis si `smtp`. `EMAIL_SMTP_STARTTLS` : true obligatoire. `EMAIL_SMTP_PORT` : 587. `EMAIL_SMTP_TIMEOUT_SECONDS` : 10 (1 à 60).
- `ACTIVATION_URL_BASE` : `http://localhost:3001/activer` (défaut). À CONFIGURER pour la production.
- `PASSWORD_RESET_URL_BASE` : `http://localhost:3001/forgot-password` (défaut). Avec `smtp` : doit être HTTPS, sans query ni fragment, et finir par `/forgot-password`, sinon démarrage refusé.
- `USER_INVITATION_TTL_HOURS` : 72. `PASSWORD_RESET_TTL_MINUTES` : 30 (1 à 60).

### Limitation d'authentification et quotas (défauts raisonnables)
- `AUTH_RATE_LIMIT_ENABLED` : true. `AUTH_RATE_LIMIT_WINDOW_SECONDS` : 900. `AUTH_RATE_LIMIT_MAX_FAILURES_PER_ACCOUNT` : 10. `AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP` : 100. `AUTH_RATE_LIMIT_LOCK_BASE_SECONDS` : 60. `AUTH_RATE_LIMIT_LOCK_MAX_SECONDS` : 900.
- `RATE_LIMIT_MAX_REQUETES` : 600 ; `RATE_LIMIT_FENETRE_SECONDES` : 60 ; `QUOTA_PRODUIT_MAX_REQUETES` : 600 ; `QUOTA_PRODUIT_FENETRE_SECONDES` : 60 ; `LIMITE_TECHNIQUE_MAX_REQUETES` : 1200 ; `LIMITE_TECHNIQUE_FENETRE_SECONDES` : 60.
- `IDEMPOTENCY_KEY_TTL_HOURS` : 24.

### Boucles en processus
- `HOLYKELL_SYNC_BASE_URL` : None (boucle désactivée). `HOLYKELL_SYNC_INTERVAL_SEC` : 5.
- `STRUCTURAL_SWEEP_INTERVAL_SEC` : 300 (toujours active).
- Ne pas dépasser un réplica (doc `deploiement.md`, point BCK-016).

### Web Push (optionnel)
- `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` : vides = canal désactivé (secret pour la privée). `VAPID_CLAIMS_EMAIL` : `contact@zylo.example` (à remplacer).

### Valeurs NON DÉFINIES (None) : la fonctionnalité répond 503 ou refuse de tourner tant qu'elles ne sont pas fournies
- `FLAGS_DUREE_CANARI_HEURES`, `FLAGS_SEUIL_ARRET_CANARI` (canari, 422).
- `ADMIN_PREVIEW_TTL_SECONDS` (prévisualisation opérateur, 503).
- `DEFAULT_LOCALE` (textes de repli si absent, non bloquant).
- `AUDIT_EXPORT_EXPIRATION_SECONDS`, `EXPORT_EXPIRATION_SECONDS` (exports, 503).
- `BACKUP_FREQUENCE` (vide), `BACKUP_RPO_HEURES`, `BACKUP_RETENTION_JOURS` (aucune sauvegarde planifiée).
- `WEBHOOK_FENETRE_ANTI_REJEU_SECONDS` (réception des webhooks, 503).
- `EVENTS_CONSUMER_MAX_TENTATIVES` (consommation d'événements, refuse de tourner).
- `INTEGRATION_BACKOFF_BASE_SECONDS`, `INTEGRATION_BACKOFF_CAP_SECONDS` (politique de reprise refusée).

### Variables lues hors `Settings` (`os.environ` / `os.getenv`)
- Quota et droits plateforme (allowlists d'identifiants utilisateur, CSV d'UUID, vide = personne) : `PLATFORM_MODULE_WRITE_USER_IDS`, `PLATFORM_CATALOG_MANAGE_USER_IDS`, `PLATFORM_EVENEMENTS_READ_USER_IDS`, `PLATFORM_MODULE_PUBLISH_USER_IDS`, `PLATFORM_RECONCILIATION_RESOLVE_USER_IDS`, `PLATFORM_MODULE_SUSPEND_USER_IDS`, `PLATFORM_TENANT_MANAGE_USER_IDS`, `PLATFORM_MAINTENANCE_RUN_USER_IDS`. Optionnelles.
- `OPERATOR_READ_USER_IDS` : allowlist opérateur (optionnelle).
- `MIGRATION_LOCK_TIMEOUT` : `30s` (défaut).
- `TRUCK_STOP_DETECTION_THROTTLE_SECONDS` : `30` (défaut).
- Paiement Flutterwave (stub, pas d'appel réseau) : `FLUTTERWAVE_MODE` (défaut `test`), `FLUTTERWAVE_TEST_SECRET_KEY` (secret, optionnelle), `FLUTTERWAVE_WEBHOOK_SECRET` (secret, optionnelle : webhook refusé sinon).
- `BILLING_SERVICE_TOKEN` (secret, optionnelle : endpoint de droits d'abonnement refusé sinon).
- Hors application (scripts seulement) : `HOLYKELL_SYNC_*`, `STATION_SIM_DSN`, `TEST_DATABASE_URL` (tests uniquement, nom `zylo_t<NNN>_test`).

## 7. Services externes
- PostgreSQL : OBLIGATOIRE.
- SMTP : requis pour les invitations et la réinitialisation (sinon fonctionnalités désactivées).
- S3 ou MinIO : optionnel (`STORAGE_BACKEND=s3`). Sinon volume local.
- Holykell (API simulateur ou réelle) : optionnel.
- Redis : aucun usage trouvé.
- Traefik/Dokploy : proxy HTTPS devant le conteneur (à configurer pour `AUTH_COOKIE_SECURE` et les IP de confiance).

## 8. Volumes persistants
- `/app/var/storage` si `STORAGE_BACKEND=local` : volume persistant, propriétaire `10001:10001` sur l'hôte.
- Aucun autre volume. La base est externe au conteneur.

## 9. Build
- Commande : `docker build -f Dockerfile .` depuis `zylo-office-backend/`.
- Dépendances système : aucune pour le build Python. Le conteneur n'a ni `pg_dump` ni `psql` : les fonctions de sauvegarde/restauration (`app/operator/restauration.py`, `scripts/backup.sh`, `restore.sh`) ne peuvent pas tourner depuis l'image.

## 10. Blocants et points d'attention

Blocants pour un premier déploiement :
1. Fournir `DATABASE_URL`, `JWT_SECRET`, `STORAGE_SIGNED_URL_SECRET`, `APP_FIELD_ENCRYPTION_KEY` (32 caractères minimum, valeurs propres). Sans elles, démarrage refusé.
2. Lancer les migrations (étapes 1 à 5, section 5) avant le premier démarrage : sinon le démarrage est refusé.
3. Volume persistant `/app/var/storage` (uid 10001) si stockage local.
4. Secrets exposés dans le dépôt Git : `.env` était versionné dans le premier commit `29aea1b` (retiré ensuite par `107433f`). Il contient une URL de base de données Neon avec mot de passe en commentaire. Rotation obligatoire avant tout déploiement (rappel QE-SEC-01).

Non bloquants au démarrage mais bloquants fonctionnellement :
5. `CORS_ORIGINS`, `ACTIVATION_URL_BASE`, `PASSWORD_RESET_URL_BASE` : à configurer sur le domaine de production, sinon les liens et le navigateur ne fonctionnent pas.
6. `EMAIL_BACKEND=smtp` + variables SMTP : sans elles, aucune invitation ni réinitialisation.
7. `AUTH_HEADER_ACCEPTED_UNTIL` (2026-11-30) : date à confirmer ; à 13/11/2026, l'échéance est dans 17 jours. Vérifier que le frontend utilise les cookies.
8. Une seule réplique : boucles Holykell et balayage structurel dans le processus.

À vérifier avant le premier déploiement :
9. Version PostgreSQL cible (17 annoncée, 16 testée) et contrainte `NULLS NOT DISTINCT` (PG 15+) si utilisée.
10. Format SSL de `DATABASE_URL` pour Neon (`ssl=require`).
11. `AUTH_RATE_LIMIT_TRUSTED_PROXIES` : IP du proxy Dokploy/Traefik si X-Forwarded-For doit être lu.
12. Retirer la route `/api/v1/health/error-demo`.

Aucun élément ne manque dans le dépôt pour construire et démarrer l'image : Dockerfile, .dockerignore, requirements, migrations, CLI, health sont présents.
