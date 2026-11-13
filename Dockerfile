# Image de l'API Zylo Office (T-028, T-051).
#
# Intentions :
# - le CMD ne lance que uvicorn : aucune migration ni seed au démarrage
#   (migrations : `python -m app.cli migrer`, voir docs/operations/) ;
# - build multi-étapes : les outils de build restent dans l'étape `build`, l'image
#   finale ne contient que le venv et le code ;
# - processus exécuté sous un utilisateur non root (uid/gid 10001) ;
# - l'image ne contient ni .env, ni dump, ni sauvegarde (voir .dockerignore).

# ---------------------------------------------------------------------------
# Étape build : dépendances Python dans un venv isolé
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Étape finale : exécution
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# ENVIRONMENT=production explicite (T-002) : les règles strictes de
# app/core/config.py s'appliquent sans dépendre d'une valeur par défaut.
# PORT est fourni par la plateforme de déploiement (Dokploy en production —
# 3004 sur backend.zylooffice.com — 3002 par défaut en local).
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    PORT=3002

# Utilisateur système dédié, sans shell ni répertoire personnel.
RUN groupadd --system --gid 10001 zylo \
    && useradd --system --uid 10001 --gid zylo --home-dir /nonexistent --no-create-home --shell /usr/sbin/nologin zylo

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .
COPY scripts ./scripts

# Seul répertoire d'écriture du conteneur : le stockage local des documents
# (STORAGE_LOCAL_ROOT, ./var/storage). Le lecteur monté doit appartenir à uid 10001
# (voir docs/operations/deploiement.md). Le reste de /app est en lecture seule
# pour l'utilisateur zylo.
RUN mkdir -p /app/var/storage \
    && chown zylo:zylo /app/var/storage

USER 10001:10001

EXPOSE 3002

HEALTHCHECK \
    --interval=30s \
    --timeout=5s \
    --start-period=10s \
    --retries=5 \
    CMD sh -c "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:${PORT}/api/v1/health')\"" || exit 1

# Forme shell : PORT est interpolé au démarrage ; `exec` remplace le shell par
# uvicorn (signaux SIGTERM transmis directement au processus).
# Aucune commande de migration ici : voir app/cli.py.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
