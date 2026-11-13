# Audit backend : données, migrations, sécurité API

- Date : 2026-10-08
- Périmètre : `zylo-office-backend` (FastAPI, SQLAlchemy async, Alembic), contrat exposé au frontend `zylo-office-frontend`
- Mode : lecture seule. Aucune migration exécutée, aucune base touchée, aucun contenu de secret lu. Les fichiers `.env`, `.env.migration` et l'archive `backups/*.sql.gz` n'ont été examinés que par leur statut git.
- Statut de tous les items : **Ouvert**

## Limites de la vérification

- `pip-audit` n'est pas installé et le `.venv` est cassé : les CVE des dépendances sont à confirmer (BCK-009).
- Pas de `alembic heads` ni de comparaison autogenerate (interdits : base non touchée). La cohérence modèles/migrations est vérifiée statiquement (BCK-018).
- Les tests `pytest` n'ont pas été lancés.
- Les appels frontend ont été comparés par heuristique (dernier segment statique de chaque route), à confirmer (BCK-020).

## Synthèse

| Priorité | Nombre | IDs |
|---|---|---|
| P0 | 3 | BCK-001, BCK-002, BCK-003 |
| P1 | 8 | BCK-004 à BCK-011 |
| P2 | 7 | BCK-012 à BCK-018 |
| P3 | 6 | BCK-019 à BCK-024 |

Les chemins sont relatifs à `zylo-office-backend/` sauf mention contraire.

## Findings

### BCK-001 : isolation multi-tenant contournable (organisation du chemin vs header)

- Priorité : **P0** | Gravité : **Critique** | État : Ouvert
- Preuves :
  - `app/rbac/service.py:17-23` : l'organisation courante vient uniquement du header `X-Organization-Id`.
  - `app/rbac/service.py:183-196` : `require_permission` vérifie la permission dans l'organisation du header, sans comparer avec `organization_id` du chemin.
  - `app/identity/router.py:53-61` : `PATCH /organizations/{organization_id}` n'a que `require_permission(ORGANIZATION_MANAGE)`.
  - `app/identity/service.py:148-163` : `update_organization` fait `db.get(Organization, organization_id)` sur l'id du chemin, sans contrôle d'appartenance de l'acteur.
  - `app/modules_registry/router.py:45-66` : `activate` et `deactivate` agissent sur l'organisation du chemin avec `MODULE_MANAGE` vérifiée sur le header.
  - `app/billing/router.py:37-43` : `POST /organizations/{organization_id}/subscriptions` avec la même logique.
  - `app/rbac/router.py:64-75` et `app/rbac/router.py:145-150` : création de rôle et de grant sur le chemin. L'escalade de privilèges est contrôlée sur le chemin (`_assert_no_privilege_escalation`, `app/rbac/service.py:456-486`), mais la création elle-même reste possible avec une liste de permissions vide.
  - Contre-exemple (correct) : les routes lecture `/organizations/{id}/...` utilisent `require_organization_member` (`app/identity/service.py:219-240`), qui contrôle l'appartenance à l'organisation du chemin. `app/audit/router.py:18-22` et `app/rbac/router.py:44-49` sont dans ce cas.
- Impact : un utilisateur administrateur d'une organisation A (avec `ORGANIZATION_MANAGE` ou `MODULE_MANAGE` sur A, et header A) peut renommer l'organisation B, activer ou désactiver des modules de B, créer des abonnements de B. Il n'a pas besoin d'être membre de B.
- Recommandation : une dépendance commune qui exige `chemin.organization_id == header` ET appartenance, appliquée à toutes les routes `{organization_id}` (ou dériver l'organisation uniquement du chemin, en vérifiant l'appartenance). Ajouter des tests cross-tenant (utilisateur de A appelant des routes de B = 403/404). Les tests actuels (`tests/test_rbac.py`) ne couvrent pas ce cas.

### BCK-002 : secrets par défaut codés en dur, sans garde-fou en production

