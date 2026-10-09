# Routes publiques, appartenance et permissions (T-023, achevée par T-019)

Source de vérité : `tests/route_inventory.py::ROUTES_PUBLIQUES` (routes sans aucune garde) et
`tests/route_baseline_sans_permission.txt` (routes de module sans garde de permission).
Les tests `tests/test_route_inventory.py` et `tests/test_gardes_permissions_routes.py` échouent si
une route change de catégorie sans que la liste soit mise à jour.

## Classement des routes (2026-10-09, 301 routes au total)

| Catégorie | Routes | Garde |
|---|---|---|
| Routes de module gardées par une permission | 239 (198 ajoutées par T-019) | `require_permission` (organisation entière), `require_permission_any_scope` (liste ou création dont le service filtre par station), `require_any_permission` (l'une de deux permissions) |
| Routes de module, appartenance seule | 2 | `require_module_active` + appartenance : `GET /zylo-liquid/system-defaults` (constantes globales en lecture seule), `GET /zylo-tanker/ping` (sonde du module) |
| Webhooks GPS, secret d'ingestion | 2 | secret d'ingestion de l'organisation, vérifié dans le service (401 `invalid_ingest_secret`) |
| Permission déjà en place hors module (billing, géographie, devises, identité) | 30 | `require_permission` |
| Publiques par nature (santé, racine, authentification) | 8 | aucune donnée d'organisation |
| Portée utilisateur (profil, mot de passe, ses organisations, photo de profil) | 5 | contrôle dans le service sur l'utilisateur connecté |
| Catalogues en lecture seule (modules, plans) | 2 | publics en attendant IAM-020 |
| Utilitaires authentifiés sans base (export, import) | 3 | `get_current_user`, aucun accès à la base |
| Téléchargement par URL signée | 1 | signature vérifiée dans le service |
| Appartenance hors module (annuaire, catalogue des permissions, audit, upload) | 9 | `require_organization_member` ou filtre de service ; décision à confirmer (voir ci-dessous) |

## Routes publiques (aucune garde)

Chaque entrée porte sa justification datée dans `ROUTES_PUBLIQUES`. Résumé :

- `GET /`, `GET /api/v1/health`, `GET /api/v1/health/error-demo` : santé et racine. La route de démonstration
  d'erreur est à retirer en production.
- `POST /api/v1/auth/register`, `login`, `activate`, `refresh`, `logout` : authentification. Inscription,
  connexion et activation sont limitées par T-012 ; l'activation consomme un jeton à usage unique (T-021).
- `GET /api/v1/auth/me`, `POST /api/v1/auth/change-password` : portée de l'utilisateur connecté.
- `GET /api/v1/organizations`, `POST /api/v1/organizations` : organisations de l'utilisateur. La création est
  ouverte à tout utilisateur connecté ; le quota (`ORG_CREATION_QUOTA`) attend la valeur fixée par le client.
- `PATCH /api/v1/users/{user_id}` : photo de profil, soi-même ou owner d'une organisation dont la cible est membre.
- `GET /api/v1/storage/local/{storage_reference}` : URL signée.
- `GET /api/v1/modules`, `GET /api/v1/billing/plans` : catalogues en lecture seule, publics en attendant IAM-020.
- `POST /api/v1/export/xlsx`, `POST /api/v1/export/docx`, `POST /api/v1/import/xlsx` : authentifiés
  (`get_current_user`), sans accès à la base.
- `POST /api/v1/zylo-liquid/gps/ingest`, `POST /api/v1/zylo-tanker/gps/ingest` : webhooks GPS, secret d'ingestion
  de l'organisation dans l'en-tête `X-Gps-Ingest-Secret`.

## Routes de module restantes sans permission

Liste figée dans `tests/route_baseline_sans_permission.txt` (4 routes). Une route de module nouvelle sans garde de
permission fait échouer le test d'inventaire. La liste ne doit que diminuer.

- `POST /api/v1/zylo-liquid/gps/ingest`, `POST /api/v1/zylo-tanker/gps/ingest` : webhooks (secret, voir ci-dessus).
- `GET /api/v1/zylo-liquid/system-defaults` : constantes globales (seuils d'algorithme), lecture seule, aucune
  donnée d'organisation.
- `GET /api/v1/zylo-tanker/ping` : sonde du module.

## Retraits et changements de comportement (T-019)

- `POST /api/v1/billing/plans` : **retirée**. Tout utilisateur connecté pouvait créer un plan (IAM-003). Le catalogue
  est désormais seedé hors API (option A de `docs/questions/rbac/permission-plateforme.md`, recommandation vérifiée).
  Aucune permission de plateforme n'est créée. Un plan de même code avec un prix différent renvoie 409
  (`plan_conflict`).
- Les routes de module gardées par `require_permission_any_scope` renvoient désormais 403 `permission_denied` à un
  utilisateur qui ne détient la permission nulle part, là où elles renvoyaient une liste vide.
- Les mises à jour de déclaration (`PATCH .../declarations/{id}`) exigent la permission de création du type de
  déclaration (l'auteur seul peut modifier, contrôle dans le service).

## Décisions attendues

- Catalogues publics : passage authentifié (`docs/questions/securite/catalogues-publics.md`, recommandation : authentifiés).
- Appartenance seule hors module (`GET .../rbac/.../members`, `.../roles`, `.../roles/{id}`, `.../permissions`,
  `POST /storage/upload`) : l'annuaire de l'organisation est lisible par tout membre. Une permission dédiée
  (par exemple `identity.user.manage` ou `rbac.role.manage`) serait plus stricte ; à trancher avec le client.
