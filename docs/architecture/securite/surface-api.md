# Surface de l'API : dépendances, documentation OpenAPI, en-têtes (T-015)

- **Date** : 2026-10-09
- **Branche** : `chore/T-015-dependances-api` (depuis `remy`, commit `17413d0`)
- **Fiche** : `docs/plans/taches/T-015-dependances-surface-api.md`
- **Constats couverts** : BCK-009 (dépendances), BCK-014 (OpenAPI public), BCK-022 (CORS, méthodes et en-têtes)

## 1. Audit des dépendances (pip-audit)

Outil : `pip-audit` 2.10.1, ajouté dans `requirements-dev.txt`. Commandes :

```bash
.venv/bin/pip-audit -r requirements.txt       # production
.venv/bin/pip-audit -r requirements-dev.txt   # production + outillage
```

### Avant (`requirements.txt` d'origine, pins de `remy`)

`Found 44 known vulnerabilities in 5 packages`

| Paquet | Version | Identifiants | Version corrigée |
|---|---|---|---|
| python-dotenv | 1.0.1 | PYSEC-2026-2270 | 1.2.2 |
| python-jose | 3.3.0 | PYSEC-2024-232, PYSEC-2024-233, PYSEC-2025-185 | 3.4.0 (PYSEC-2025-185 : aucune) |
| Pillow | 11.0.0 | 17 identifiants distincts, 33 entrées (PYSEC-2026-165 à 3496) | 12.3.0 couvre tous |
| pytest | 8.3.4 | PYSEC-2026-1845 | 9.0.3 (dépendance de test) |
| ecdsa | 0.19.2 | PYSEC-2026-1325 | aucune (transitif de python-jose) |

### Après

- `pip-audit -r requirements.txt` : **No known vulnerabilities found**.
- `pip-audit -r requirements-dev.txt` : **No known vulnerabilities found**.

### Décisions de montée

- **python-jose remplacé par PyJWT 2.15.1.** La montée à 3.5.0 (dernière version publiée) ne suffisait pas : elle conserve CVE-2026-85394 (GHSA-3qf3-8w2g-rqmx), un correctif incomplet de CVE-2024-33663 qui accepte une clé publique DER comme secret HMAC lorsque l'algorithme n'est pas restreint. Aucune version corrigée n'existe. python-jose tire aussi `ecdsa` (PYSEC-2026-1325, sans correctif prévu côté projet). PyJWT est maintenu et n'a ni l'un ni l'autre. Le code (`app/core/security.py`) passe `algorithms=[JWT_ALGORITHM]` explicitement au décodage ; c'est inchangé.
- **Compatibilité des jetons.** Le format est HS256 standard, identique. Les jetons déjà émis restent valides (voir §5).
- **Pillow 12.3.0**, **python-dotenv 1.2.2**. L'usage de Pillow (miniatures d'upload, `app/shared/storage_router.py`) est encapsulé dans un `try/except` : une régression d'API y serait silencieuse. Le contrôle repose donc sur la suite de tests et une vérification manuelle recommandée des miniatures.
- **pytest 9.0.3 et pytest-asyncio 1.3.0** (dev uniquement). Vérifié par la suite complète : mêmes 21 échecs qu'avant la montée, aucun nouveau.
- **Séparation dev/prod.** `requirements.txt` ne contient plus pytest, pytest-asyncio ni import-linter. `requirements-dev.txt` inclut `requirements.txt` et ajoute l'outillage. Le Dockerfile n'installe que `requirements.txt`. Le CI désactivé (`ci.yml.disabled`) installe désormais `requirements-dev.txt`.

## 2. Documentation OpenAPI

`app/core/securite_http.py` : `options_documentation(ENVIRONMENT)` renvoie `docs_url`, `redoc_url`, `openapi_url` à FastAPI. Ces trois valeurs ne sont renseignées qu'en `development`. Toute autre valeur (production, test, absente, inconnue, casse différente) donne `None` : 404.

Tests (`tests/test_surface_api.py`) :
- fonction pure : ouverte en `development`, fermée pour les autres valeurs ;
- dans le client de test (`ENVIRONMENT=test`) : `/openapi.json`, `/docs`, `/redoc` renvoient 404 ;
- dans un processus Python séparé, configuration réelle : `development` donne 200 sur les trois routes ; `production` avec des secrets propres donne 404 sur les trois.

## 3. En-têtes de sécurité

Ajoutés à chaque réponse HTTP par `EnTetesSecuriteMiddleware` (ASGI pur, comme `RequestIdMiddleware`) :

| En-tête | Valeur |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |

Un en-tête déjà posé par une route n'est jamais écrasé (testé).

Volontairement absent : une CSP. `default-src 'none'` bloquerait les images que le frontend charge depuis l'API (avatars, miniatures). Le durcissement des fichiers téléchargés (type actif, `Content-Disposition: attachment`) relève de T-014 (BCK-008).

## 4. CORS

`app/main.py` : méthodes `GET, POST, PUT, PATCH, DELETE, OPTIONS` et en-têtes `Authorization, Content-Type, X-Organization-Id, Accept`, au lieu de `*`. Ce sont les méthodes et en-têtes réellement utilisés par le frontend (relevé dans `zylo-office-frontend/src`). Les origines restent lues depuis `CORS_ORIGINS`. Testé : méthode `TRACE` et en-tête inconnu refusés au préflight ; méthodes `PATCH`, `PUT`, `DELETE`, `POST` acceptées.

## 5. Jetons existants

Tests dans `tests/test_surface_api.py` :
- deux jetons (accès et rafraîchissement) émis avec python-jose 3.3.0 avant la migration, décodés par `decode_token` ;
- un jeton HS256 au format historique, construit à la main pour un utilisateur créé en base, accepté par `GET /api/v1/auth/me` ;
- rejet : signature d'un autre secret, `alg: none`, jeton expiré, type inattendu.

## 6. Résultats de tests

- Référence (dépendances d'origine, `remy`) : 347 tests, **326 réussis, 21 échecs**.
- Après changements : 367 tests, **346 réussis, 21 échecs**. Les 20 nouveaux tests passent.
- Les 21 échecs sont identiques, nom par nom, à la référence. Ce sont les échecs préexistants que T-006 corrige sur sa branche. Aucun n'est introduit par T-015.

Base de test : `zylo_t015_test` uniquement (`TEST_DATABASE_URL` explicite).

## 7. Limites et points non traités

- **Pas de correctif pour CVE-2026-85394 côté python-jose** : la dépendance est retirée, pas corrigée. Si python-jose revient un jour, reprendre ce constat.
- **Secrets littéraux restants** (fiche T-015, non traités ici) : mot de passe de démo dans `scripts/bootstrap_demo_org.py` (BCK-010), littéraux dans `tests/conftest.py` et `ci.yml.disabled`, valeur de repli de `DATABASE_URL` dans `app/core/config.py`. À traiter avant d'appliquer `git grep` en critère.
- **CORS** : seules méthodes et en-têtes sont restreints. Les origines de production ne sont pas vérifiées dans ce dépôt.
- **Pas de CSP** sur l'API (voir §3).

## 8. Reproduire

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pip-audit -r requirements.txt
.venv/bin/pip-audit -r requirements-dev.txt
TEST_DATABASE_URL=postgresql+asyncpg://<role>@/zylo_t015_test?host=/var/run/postgresql .venv/bin/pytest -q
```