- Priorité : **P0** | Gravité : **Critique** | État : Ouvert
- Preuves :
  - `app/core/config.py:26` : `JWT_SECRET` vaut `"changeme-generate-a-real-random-secret"`.
  - `app/core/config.py:37` : `STORAGE_SIGNED_URL_SECRET` a la même valeur par défaut.
  - `app/core/config.py:24` : `DATABASE_URL` par défaut avec mot de passe `changeme`.
  - `app/core/config.py:8` : `ENVIRONMENT` vaut `development` par défaut. Aucun `validator` ne refuse ces valeurs hors développement (aucune occurrence de `model_validator` ou `field_validator` dans `config.py`).
  - `app/core/security.py:53` : `jwt.decode` avec `settings.JWT_SECRET`.
- Impact : si la variable d'environnement n'est pas définie en production, un attaquant peut forger un access token de n'importe quel utilisateur (y compris propriétaire) et des URLs signées de téléchargement de documents.
- Recommandation : faire échouer le démarrage si `ENVIRONMENT != development` et qu'un secret vaut la valeur par défaut ou fait moins de 32 caractères. Vérifier les variables réellement définies en production (hors de ce dépôt).

### BCK-003 : archive de base de données suivie par git

- Priorité : **P0** | Gravité : **Critique** | État : Ouvert
- Preuves :
  - `backups/zylo_office_20260831_180729.sql.gz` est suivi par git (commit `8aea496`, 6,5 Ko).
  - `.gitignore:26` contient `backups/`, donc le fichier a été ajouté avant l'exclusion ou en forçant.
  - Dépôt distant configuré : `origin` = `github.com/dashtech25/zylo-office-backend`.
  - Contenu de l'archive non examiné (conforme à la consigne).
- Impact : des données de base sont présentes dans l'historique git. Si le dépôt distant est public ou largement accessible, il y a fuite de données et de credentials éventuellement contenus.
- Recommandation : vérifier la visibilité du dépôt distant ; retirer le fichier du suivi (`git rm --cached`) ; réécrire l'historique (ex. `git filter-repo`) si le dépôt a été poussé ; considérer les credentials présents dans la base comme compromis et les faire tourner ; ne jamais committer de dump.

### BCK-004 : aucune limitation de débit ni verrouillage sur l'authentification

- Priorité : **P1** | Gravité : **Élevée** | État : Ouvert
- Preuves :
  - `app/auth/router.py:18-22` : `POST /auth/login` sans dépendance de limitation.
  - `app/auth/service.py:45-53` : `authenticate_user` compare le mot de passe sans compteur d'échecs ni verrouillage.
  - Aucune occurrence de `slowapi`, `ratelimit`, `throttl` ou de compteur d'échecs dans `app/` ou `requirements.txt`.
- Impact : attaque par force brute ou par bourrage d'identifiants sur les comptes, y compris propriétaires.
- Recommandation : limiter par IP et par email (ex. `slowapi` ou limitation au niveau du reverse proxy), verrouillage temporaire après N échecs, journalisation des échecs d'authentification.

### BCK-005 : inscription publique sans politique de mot de passe, énumération d'emails

- Priorité : **P1** | Gravité : **Élevée** | État : Ouvert
- Preuves :
  - `app/auth/schemas.py:8` : `password: str` sans longueur minimale ni complexité.
  - `app/auth/router.py:12-15` : `POST /auth/register` ouvert, sans authentification.
  - `app/auth/service.py:20-31` : création d'un utilisateur `status="active"` (`app/identity/service.py`, `build_user`, valeur par défaut), sans vérification d'email.
  - `app/identity/service.py` (`check_email_available`) : retourne une erreur 409 révélant l'existence d'un compte.
- Impact : création de comptes en masse, mots de passe faibles, énumération des emails enregistrés.
- Recommandation : longueur minimale (12 ou plus) et vérification contre les mots de passe compromis ; vérification d'email avant activation ; désactiver l'inscription libre hors cas explicites ; réponse neutre à l'inscription.

### BCK-006 : migrations destructives, exécutées automatiquement au démarrage

