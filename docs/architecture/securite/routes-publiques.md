# Routes publiques, appartenance et permissions (T-023, achevée par T-019)

Source de vérité : `tests/route_inventory.py::ROUTES_PUBLIQUES` (routes sans portée tenant, avec justification),
`ROUTES_GARDEES_MANUELLEMENT` (signatures vérifiées dans le handler/service), les dépendances FastAPI du
routeur (dont `require_operator`) et `tests/route_baseline_sans_permission.txt` (routes de module sans permission tenant).
Les tests `tests/test_route_inventory.py` et `tests/test_gardes_permissions_routes.py` échouent si
une route change de catégorie sans que la liste soit mise à jour.

## Classement des routes (2026-11-02, 359 routes au total)

| Catégorie | Routes | Garde |
|---|---|---|
| Routes de module gardées par une permission | 278 | `require_permission`, `require_permission_any_scope` ou `require_any_permission` |
| Routes de module, appartenance seule | 2 | `require_module_active` + appartenance : system defaults et ping |
| Webhooks GPS | 2 | Secret d'ingestion d'organisation vérifié dans le service avant traitement |
| Routes avec permission hors module | 32 | `require_permission` ou garde RBAC équivalente |
| Routes avec appartenance hors module | 18 | `require_organization_member` ou filtre de service |
| Routes d'administration plateforme | 5 | `require_operator` : session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS` |
| Routes publiques/statique ou à portée utilisateur sans appartenance tenant | 21 | Chaque route est justifiée individuellement dans `ROUTES_PUBLIQUES` |
| Webhook Flutterwave | 1 | `verif-hash` comparé en temps constant; absent -> 503, invalide -> 401 avant traitement |

## Routes publiques (aucune garde)

Chaque entrée porte sa justification datée dans `ROUTES_PUBLIQUES`. Résumé :

- `GET /`, `GET /api/v1/health`, `GET /api/v1/health/error-demo` : santé et racine. La route de démonstration
  d'erreur est à retirer en production.
- `POST /api/v1/auth/register`, `login`, `activate`, `refresh`, `logout` : routes d'accès sans portée tenant.
  L'inscription publique reste masquée par défaut par `AUTH_PUBLIC_REGISTRATION_ENABLED=false`; le validateur
  `Settings` refuse `true` en production/staging et ne l'admet qu'en `development` ou `test`. L'activation
  consomme un jeton à usage unique (T-021).
- `GET /api/v1/auth/me`, `POST /api/v1/auth/change-password` : portée de l'utilisateur connecté.
- `GET /api/v1/organizations`, `POST /api/v1/organizations` : organisations de l'utilisateur. La création est
  ouverte à tout utilisateur connecté ; le quota (`ORG_CREATION_QUOTA`) attend la valeur fixée par le client.
- `PATCH /api/v1/users/{user_id}` : photo de profil, soi-même ou owner d'une organisation dont la cible est membre.
- `GET /api/v1/storage/local/{storage_reference}` : URL signée.
- `GET /api/v1/modules`, `GET /api/v1/billing/plans` : catalogues en lecture seule, publics en attendant IAM-020.
- `GET /api/v1/billing/payment-provider` : seules métadonnées statiques du provider test (`configured=false`,
  `checkoutAvailable=false`); aucun secret ni état tenant.
- `POST /api/v1/export/xlsx`, `POST /api/v1/export/docx`, `POST /api/v1/import/xlsx` : authentifiés
  (`get_current_user`), sans accès à la base.
- Les routes opérateur sont protégées au niveau du routeur par `require_operator`, qui exige une session et
  l'identifiant utilisateur dans `OPERATOR_READ_USER_IDS`.

## Routes avec garde manuelle de signature

- `POST /api/v1/billing/webhooks/flutterwave` : comparaison constante du `verif-hash`; ne pas la traiter comme
  route publique malgré l'absence d'un bearer utilisateur.
- `POST /api/v1/zylo-liquid/gps/ingest` et `POST /api/v1/zylo-tanker/gps/ingest` : secret propre à
  l'organisation dans `X-GPS-Ingest-Secret`, vérifié par le service avant traitement.

## Routes de module restantes sans permission

Liste figée dans `tests/route_baseline_sans_permission.txt` (4 routes sans permission tenant). Une route de module
nouvelle sans garde de permission fait échouer le test d'inventaire. Les webhooks y restent sans permission
utilisateur mais leur authentification par secret est inscrite dans `ROUTES_GARDEES_MANUELLEMENT`.

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
