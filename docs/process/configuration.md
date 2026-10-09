# Configuration du backend : variables et obligations

- **Statut** : en vigueur depuis T-002 (2026-10-08).
- **Source** : `app/core/config.py` (classe `Settings`), lue depuis les variables d'environnement, puis depuis `.env` dans le répertoire de lancement.
- **Décision** : `docs/questions/architecture/environnement-par-defaut.md`.

## 1. Environnement (`ENVIRONMENT`)

| Valeur | Effet |
|---|---|
| absente | traitée comme `production` (défaut de `Settings`) |
| `production` | règles strictes (voir §3) |
| `test` | règles strictes ; `tests/conftest.py` la déclare explicitement |
| `development` | seule valeur qui autorise les secrets de repli (lancement local) |
| autre (ex. `staging`, `Development`) | règles strictes : toute valeur inconnue est traitée comme la production |

Le `Dockerfile` déclare `ENV ENVIRONMENT=production`. Pour un lancement local, mettre `ENVIRONMENT=development` dans le `.env` du worktree ou du dépôt (le modèle `.env.example` le contient déjà).

## 2. Variables et obligations

| Variable | Obligation hors `development` | Règle vérifiée au démarrage |
|---|---|---|
| `ENVIRONMENT` | défaut `production` | valeur lue telle quelle ; tout ce qui n'est pas `development` applique les règles strictes |
| `DATABASE_URL` | obligatoire en pratique | refusée si le mot de passe vaut le mot de passe de repli `changeme` |
| `JWT_SECRET` | obligatoire | refusé s'il vaut la valeur de repli ou fait moins de 32 caractères |
| `STORAGE_SIGNED_URL_SECRET` | obligatoire | refusé s'il vaut la valeur de repli ou fait moins de 32 caractères |
| `APP_FIELD_ENCRYPTION_KEY` | obligatoire hors `development` et `test`, au moins 32 caractères | refusée si absente, vide ou trop courte (déclarée ici, utilisée par T-027) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` | facultatives | vides = canal Web Push désactivé |
| `HOLYKELL_SYNC_BASE_URL` | facultative | vide = boucle de sondage désactivée |
| `STORAGE_S3_ACCESS_KEY`, `STORAGE_S3_SECRET_KEY` | requises si `STORAGE_BACKEND` est S3 | non vérifiées par T-002 |

En `development`, les replis (`JWT_SECRET`, `STORAGE_SIGNED_URL_SECRET`, mot de passe `changeme`) sont acceptés pour le confort local.

## 3. Refus au démarrage

Hors `development`, `Settings` lève `ConfigurationSecretError` à l'import de `app.core.config`. `import app.main` et `uvicorn` s'arrêtent alors avec un code non nul. Le message nomme les variables en cause, jamais leur valeur. Le refus lève une exception qui n'est pas une `ValueError` : pydantic n'y joint donc pas la valeur d'entrée.

Pour générer une valeur forte : `openssl rand -hex 32` (64 caractères).

## 4. Tests

`tests/conftest.py` fixe `ENVIRONMENT=test` et des secrets de test explicites (longs, non issus des replis) avant tout import de l'application. `tests/test_config_secrets.py` couvre le refus, l'acceptation en `development` et les secrets valides, y compris un démarrage en sous-processus.