- Priorité : **P1** | Gravité : **Élevée** | État : Ouvert
- Preuves :
  - `Dockerfile:33` : `CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app ..."]`. Chaque démarrage de conteneur applique les migrations, sans étape dédiée ni sauvegarde préalable.
  - `alembic/versions/7ffb9473d45e_fuel_product_organization_id.py:26` : `TRUNCATE TABLE "zyloLiquidFuelProduct" CASCADE` (vide la table et ses dépendances).
  - `alembic/versions/1047562d0691_sellable_product_image_and_price.py:63` : `op.drop_table('zyloLiquidSellableProductPrice')`.
  - `alembic/versions/139b3a1a96cb_delivery_tank_chosen_at_delivery.py:94-119` : suppression de colonnes et de tables de livraison.
  - `alembic/versions/00e30f42d09d_gps_tracking_truck_stops.py:97-108` : suppression de tables GPS.
  - `alembic/versions/0240c128e5de_core_geo_tables_and_zylo_liquid_layers_.py:279-291` : suppression de tables de la couche Zylo Liquid.
- Impact : perte de données à la première application d'une migration de ce type ; course entre plusieurs réplicas qui démarrent en même temps ; aucune trace de sauvegarde avant migration.
- Recommandation : sortir `alembic upgrade head` du `CMD` et l'exécuter comme job dédié, une seule fois, précédé d'une sauvegarde vérifiée. Remplacer le `TRUNCATE` par une migration de données non destructive. Revoir les `downgrade()` associés.

### BCK-007 : mot de passe d'un compte externe stocké en clair

- Priorité : **P1** | Gravité : **Élevée** | État : Ouvert
- Preuves :
  - `app/modules/zylo_liquid/models.py:74` : `holykellPassword: Mapped[str] = mapped_column(String(255), nullable=False)`, colonne en clair.
  - `app/modules/zylo_liquid/service.py:4262` et `:4280` : le mot de passe est reçu et persisté tel quel.
  - `app/modules/zylo_liquid/telemetry_sync.py:75` : utilisé directement pour l'appel externe.
  - Les schémas de réponse n'exposent pas ce champ (vérifié : une seule occurrence dans `schemas.py:776`, côté requête).
- Impact : toute lecture de la base (dump, accès SQL, BCK-003) donne les identifiants du compte Holykell.
- Recommandation : chiffrement applicatif de la colonne (clé hors base, ex. KMS ou variable d'environnement dédiée) ou stockage dans un gestionnaire de secrets ; rotation du mot de passe existant.

### BCK-008 : upload sans liste blanche, contenu actif servi depuis l'origine de l'API

- Priorité : **P1** | Gravité : **Élevée** | État : Ouvert
- Preuves :
  - `app/shared/storage_router.py:34-38` : le fichier est lu et stocké sans contrôle de type MIME ni d'extension. Seule la taille (25 Mo, `:23`) est contrôlée.
  - `app/shared/storage.py:75` : l'extension de l'utilisateur est conservée dans la référence de stockage (`splitext(file_name)[1][:20]`).
  - `app/shared/storage_router.py:87` : `Response(content=..., media_type=guessed_type or ...)`. Le type est déduit de l'extension (`mimetypes.guess_type`). Un fichier `.html` ou `.svg` est donc servi avec `text/html` ou `image/svg+xml`, sans `Content-Disposition: attachment` ni `X-Content-Type-Options: nosniff`.
  - Le lien de téléchargement local est signé mais le fichier est servi depuis l'origine de l'API.
- Impact : stockage XSS possible (un utilisateur autorisé uploade du HTML ou du SVG actif, un autre le consulte via le lien signé).
- Recommandation : liste blanche d'extensions et de types (PDF, images, office), réécriture de l'extension selon le type détecté, `Content-Disposition: attachment` pour tout ce qui n'est pas image/PDF, en-têtes `X-Content-Type-Options: nosniff` et CSP `sandbox`, ou servir les fichiers depuis un domaine séparé (S3/MinIO en prod).

### BCK-009 : dépendances anciennes, non auditées

- Priorité : **P1** | Gravité : **Moyenne à élevée** (à confirmer) | État : Ouvert
- Preuves :
  - `requirements.txt:11` : `python-jose[cryptography]==3.3.0`. Des CVE (dont algorithm confusion et JWT bomb) sont corrigées dans une version ultérieure (3.4.0) : à confirmer avec `pip-audit`.
  - `requirements.txt:18` : `Pillow==11.0.0`, ancienne 11.x avec des CVE corrigées plus tard : à confirmer.
  - `requirements.txt` : `pytest`, `import-linter`, `pytest-asyncio` sont en dépendances de production (fichier unique, sans séparation dev/prod).
  - `pip-audit` non installé, `.venv` cassé : non vérifié.
- Impact : vulnérabilités connues dans le parseur JWT et le traitement d'images exposés aux uploads (BCK-008).
- Recommandation : lancer `pip-audit` dans un environnement propre, mettre à jour `python-jose` et `Pillow`, séparer `requirements-dev.txt`.

### BCK-010 : identifiants de démonstration en dur dans un script versionné

- Priorité : **P1** | Gravité : **Moyenne** | État : Ouvert
- Preuves :
  - `scripts/bootstrap_demo_org.py:22` : mot de passe littéral en constante `PASSWORD` (valeur non reproduite ici).
  - Le nom du mot de passe suggère un usage sur un environnement « live ». À confirmer.
- Impact : si ce mot de passe est encore actif sur un environnement accessible, accès direct à un compte.
- Recommandation : lire le mot de passe depuis l'environnement ou le générer aléatoirement ; vérifier et changer le compte concerné ; supprimer la valeur du dépôt.

### BCK-011 : fichier d'environnement sensible non suivi mais non ignoré

- Priorité : **P1** | Gravité : **Moyenne** | État : Ouvert
- Preuves :
  - `git status` : `?? .env.migration` (non suivi, non ignoré).
  - `.gitignore:18` ne couvre que `.env` exact ; `.env.migration` n'est ignoré par aucune règle (`git check-ignore` sans résultat).
  - `.env` est bien ignoré (`!!`).
  - Contenu non examiné.
- Impact : un `git add .` peut committer ce fichier et ses secrets, avec le risque décrit en BCK-003.
- Recommandation : ajouter `.env.*` (en gardant `!.env.example`) à `.gitignore`.

### BCK-012 : limites de taille manquantes sur import XLSX et export

- Priorité : **P2** | Gravité : **Moyenne** | État : Ouvert
- Preuves :
  - `app/shared/import_router.py:27` : `content = await file.read()` sans limite de taille (contrairement à `storage_router.py:23`).
  - `app/shared/export_router.py:32` : `rows: list[list[str]]` sans `max_items`, export en mémoire (`:41`).
- Impact : consommation mémoire et CPU par un utilisateur authentifié (déni de service).
- Recommandation : limite de taille sur l'import, nombre maximal de lignes et de colonnes sur l'export.

### BCK-013 : conteneur exécuté en root

- Priorité : **P2** | Gravité : **Moyenne** | État : Ouvert
- Preuves : `Dockerfile:1` (`FROM python:3.12-slim`) ; aucune directive `USER` dans le fichier.
- Impact : une compromission de l'application donne les droits root dans le conteneur.
- Recommandation : créer un utilisateur non privilégié et ajouter `USER`.

### BCK-014 : documentation OpenAPI exposée sans condition

- Priorité : **P2** | Gravité : **Faible à moyenne** | État : Ouvert
- Preuves : `app/main.py:40` : `FastAPI(title=..., openapi_tags=...)` sans `docs_url=None` ni `openapi_url=None` selon l'environnement. Swagger et `/openapi.json` sont donc publics en production.
- Impact : cartographie complète de l'API pour un attaquant.
- Recommandation : désactiver `docs_url`, `redoc_url` et `openapi_url` hors `development`.

### BCK-015 : jetons en `localStorage`, rotation sans détection de réutilisation

- Priorité : **P2** | Gravité : **Moyenne** | État : Ouvert
- Preuves :
  - Frontend `zylo-office-frontend/src/core/auth/tokens.ts:6-21` : access et refresh tokens dans `localStorage`. Un XSS donne accès aux deux.
  - `app/auth/service.py:67-84` : `rotate_refresh_token` refuse un token révoqué (401) mais ne révoque pas la famille de tokens. Une réutilisation après rotation n'alerte pas et ne coupe pas la session de l'attaquant.
  - Points conformes : refresh tokens stockés hachés (SHA-256, `app/auth/service.py:16-17`), rotation effective, expiration configurée (`app/core/config.py:28-29`).
- Impact : vol de session après XSS ; réutilisation d'un refresh token volé non détectée.
- Recommandation : refresh token en cookie `HttpOnly; Secure; SameSite` (restreint au chemin `/auth`) ; révoquer toute la famille en cas de réutilisation ; durée d'access token déjà courte (15 min) à conserver.

### BCK-016 : tâches de fond et seeds lancés à chaque process

- Priorité : **P2** | Gravité : **Moyenne** | État : Ouvert
- Preuves :
  - `app/main.py:80-100` : `on_startup` exécute seeds et backfills (permissions, modules, rôles) à chaque démarrage et pour chaque process.
  - `app/main.py:116` : boucle de sondage Holykell (`holykell_sync_loop`) démarrée dans chaque process.
  - `app/main.py:126` : boucle `structural_sweep_loop` démarrée dans chaque process, sans verrou.
  - `Dockerfile:33` : pas de `--workers` explicite, mais tout passage à plusieurs réplicas dupliquerait les sondages.
- Impact : doubles appels vers Holykell, écritures concurrentes sur les seeds/backfills, comportement non déterministe à l'échelle.
- Recommandation : verrou (advisory lock PostgreSQL) ou process dédié pour les boucles de fond ; seeds en job de migration.

### BCK-017 : exceptions avalées sans trace

- Priorité : **P2** | Gravité : **Moyenne** | État : Ouvert
- Preuves (échantillon, relevé par grep) :
  - `app/shared/storage.py:32` : `pass` ; `app/shared/storage.py:122` : `except Exception:` (l'erreur disparaît).
  - `app/location/service.py:431`, `:509`, `:523` : `except Exception:` sans journalisation vérifiée.
  - `app/modules/zylo_liquid/service.py:2585` : `pass` ; une vingtaine de `except Exception:` dans le même fichier (ex. `:3091`, `:5432`, `:5436`, `:7081`, `:14471`).
  - `app/modules/zylo_liquid/telemetry_sync.py:144`, `:162`, `:178`, `:194` : `except Exception:`.
  - Points conformes : le gestionnaire global journalise (`logger.exception`, `app/core/errors.py`) et renvoie un message générique (pas de fuite de stack trace).
- Impact : erreurs métier ou d'intégration silencieuses (ex. données de télémétrie perdues sans alerte).
- Recommandation : restreindre les exceptions attrapées, journaliser avec `logger.exception` là où l'erreur est avalée, ajouter des tests sur les chemins d'erreur.

### BCK-018 : cohérence modèles SQLAlchemy / migrations (vérification statique)

- Priorité : **P2** | Gravité : **Moyenne** (non confirmée) | État : Ouvert
- Preuves :
  - Tête alembic unique : `f1a3b5c7d849` (`alembic/versions/f1a3b5c7d849_cash_summary.py`), relevé statique sur 67 fichiers de révision. Pas de têtes multiples détectées.
  - 113 `__tablename__` dans les modèles ; 98 `create_table` relevés. Les tables restantes (ex. `zyloLiquidShiftReportCashLine`) sont créées via une variable (`_LINE`, `alembic/versions/d9e1f3a5b627_cash_collection.py:26`) : faux positif, pas de divergence avérée.
  - 291 `ForeignKey` dans les modèles contre 45 fichiers de migration contenant une FK ; 207 `index=True` contre 240 `create_index`. Comparaison non exhaustive.
- Impact : divergence possible entre le schéma réel et les modèles (FK, index ou contraintes manquants), non vérifiée.
- Recommandation : comparer en lecture seule l'état réel d'une copie de base avec `alembic check` ou autogenerate, dans un environnement isolé (non réalisé ici).

### BCK-019 : endpoints de démonstration et de test accessibles

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves :
  - `app/api/v1/endpoints/health.py:13-19` : `GET /api/v1/health/error-demo` public, lève une erreur 418 (le code note « à retirer »).
  - `app/identity/router.py:64-71` : `GET /organizations/{id}/protected-demo`.
  - `app/modules_registry/router.py:72-80` : `GET /organizations/{id}/zylo-liquid/protected-demo`.
- Impact : surface inutile en production ; les routes protégées ne sont pas dangereuses en soi.
- Recommandation : supprimer ou ne monter qu'en `development`.

### BCK-020 : routes sans consommateur frontend (heuristique)

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves : 39 routes sur 293 dont le dernier segment statique n'apparaît pas dans `zylo-office-frontend/src`. Principalement : `app/modules/zylo_liquid/router.py` (27 : déclarations incident, test d'étanchéité, jaugeage manuel, contrôle qualité, autorisations, chauffeurs, rapports de sections, prix sellables), `app/location/router.py` (6 : commentaires et rapprochements d'arrêts de navire), `app/billing/router.py` (2 : plans).
- Impact : code mort ou fonctionnalités backend non exposées ; surface d'attaque inutile.
- Recommandation : confirmer chaque route avec le frontend (certaines peuvent être appelées via des chemins construits), supprimer ou documenter celles qui ne servent pas.

### BCK-021 : router de localisation monté deux fois

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves : `app/api/v1/router.py:35` (sous `/zylo-liquid`) et `app/api/v1/router.py:53` (sous `/zylo-tanker`) : `location_router` est inclus deux fois, avec les mêmes handlers.
- Impact : entrées OpenAPI dupliquées, identifiants d'opération dupliqués, risque de divergence future.
- Recommandation : monter une seule fois et documenter le besoin, ou séparer les routers.

### BCK-022 : CORS trop permissif sur les méthodes et en-têtes

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves : `app/main.py:52-57` : `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`. Les origines sont explicites (`app/core/config.py:10-20`), ce qui limite le risque.
- Impact : surface plus large que nécessaire.
- Recommandation : liste explicite des méthodes et des en-têtes utilisés ; origines de production lues depuis l'environnement.

### BCK-023 : pas de contrat OpenAPI versionné

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves : aucun fichier `openapi.json` dans le dépôt ; le frontend appelle les routes par chaînes saisies à la main (`core/api/client.ts`).
- Impact : dérive silencieuse entre backend et frontend, non détectée à l'intégration.
- Recommandation : exporter le schéma OpenAPI en CI et générer les types client, ou ajouter des tests de contrat.

### BCK-024 : documentation de démarrage incohérente

- Priorité : **P3** | Gravité : **Faible** | État : Ouvert
- Preuves : le backend écoute par défaut sur `PORT=3002` (`app/core/config.py`), la commande de `CLAUDE.md` utilise le port 3007, le frontend cible `http://localhost:3007` par défaut (`src/core/api/client.ts:3`). Le README mentionne aussi d'autres ports.
- Impact : erreurs de configuration locale.
- Recommandation : une seule source de vérité pour les ports, documentée.

## Points conformes

- Aucune requête SQL brute ni concaténation SQL détectée (`text(`, `execute(f"...")`) : accès via l'ORM SQLAlchemy.
- Mots de passe hachés avec bcrypt ; refresh tokens stockés hachés.
- Routes métier : 282 décorateurs de route, presque tous avec une dépendance d'authentification (les exceptions sont `/health`, `/`, la clé VAPID publique et les routes signées de téléchargement local).
- Objets métier accédés par identifiant (zylo_liquid, files) vérifient l'organisation (ex. `app/files/service.py:172-178`, `app/modules/zylo_liquid/service.py:5255-5262`).
- Téléchargement local signé avec expiration et comparaison à temps constant (`app/shared/storage.py`, `hmac.compare_digest`).
- Erreurs : format unique, message générique pour les 500 (`app/core/errors.py`).
- Migrations : une seule tête détectée statiquement ; aucune table de modèle absente après contrôle des faux positifs.
- `.env` et `var/` sont ignorés par git ; `.env` n'est pas suivi.

## Prochaines actions suggérées (ordre)

1. BCK-003 et BCK-011 : retirer le dump du suivi, purger l'historique si nécessaire, faire tourner les credentials.
2. BCK-002 : refuser le démarrage hors développement avec des secrets par défaut.
3. BCK-001 : corriger l'isolation multi-tenant et ajouter des tests cross-tenant.
4. BCK-004, BCK-005 : limitation de débit et politique d'inscription.
5. BCK-006 : sortir les migrations du démarrage, sauvegarde avant migration.
6. BCK-007, BCK-008, BCK-009, BCK-010 : chiffrement des secrets, upload sûr, mises à jour des dépendances, suppression des credentials de démo.
