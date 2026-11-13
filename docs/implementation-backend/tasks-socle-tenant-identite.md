# Tâches back-end — socle tenant et identité (ZYLO-OFFICE-BACKEND-PLAN, agent BE-SOC)

- **Domaine :** socle back-end : organisations (tenant), identité, authentification, RBAC et isolation tenant, registre et activation des modules, facturation (lecture et adaptateur neutre), audit, notifications, console opérateur.
- **Date :** 2026-11-03. **Modèle :** Haiku 5.5, effort medium. **Périmètre :** back-end uniquement. Le front-end n'apparaît que pour ses contrats (routes, payloads, codes d'erreur).
- **Base des chemins de route :** `/api/v1` (préfixe monté dans `app/main.py` : `include_router(api_router, prefix="/api/v1")`). Tous les chemins écrits ci-dessous sont complets, préfixe inclus. L'administration utilise `/api/v1/admin` ; le mot unique des ressources d'organisation est `organizations`.
- **Sources lues** (relatives à `definition-travail/`) :
  - `00-pilotage/architecture-fondation/phases/PH-07-modele-saas-organisations.md`
  - `00-pilotage/architecture-fondation/phases/PH-08-identite-utilisateurs-securite.md`
  - `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md` (lu en entier, par sections)
  - `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md`
  - `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md`
- **Plage d'identifiants :** BE-001 à BE-039. Utilisée : BE-001 à BE-039 (39 tâches, plage complète). Aucun blocage de plage.
- **Règle appliquée :** toute valeur absente des sources est écrite « NON DÉFINI » suivie d'une recommandation. Les codes HTTP attendus en refus viennent des sources (403 pour accès refusé, 404 pour élément absent) ; les autres codes sont des recommandations marquées NON DÉFINI.

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-001 | Contrat d'erreurs, request ID et format de succès | 0 | aucune |
| BE-002 | Organisation (tenant racine) : modèle et migrations | 0 | BE-001 |
| BE-003 | Utilisateur global et unicité du courriel | 0 | BE-001 |
| BE-004 | Appartenance utilisateur–organisation | 0 | BE-002, BE-003 |
| BE-005 | Authentification : connexion, session, limitation des tentatives | 3 | BE-001, BE-003 |
| BE-006 | Inscription publique fermée par défaut | 1 | BE-005 |
| BE-007 | Journal d'audit métier (écriture) | 0 | BE-002, BE-003 |
| BE-008 | RBAC : rôles, permissions, grants (modèle) | 0 | BE-004 |
| BE-009 | Garde serveur de contexte organisation et d'autorisation | 0 | BE-004, BE-005, BE-008 |
| BE-010 | Organisation courante : lecture du contexte | 1 | BE-001, BE-009 |
| BE-011 | Réglages d'organisation minimum | 2 | BE-007, BE-008, BE-010 |
| BE-012 | Invitations : création et jeton à usage unique | 2 | BE-004, BE-007, BE-008, BE-009 |
| BE-013 | Activation de compte invité | 1 | BE-005, BE-007, BE-012 |
| BE-014 | Membres de l'organisation : liste et retrait | 2 | BE-007, BE-008, BE-009 |
| BE-015 | Affectation des rôles aux membres | 1 | BE-007, BE-008, BE-014 |
| BE-016 | Lecture des rôles et permissions | 2 | BE-008, BE-009 |
| BE-017 | Grants allow/deny par utilisateur | 2 | BE-007, BE-008, BE-015 |
| BE-018 | Changement de mot de passe du compte | 1 | BE-005, BE-007 |
| BE-019 | Récupération et réinitialisation du mot de passe | 2 | BE-003, BE-005, BE-007 |
| BE-020 | Profil de compte en lecture seule | 1 | BE-003, BE-005 |
| BE-021 | Registre des modules et états de module (modèle) | 0 | BE-002 |
| BE-022 | Catalogue et activation des modules par organisation | 2 | BE-007, BE-008, BE-009, BE-021 |
| BE-023 | Plans, versions et abonnement (modèle et migrations) | 0 | BE-002 |
| BE-024 | Entitlements d'abonnement (modèle et calcul) | 0 | BE-021, BE-023 |
| BE-025 | Garde d'accès module fail-closed (projection canOpen / canActivate) | 1 | BE-009, BE-022, BE-024 |
| BE-026 | Abonnement et droits de l'organisation courante (lecture) | 2 | BE-009, BE-024 |
| BE-027 | Factures et tentatives de paiement (lecture) | 2 | BE-009, BE-023 |
| BE-028 | Adaptateur de paiement neutre (stub, sandbox, aucun débit) | 0 | BE-027 |
| BE-029 | Évènements webhook de paiement (idempotence) | 0 | BE-028 |
| BE-030 | Journal opérateur des lectures sensibles | 0 | BE-001, BE-007 |
| BE-031 | Console opérateur en lecture seule | 3 | BE-001, BE-022, BE-026, BE-030 |
| BE-032 | Statut technique du service (health, readiness) | 2 | BE-001 |
| BE-033 | Journal d'audit consultable par l'administrateur d'organisation | 1 | BE-007, BE-009 |
| BE-034 | Abonnement push et désabonnement côté serveur | 2 | BE-003, BE-005 |
| BE-035 | Boîte de réception des notifications | 2 | BE-003, BE-009 |
| BE-036 | Cycle de vie de l'organisation : états et transitions (bloqué par décision) | 3 | BE-002, BE-007, BE-009 |
| BE-037 | Réconciliation ORM et migrations (password_reset_token, notification_inbox_item) | 0 | BE-019, BE-035 |
| BE-038 | Suite adversariale d'isolation tenant et de permissions HTTP | 0 | BE-011, BE-015, BE-017, BE-022, BE-026, BE-027, BE-031, BE-033, BE-035 |
| BE-039 | Inventaire global tables, propriétaires, portées et tests | 0 | BE-037, BE-038 |

---

## Tâches

### BE-001 — Contrat d'erreurs, request ID et format de succès (livré en revue statique, preuve dynamique à produire)
- Domaine : transverse, API
- Vague : 1
- Routes : aucune (s'applique à toutes les routes `/api/v1`)
- Tables / migrations : aucune
- Droits : aucun droit propre. Codes couverts par les tests : 404 (route inconnue, code `http_404`), 405 (méthode non permise, code `http_405`), 500 (erreur inattendue, code `internal_error`). Erreur de validation : 422, code `validation_error` (constaté dans `app/core/errors.py`).
- Format d'erreur (décision D1, propriétaire unique de l'enveloppe) : corps `{"error": {"code": str, "message": str, "field_errors": {chemin: [message, ...]}, "details": [...]}, "request_id": str}`. `field_errors` donne le chemin pointé sans préfixe `body`/`query`/`path` ; `details` est vide sauf pour les erreurs de validation (liste Pydantic sans `input` ni `ctx`). Le message des erreurs HTTP Starlette reste dans la langue fournie par Starlette. Les en-têtes `X-Request-Id` et `X-Correlation-Id` portent la même valeur que `request_id`. Les tâches qui réutilisent cette enveloppe (BE-010, BE-070, BE-180, BE-220) déclarent BE-001 et ne la redéfinissent pas.
- Format de succès : pas d'enveloppe ; le corps est l'objet renvoyé (ex. `GET /api/v1/health` renvoie `{"status": "ok"}`). Les collections peuvent utiliser le format `Page` (`data`, `meta`) de `app/shared/schemas.py`, mais toutes les listes existantes ne l'utilisent pas (ex. liste des organisations : tableau nu). Ce format ne change pas dans BE-001.
- Dépendances : aucune
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : une route inconnue renvoie 404 avec `error.code` = `http_404`, `error.message` et un `request_id` au niveau racine.
  - CA-2 : une méthode non permise sur une route existante renvoie 405 au même format d'erreur (`error.code` = `http_405`).
  - CA-3 : une erreur 500 renvoie `error.code` = `internal_error`, un `request_id` identique à celui du journal serveur (événement `unhandled_error`), et le corps ne contient ni trace ni détail interne.
  - CA-4 : une erreur de validation renvoie 422, `error.code` = `validation_error`, `error.field_errors` et ne contient ni `input` ni `ctx` dans `error.details`.
  - CA-5 : une réponse de succès sur un endpoint témoin (`GET /api/v1/health`) garde son format antérieur (test de contrat).
  - CA-6 : un en-tête `X-Request-Id` ou `X-Correlation-Id` fourni par le client est repris dans la réponse s'il respecte le motif `^[A-Za-z0-9._:-]{1,128}$` ; sinon un identifiant UUID est généré.
- Code existant (develop) : `app/core/errors.py` (`AppError`, gestionnaires d'exceptions 422 `validation_error`, HTTP `http_<statut>`, 500 `internal_error`, enveloppe ci-dessus) ; `app/core/middleware.py` (`RequestIdMiddleware` : `X-Request-Id` et `X-Correlation-Id`, `TimingMiddleware`) ; `app/shared/schemas.py` (`ApiErrorBody`, `ApiErrorResponse`, `Page`, déclarés pour OpenAPI) ; `app/api/v1/endpoints/health.py` (`GET /api/v1/health`, `GET /api/v1/health/error-demo`) ; garder : enveloppe, codes `validation_error` / `internal_error` / `http_<statut>`, en-têtes de corrélation, `app/shared/schemas.py` ; casser : la route de démonstration `/api/v1/health/error-demo`, à retirer une fois un test d'erreur réel en place.
- Documentation attendue : docstrings de chaque handler public ; doc de module pour `app/core/errors.py`, `app/core/middleware.py`, `app/shared/schemas.py` ; mise à jour de `docs/architecture/conventions-api.md`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#4. État de réalisation` ; `#Tableau de suivi persistant P0` (ligne « Shared PermissionState + contrat API »).

### BE-002 — Organisation (tenant racine) : modèle et migrations
- Domaine : organisation (tenant)
- Vague : 2
- Routes : aucune
- Tables / migrations : `organization` (modèle `app/identity/models.py::Organization`, création dans `alembic/versions/4b1cccdb5fd5_identity_rbac_and_auth_tables.py`). Colonnes clés observées : `name` (nom), `slug` (identifiant, unique), `status` (défaut `active`) ; suppression logique (`deletedAt`, mixin `SoftDeleteMixin`). Autres colonnes : NON DÉFINI (QE-SOC-10). Cardinalité compte / payeur / Organization : NON DÉFINI (QE-SOC-01).
- Code existant (develop) : `app/identity/models.py` (classe `Organization`, table `organization`, colonnes ci-dessus) ; migration `4b1cccdb5fd5_identity_rbac_and_auth_tables.py` ; garder : table, colonnes `name` / `slug` / `status`, unicité de `slug` ; casser : rien d'imposé par BE-002.
- Droits : aucun endpoint. Accès aux données via BE-009. Refus interne : une lecture de repository sans contexte d'organisation est refusée.
- Dépendances : BE-001
- Critères d'acceptation :
  - CA-1 : créer une organisation puis la relire restitue nom, identifiant et statut à l'identique.
  - CA-2 : un second enregistrement avec le même identifiant est refusé par la base (recommandation appliquée, QE-SOC-10).
  - CA-3 : aucune fonction publique de lecture ne retourne plusieurs organisations sans paramètre de portée (test unitaire).
  - CA-4 (refus) : un appel de repository sans contexte d'organisation lève une erreur (test unitaire).
  - CA-5 (isolation) : lire l'organisation O2 avec le contexte de O1 ne retourne aucune donnée.
- Documentation attendue : docstrings des fonctions publiques ; doc de module `app/identity/models.py` (section organisation).
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Tenant / organisation` ; `00-pilotage/architecture-fondation/phases/PH-07-modele-saas-organisations.md#Critères d'acceptation`.

### BE-003 — Utilisateur global et unicité du courriel
- Domaine : identité
- Vague : 2
- Routes : aucune
- Tables / migrations : `user` (modèle `app/identity/models.py`) ; migrations `4b1cccdb5fd5_identity_rbac_and_auth_tables.py` et `c5a1d9e3f7b2_user_email_lower_unique.py` (courriel unique insensible à la casse, index unique sur `lower(email)`). Colonnes clés : `email` (String 320, unique), `hashedPassword` (String 255, condensat bcrypt via passlib), `fullName`, `status` (`active` | `suspended` | `pending`), `mustChangePassword`.
- Code existant (develop) : `app/identity/models.py` (classe `User`, table `user`, colonnes ci-dessus, index `uq_user_email_lower`) ; `app/core/security.py` (`hash_password` / `verify_password`, `CryptContext` bcrypt) ; garder : table `user`, index insensible à la casse, condensat bcrypt ; casser : rien d'imposé par BE-003.
- Droits : aucun endpoint. Un utilisateur est global ; son accès est donné par BE-004.
- Dépendances : BE-001
- Critères d'acceptation :
  - CA-1 : créer un utilisateur puis un second avec le même courriel en casse différente est refusé.
  - CA-2 : un mot de passe n'est jamais stocké en clair (test sur la colonne après création).
  - CA-3 (refus) : un utilisateur inexistant n'obtient aucune session (test).
  - CA-4 (isolation) : un même courriel rattaché à deux organisations n'existe qu'en une seule ligne `user`.
- Documentation attendue : docstrings publiques ; doc de module `app/identity/models.py`.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Identité / appartenance` ; `00-pilotage/architecture-fondation/phases/PH-08-identite-utilisateurs-securite.md#Questions à résoudre et clarification`.

### BE-004 — Appartenance utilisateur–organisation
- Domaine : identité / organisation
- Vague : 3
- Routes : aucune (utilisée par BE-010, BE-014)
- Tables / migrations : `organization_user` (modèle `OrganizationUser`), association plusieurs-à-plusieurs entre `user` et `organization`. Colonnes clés : identifiant utilisateur, identifiant organisation, statut d'appartenance (NON DÉFINI, QE-SOC-04). Migration `4b1cccdb5fd5`.
- Droits : aucun endpoint. Utilisateur non membre d'une organisation : refus sur toute ressource de cette organisation, code 404 (recommandation, QE-SOC-05).
- Dépendances : BE-002, BE-003
- Critères d'acceptation :
  - CA-1 : un utilisateur rattaché à O1 et O2 a deux contextes distincts (test).
  - CA-2 (refus) : un utilisateur non rattaché à O2 n'obtient aucune donnée de O2 ; code 404 (test).
  - CA-3 (isolation) : supprimer l'appartenance retire l'accès à la requête suivante (test).
- Documentation attendue : docstrings publiques ; doc de module `app/identity/models.py`.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Identité / appartenance` ; `00-pilotage/architecture-fondation/phases/PH-07-modele-saas-organisations.md#Questions à résoudre et clarification`.

### BE-005 — Authentification : connexion, session, limitation des tentatives
- Domaine : identité / authentification
- Vague : 3
- Routes :
  - `POST /api/v1/auth/login` (connexion ; source : `/api/v1/auth/login` 200 dans la reprise)
  - `GET /api/v1/auth/me` (session ; source : `/api/v1/auth/me` 200 dans la reprise)
  - `POST /api/v1/auth/refresh` (existe dans develop, `app/auth/router.py` : renouvellement de session par cookie ; corps accepté seulement pendant la transition)
  - BE-005 porte ces routes ; BE-188 n'en garde que la déconnexion (QE-API-32). Hors périmètre de cette tâche : `POST /api/v1/auth/logout` (porté par BE-188).
- Tables / migrations : `refresh_token`, `login_attempt` (`app/auth/models.py`) ; migration `a9b8c7d6e5f4_login_attempt_rate_limit.py`. Colonnes clés : NON DÉFINI.
- Droits : aucune permission requise pour la connexion. `GET /api/v1/auth/me` exige une session. Session absente : code NON DÉFINI (recommandation 401, QE-SOC-05). Identifiants invalides : code NON DÉFINI (recommandation 401, même réponse que compte inexistant). Trop de tentatives : code NON DÉFINI (recommandation 429). Seuil de tentatives : NON DÉFINI (QE-SOC-08).
- Dépendances : BE-001, BE-003
- Critères d'acceptation :
  - CA-1 : connexion valide renvoie 200 ; `GET /api/v1/auth/me` renvoie 200 avec l'utilisateur de la session.
  - CA-2 : mauvais mot de passe et compte inexistant renvoient la même réponse et le même délai approximatif (test d'énumération).
  - CA-3 (refus) : `GET /api/v1/auth/me` sans session est refusé (code NON DÉFINI, recommandation 401).
  - CA-4 (refus) : au-delà du seuil NON DÉFINI, la connexion est bloquée pour la fenêtre définie (test).
  - CA-5 : une session révoquée ne permet plus `GET /api/v1/auth/me` (test).
  - CA-6 (isolation) : deux sessions simultanées renvoient chacune uniquement leur utilisateur (test).
- Documentation attendue : docstrings des routes et services ; doc de module `app/auth/` (chemin existant).
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Hydratation du login` ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Authentification P0 »).

### BE-006 — Inscription publique fermée par défaut
- Domaine : identité / authentification
- Vague : 4
- Routes :
  - `POST /api/v1/auth/register` (succès 201 observé en parcours API)
- Tables / migrations : `user` ; `organization` si l'inscription crée aussi une organisation (NON DÉFINI, QE-SOC-04).
- Droits : aucune permission. Garde de configuration `AUTH_PUBLIC_REGISTRATION_ENABLED`, fermée par défaut et en production. Refus si fermée : 404, code `registration_disabled` (comportement de develop, `app/auth/router.py`). Recommandation appliquée : conserver 404 pour ne pas révéler la route. | QE-SOC-21
- Dépendances : BE-005
- Critères d'acceptation :
  - CA-1 (refus) : avec la garde fermée, `POST /api/v1/auth/register` renvoie 404 `registration_disabled` et aucun utilisateur n'est créé (test).
  - CA-2 : avec la garde ouverte, l'inscription renvoie 201 et crée un utilisateur (test).
  - CA-3 : en environnement de production sans configuration explicite, l'inscription est refusée (test).
  - CA-4 (isolation) : l'inscription ne crée aucune appartenance à une organisation existante (test).
- Documentation attendue : docstring de la route ; doc de module `app/auth/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Authentification P0 ») ; `#Journal chronologique des mises à jour` (entrée 2026-11-02, garde signup).

### BE-007 — Journal d'audit métier (écriture)
- Domaine : audit
- Vague : 3
- Routes : aucune (écriture par les services ; lecture en BE-033)
- Tables / migrations : table unique `audit_event` (décision D2). Propriétaire : BE-007, qui renomme la table existante `audit_log` (modèle `app/audit/models.py::AuditLog`, migration `d77282efbbb2_user_permission_grant_and_audit_log.py`). Toute tâche qui écrit ou lit une entrée d'audit déclare BE-007 et réutilise ses colonnes ; aucune autre table d'audit n'est créée. La table develop `operator_audit_log` (`app/operator/audit_models.py`) est reprise dans `audit_event` puis retirée : NON DÉFINI : Recommandation appliquée : reprise des lignes avec `action` préfixée `operator.`, puis retrait de `operator_audit_log` (tâche BE-030) | QE-SOC-22.
  - Colonnes existantes (develop) : `organizationId`, `actorUserId`, `action`, `entityType`, `entityId`, `scopeResourceType`, `scopeResourceId`, `summary`, `changes`, `ipAddress`, `userAgent`, `createdAt`.
  - Colonnes absentes de develop, ajoutées par la migration de renommage : request ID et résultat. Recommandation appliquée : `request_id` (String, obligatoire) et `result` (`success` | `refused` | `error`). | QE-SOC-22
  - Colonnes demandées par BE-122, BE-152 et BE-227, ajoutées par la même migration (vérification de cohérence) : `eventId` (String, unique, obligatoire pour toute nouvelle ligne ; renseigné pour les lignes reprises), `actorType` (`humain` | `service` | `systeme`), `reason` (motif, nullable), `approvalId` (référence d'approbation, nullable), `schemaVersion` (entier), `visibility`, `dataClassification`. `organizationId` devient nullable pour la portée plateforme. Correspondances sans colonne ajoutée : `correlationId` = `request_id` (BE-122, BE-227) ; `occurredAt` = `createdAt` (BE-152) ; les champs sans colonne demandés par BE-122 (acteur de service, contexte d'authentification, catégorie, ticket de motif, initiateur, approbateur, références d'état avant et après, statut de notification, durée de fenêtre) sont portés dans `changes` (JSON), sans nouvelle colonne.
  - Colonnes à trancher : rétention et exhaustivité (NON DÉFINI, QE-SOC-14).
- Code existant (develop) : `app/audit/models.py` (classe `AuditLog`, table `audit_log`, colonnes ci-dessus sans request ID) ; `app/audit/service.py` et `app/audit/router.py` (existants, à adapter) ; garder : colonnes existantes, index ; casser : nom de table `audit_log` (renommé en `audit_event`).
- Droits : aucun endpoint. Écriture sans acteur ou sans identifiant d'organisation : refusée (erreur interne, code NON DÉFINI).
- Dépendances : BE-002, BE-003
- Critères d'acceptation :
  - CA-1 : chaque mutation sensible de BE-011, BE-015, BE-017, BE-018, BE-022 produit exactement une entrée (test).
  - CA-2 : chaque entrée contient le request ID de la requête (test).
  - CA-3 (refus) : une écriture sans acteur ou sans organisation est refusée et ne crée aucune ligne (test).
  - CA-4 : le mot de passe, les jetons et les secrets n'apparaissent jamais dans une entrée (test).
  - CA-5 (isolation) : une entrée de O1 porte l'identifiant de O1 et n'est jamais écrite sous O2 (test).
- Documentation attendue : docstrings publiques ; doc de module `app/audit/` (existant).
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Audit` ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-4 : audit des mutations).

### BE-008 — RBAC : rôles, permissions, grants (modèle)
- Domaine : RBAC
- Vague : 4
- Routes : aucune (lecture en BE-016)
- Tables / migrations : `role`, `permission`, `role_permission`, `user_role`, `user_permission_grant` (`app/rbac/models.py`). `resourceType` et `resourceId` ajoutés à `user_role` par `95e8bd6bf477_user_role_scoped_assignment.py`. Grants et journal par `d77282efbbb2_user_permission_grant_and_audit_log.py`. Codes de permission : NON DÉFINI (QE-SOC-06). Précédence allow/deny : NON DÉFINI (QE-SOC-07).
- Droits : aucun endpoint. Un rôle sans portée sur une ressource ne donne aucun accès sur cette ressource (refus).
- Dépendances : BE-004
- Critères d'acceptation :
  - CA-1 : une affectation de rôle avec portée ressource ne s'applique qu'à la ressource indiquée (test).
  - CA-2 (refus) : un utilisateur sans rôle sur une ressource est refusé (test, code 403).
  - CA-3 : un grant `deny` l'emporte sur un `allow` pour la même permission (recommandation appliquée, QE-SOC-07 ; test).
  - CA-4 (isolation) : un rôle défini pour O1 n'est pas applicable à O2 (test).
- Documentation attendue : docstrings des modèles et fonctions de résolution ; doc de module `app/rbac/models.py`.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#RBAC` ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-4).

### BE-009 — Garde serveur de contexte organisation et d'autorisation
- Domaine : organisation / RBAC
- Vague : 5
- Routes : aucune directe. Dépendance transverse appliquée à toutes les routes d'organisation (BE-010 à BE-036).
- Tables / migrations : aucune nouvelle.
- Droits : toute requête d'organisation porte un contexte d'organisation vérifié côté serveur, jamais le seul paramètre client. Accès absent ou refusé : 403 (source P0-2 et P0-7). Organisation hors appartenance ou ressource d'une autre organisation : 404 (recommandation, QE-SOC-05). Session invalide : 401 (recommandation, QE-SOC-05). Chemin prévu : `app/rbac/guards.py` (recommandation).
- Dépendances : BE-004, BE-005, BE-008
- Critères d'acceptation :
  - CA-1 (refus) : une requête d'organisation sans session est refusée (test, 401 recommandé).
  - CA-2 (refus) : une requête avec session valide mais sans appartenance à l'organisation demandée est refusée en 403 (test).
  - CA-3 (isolation) : un paramètre d'organisation O2 envoyé avec une session O1 est refusé (test, 404 recommandé).
  - CA-4 (isolation) : un identifiant de ressource de O2 deviné avec le contexte O1 renvoie la même réponse qu'une ressource inexistante (test).
  - CA-5 : changer l'organisation active met à jour le périmètre ; les données de l'ancienne organisation ne sont plus retournées (test).
- Documentation attendue : docstring de la dépendance ; doc de module `app/rbac/guards.py`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-2) ; `#5. Tranches de code : livrables et critères` (tranche E, isolation tenant).

### BE-010 — Organisation courante : lecture du contexte
- Domaine : organisation
- Vague : 6
- Routes :
  - `GET /api/v1/organizations/current` (existe dans develop, `app/identity/router.py` ; organisation résolue par l'en-tête `X-Organization-Id` après contrôle d'appartenance)
- Tables / migrations : `organization`, `organization_user`.
- Droits : membre authentifié. Permission de lecture : NON DÉFINI (QE-SOC-06). Non-membre : 403 (source P0-2 et P0-7).
- Dépendances : BE-001, BE-009
- Critères d'acceptation :
  - CA-1 : un membre reçoit l'organisation active avec son identifiant, son nom et son statut (200, test).
  - CA-2 (refus) : sans session, la route est refusée (test).
  - CA-3 (isolation) : l'organisation d'un autre tenant n'est jamais retournée, même avec un identifiant forcé (test).
  - CA-4 : une erreur de lecture renvoie un état d'erreur structuré du format BE-001 avec `request_id` (test).
- Documentation attendue : docstring de la route ; doc de module `app/identity/` (organisation courante).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « API organisation courante », 4 tests ciblés rapportés).

### BE-011 — Réglages d'organisation minimum
- Domaine : organisation
- Vague : 7
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/settings` (QE-SOC-04)
  - NON DÉFINI : `PUT /api/v1/organizations/current/settings` (QE-SOC-04)
- Tables / migrations : `organization` (nom, identifiant, statut) ; `audit_event` (BE-007).
- Droits : lecture pour tout membre ; écriture exige une permission d'administration des réglages, code NON DÉFINI (recommandation `organization.settings.update`, QE-SOC-06). Refus : 403. Organisation hors appartenance : 404.
- Dépendances : BE-007, BE-008, BE-010
- Critères d'acceptation :
  - CA-1 : sauvegarder le nom, relire après rechargement, la valeur persiste (test).
  - CA-2 (refus) : un membre sans permission d'écriture reçoit 403 et la valeur ne change pas (test).
  - CA-3 (isolation) : un administrateur de O1 ne modifie jamais les réglages de O2 (test, 404 recommandé).
  - CA-4 : une modification réussie crée une entrée d'audit (test).
  - CA-5 : un nom vide est refusé avec `field_errors` au format BE-001 (test ; code HTTP NON DÉFINI, recommandation 422).
- Documentation attendue : docstrings de la route et du service ; doc de module `app/identity/` (réglages).
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Journal de reprise ISS-084` (sauvegarde puis rechargement des paramètres) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-4).

### BE-012 — Invitations : création et jeton à usage unique
- Domaine : identité / organisation
- Vague : 6
- Routes :
  - NON DÉFINI : `POST /api/v1/organizations/current/invitations` (QE-SOC-04)
  - NON DÉFINI : `GET /api/v1/organizations/current/invitations` (liste des invitations en attente, QE-SOC-04)
- Tables / migrations : `user_invitation` (`app/identity/models.py`) ; migration `e7f8a9b0c1d2_creation_utilisateurs_invitations.py`. Colonnes clés : destinataire, organisation, rôle proposé, état, expiration (NON DÉFINI, QE-SOC-09).
- Droits : permission d'inviter, code NON DÉFINI (recommandation `organization.members.invite`, QE-SOC-06). Refus : 403. Invitation d'une autre organisation : 404.
- Dépendances : BE-004, BE-007, BE-008, BE-009
- Critères d'acceptation :
  - CA-1 : un administrateur crée une invitation ; elle apparaît dans la liste de son organisation (test).
  - CA-2 (refus) : un membre sans permission d'inviter reçoit 403 et aucune invitation n'est créée (test).
  - CA-3 (isolation) : la liste des invitations de O1 ne contient aucune invitation de O2 (test).
  - CA-4 : le jeton d'invitation n'est stocké que sous forme de condensat (test sur la base).
  - CA-5 : une invitation créée ouvre une entrée d'audit (test).
- Documentation attendue : docstrings des routes et du service ; doc de module `app/identity/` (invitations).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-1 : invitation limitée au destinataire et à l'organisation) ; `#Tableau de suivi persistant P0` (« Authentification P0 — invitation/activation »).

### BE-013 — Activation de compte invité
- Domaine : identité
- Vague : 7
- Routes :
  - NON DÉFINI : `POST /api/v1/auth/activate` (activation par jeton ; QE-SOC-04)
- Tables / migrations : `user_invitation`, `user`, `organization_user`.
- Droits : aucune permission ; jeton valide requis. Jeton inconnu, expiré ou déjà consommé : même réponse, code NON DÉFINI (recommandation 404, QE-SOC-05).
- Dépendances : BE-005, BE-007, BE-012
- Critères d'acceptation :
  - CA-1 : un jeton valide crée ou active l'utilisateur et l'appartenance à l'organisation de l'invitation (test).
  - CA-2 (refus) : un jeton réutilisé est refusé et ne crée rien (test).
  - CA-3 (refus) : un jeton expiré est refusé (test ; délai d'expiration NON DÉFINI, QE-SOC-09).
  - CA-4 (isolation) : un jeton émis pour O1 n'octroie aucune appartenance à O2 (test).
  - CA-5 : l'activation ouvre une entrée d'audit (test).
- Documentation attendue : docstring de la route ; doc de module `app/identity/` (activation).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (activation 6 tests et limitation de débit, rapportés PASS) ; `#Priorisation stricte pour permettre l'usage initial` (P0-1).

### BE-014 — Membres de l'organisation : liste et retrait
- Domaine : organisation / identité
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/members` (QE-SOC-04)
  - NON DÉFINI : `DELETE /api/v1/organizations/current/members/{userId}` (QE-SOC-04)
- Tables / migrations : `organization_user`, `user`, `user_role`.
- Droits : lecture des membres : permission NON DÉFINI (recommandation `organization.members.read`, QE-SOC-06). Retrait : permission `organization.members.remove`, code NON DÉFINI (QE-SOC-06). Refus : 403. Retrait du rôle propriétaire par un non-propriétaire : refusé, 403 (recommandation, QE-SOC-16).
- Dépendances : BE-007, BE-008, BE-009
- Critères d'acceptation :
  - CA-1 : la liste ne contient que les membres de l'organisation active ; états vide, erreur et refus distincts (test).
  - CA-2 (refus) : un membre sans permission de retrait reçoit 403 et l'appartenance est conservée (test).
  - CA-3 (isolation) : la liste de O1 n'expose aucun membre de O2 (test).
  - CA-4 : le retrait révoque l'accès dès la requête suivante et crée une entrée d'audit (test).
  - CA-5 : le rôle propriétaire est immuable pour un non-propriétaire, conformément aux contrôles observés (test).
- Documentation attendue : docstrings des routes et services ; doc de module `app/identity/` (membres).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Membres/rôles + API membres/catalogue ») ; `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Journal de reprise ISS-084` (contrôles immuables du rôle propriétaire).

### BE-015 — Affectation des rôles aux membres
- Domaine : RBAC
- Vague : 7
- Routes :
  - NON DÉFINI : `PUT /api/v1/organizations/current/members/{userId}/roles` (QE-SOC-04)
- Tables / migrations : `user_role` (`resourceType`, `resourceId`) ; `audit_event`.
- Droits : permission d'administration des rôles, code NON DÉFINI (QE-SOC-06). Refus : 403. Rôle d'une autre organisation : 404 (recommandation, QE-SOC-05). L'affectation est revalidée côté serveur, jamais sur le seul affichage UI.
- Dépendances : BE-007, BE-008, BE-014
- Critères d'acceptation :
  - CA-1 : une affectation valide persiste et est revalidée côté serveur (test).
  - CA-2 (refus) : un membre sans permission reçoit 403 et aucune affectation n'est modifiée (test).
  - CA-3 (refus) : un non-propriétaire ne peut ni attribuer ni retirer le rôle propriétaire (test, QE-SOC-16).
  - CA-4 (isolation) : un rôle de O2 ne peut être affecté dans O1 (test).
  - CA-5 : chaque affectation crée une entrée d'audit (test).
- Documentation attendue : docstrings de la route et du service ; doc de module `app/rbac/` (affectations).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Membres/rôles + API membres/catalogue », assignations revalidées serveur).

### BE-016 — Lecture des rôles et permissions
- Domaine : RBAC
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/roles` (QE-SOC-04)
  - NON DÉFINI : `GET /api/v1/organizations/current/roles/{roleId}` (QE-SOC-04)
- Tables / migrations : `role`, `permission`, `role_permission`.
- Droits : permission de lecture des rôles, code NON DÉFINI (QE-SOC-06). Refus : 403. Rôle d'une autre organisation : 404.
- Dépendances : BE-008, BE-009
- Critères d'acceptation :
  - CA-1 : le rôle propriétaire renvoie ses 12 permissions en lecture (test ; nombre observé en reprise).
  - CA-2 (refus) : un membre sans permission de lecture reçoit 403 (test).
  - CA-3 : toute écriture sur ces routes (PUT, PATCH, DELETE) renvoie 405 (test, lecture seule).
  - CA-4 (isolation) : un rôle de O2 demandé avec le contexte de O1 renvoie 404 (test).
- Documentation attendue : docstrings des routes ; doc de module `app/rbac/`.
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Journal de reprise ISS-084` (routes `/roles` et `/roles/[roleId]`, 12 permissions en lecture seule).

### BE-017 — Grants allow/deny par utilisateur
- Domaine : RBAC
- Vague : 8
- Routes :
  - NON DÉFINI : `POST /api/v1/organizations/current/members/{userId}/grants` (QE-SOC-04)
  - NON DÉFINI : `DELETE /api/v1/organizations/current/members/{userId}/grants/{grantId}` (QE-SOC-04)
- Tables / migrations : `user_permission_grant` ; `audit_event`.
- Droits : permission d'administration des droits, code NON DÉFINI (QE-SOC-06). Refus : 403. Grant sur un utilisateur ou une permission hors organisation : 404.
- Dépendances : BE-007, BE-008, BE-015
- Critères d'acceptation :
  - CA-1 : un grant `allow` puis un grant `deny` sur la même permission donnent le résultat `deny` (test, QE-SOC-07).
  - CA-2 (refus) : un membre sans permission d'administration reçoit 403 et aucun grant n'est créé (test).
  - CA-3 (isolation) : un grant ne peut viser un utilisateur de O2 depuis O1 (test).
  - CA-4 : chaque création ou suppression crée une entrée d'audit (test).
- Documentation attendue : docstrings ; doc de module `app/rbac/` (grants).
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#RBAC` (grants allow/deny).

### BE-018 — Changement de mot de passe du compte
- Domaine : identité / compte
- Vague : 4
- Routes :
  - NON DÉFINI : `POST /api/v1/account/password` (page source `/account/security` ; QE-SOC-04)
- Tables / migrations : `user` (condensat du mot de passe) ; `audit_event`. La révocation des sessions n'est pas incluse (NON DÉFINI, QE-SOC-17).
- Droits : utilisateur authentifié, sur son propre compte uniquement. Ancien mot de passe requis : NON DÉFINI (recommandation oui). Refus sans session : 401 (recommandation, QE-SOC-05).
- Dépendances : BE-005, BE-007
- Critères d'acceptation :
  - CA-1 : avec le bon ancien mot de passe, le nouveau mot de passe est accepté et relu comme valide (test).
  - CA-2 (refus) : un mauvais ancien mot de passe est refusé sans modification (test).
  - CA-3 (isolation) : un utilisateur ne peut changer le mot de passe d'un autre utilisateur (test, 404 recommandé).
  - CA-4 : l'entrée d'audit ne contient ni l'ancien ni le nouveau mot de passe (test).
- Documentation attendue : docstring de la route ; doc de module `app/auth/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Profil et sécurité du compte »).

### BE-019 — Récupération et réinitialisation du mot de passe
- Domaine : identité
- Vague : 4
- Routes :
  - NON DÉFINI : `POST /api/v1/auth/password-reset/request` (QE-SOC-04)
  - NON DÉFINI : `POST /api/v1/auth/password-reset/confirm` (QE-SOC-04)
  - Pages front associées : `/forgot-password`, `/reset-password` (contrat : réponse générique)
- Tables / migrations : `password_reset_token` (migration `e3c4a8f1b2d6_password_reset_tokens.py`, sans classe ORM observée, voir BE-037). Durée de validité NON DÉFINI (QE-SOC-09).
- Droits : aucune permission. Réponse générique identique que le compte existe ou non. Jeton consommé, expiré ou d'un autre utilisateur : refus, code NON DÉFINI (recommandation 404).
- Dépendances : BE-003, BE-005, BE-007
- Critères d'acceptation :
  - CA-1 : la demande de réinitialisation renvoie la même réponse pour un compte existant et un compte inexistant (test d'énumération).
  - CA-2 (refus) : un jeton consommé est refusé (test).
  - CA-3 (refus) : un jeton d'un autre utilisateur est refusé (test).
  - CA-4 : la réponse ne confirme jamais la livraison d'un courriel ; l'envoi est testé avec un SMTP factice (QE-SOC-18).
  - CA-5 : la réinitialisation réussie crée une entrée d'audit sans mot de passe (test).
- Documentation attendue : docstrings des routes ; doc de module `app/auth/` (récupération).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Authentification P0 ») ; `#Journal chronologique des mises à jour` (entrée 2026-11-03, récupération de compte).

### BE-020 — Profil de compte en lecture seule
- Domaine : identité / compte
- Vague : 4
- Routes :
  - NON DÉFINI : `GET /api/v1/account/profile` (page source `/account/profile` ; QE-SOC-04)
- Tables / migrations : `user`.
- Droits : utilisateur authentifié, son propre profil. Aucune route d'édition (PUT et PATCH renvoient 405). Refus sans session : 401 (recommandation, QE-SOC-05).
- Dépendances : BE-003, BE-005
- Critères d'acceptation :
  - CA-1 : le profil renvoyé est celui de la session (test).
  - CA-2 (refus) : sans session, la route est refusée (test).
  - CA-3 (isolation) : le profil d'un autre utilisateur n'est jamais retourné (test).
  - CA-4 : PUT et PATCH sur la route renvoient 405 (test).
- Documentation attendue : docstring de la route ; doc de module `app/identity/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Profil et sécurité du compte », lecture seule).

### BE-021 — Registre des modules et états de module (modèle)
- Domaine : modules
- Vague : 3
- Routes : aucune
- Tables / migrations : `module`, `organization_module` (`app/modules_registry/models.py`) ; migration `1ede243704c7_modules_registry_tables.py`. Colonnes clés : identifiant de module, version du manifeste, état d'activation par organisation (NON DÉFINI, QE-SOC-19). Le manifeste est versionné (contrat décrit dans les sources, format NON DÉFINI).
- Droits : aucun endpoint. Les états `absent`, `inconnu` et `incompatible` sont explicites ; aucun droit n'est déduit.
- Dépendances : BE-002
- Critères d'acceptation :
  - CA-1 : un module non présent renvoie l'état `absent` (test).
  - CA-2 : un module non reconnu renvoie l'état `inconnu` (test).
  - CA-3 : un manifeste de version incompatible renvoie l'état `incompatible` (test).
  - CA-4 (refus) : aucun de ces trois états n'ouvre l'accès au module (test).
- Documentation attendue : docstrings ; doc de module `app/modules_registry/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-3) ; `#2. Faits établis et décisions` (ligne « Catalogue / activation »).

### BE-022 — Catalogue et activation des modules par organisation
- Domaine : modules
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/modules` (catalogue ; QE-SOC-04)
  - NON DÉFINI : `PUT /api/v1/organizations/current/modules/{moduleId}/activation` (QE-SOC-04)
- Tables / migrations : `organization_module`, `module` ; `audit_event`.
- Droits : lecture pour membre ; activation et désactivation exigent une permission, code NON DÉFINI (recommandation `organization.modules.activate`, QE-SOC-06). Refus : 403. Module inconnu : refusé, code NON DÉFINI (recommandation 404). Autre organisation : 404.
- Dépendances : BE-007, BE-008, BE-009, BE-021
- Critères d'acceptation :
  - CA-1 : activer puis désactiver un module persiste l'état (test).
  - CA-2 (refus) : un membre sans permission reçoit 403 et l'état ne change pas (test).
  - CA-3 (isolation) : activer un module dans O1 n'a aucun effet sur O2 (test).
  - CA-4 : module inconnu ou `incompatible` : activation refusée (test).
  - CA-5 : chaque activation ou désactivation crée une entrée d'audit (test).
- Documentation attendue : docstrings ; doc de module `app/modules_registry/` (activation).
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Résultats vérifiés` (activation existante à vérifier côté serveur) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-3).

### BE-023 — Plans, versions et abonnement (modèle et migrations)
- Domaine : facturation
- Vague : 3
- Routes : aucune
- Tables / migrations : `plan`, `plan_version`, `subscription` (`app/billing/models.py`) ; migrations `da0ccc1f6d2c_billing_tables.py` et `c0b7d9a2e511_billing_versions_and_payments.py`. Montants en `amountMinor` (backfill depuis `amountCents`, corrigé et contre-revu). Payeur, bénéficiaire et niveau d'achat : NON DÉFINI (QE-SOC-01).
- Droits : aucun endpoint. Un abonnement appartient à une seule organisation.
- Dépendances : BE-002
- Critères d'acceptation :
  - CA-1 : la migration `c0b7d9a2e511` remplit `amountMinor` depuis `amountCents` sans perte (test sur base jetable).
  - CA-2 : upgrade puis downgrade jusqu'à `d8e9f0a1b2c3` réussissent (test) ; une seule tête Alembic (test).
  - CA-3 (isolation) : un abonnement de O1 n'est jamais lisible depuis O2 (test de repository).
  - CA-4 (refus) : un abonnement sans organisation est refusé à l'écriture (test).
- Documentation attendue : docstrings des modèles ; doc de module `app/billing/models.py`.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Facturation / abonnement` ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Billing API et migration socle »).

### BE-024 — Entitlements d'abonnement (modèle et calcul)
- Domaine : facturation
- Vague : 4
- Routes : aucune (lecture en BE-026)
- Tables / migrations : table unique `subscription_entitlement` (décision D3 ; renomme `subscription_entitlement`, modèle `app/billing/models.py::SubscriptionEntitlement`). Tâche absorbant BE-261 : la table `entitlement` de BE-261 n'est pas créée. `plan_version` (BE-023).
  - Colonnes existantes (develop) : `organizationId`, `subscriptionId`, `moduleCode`, `entitlementCode`, `status` (défaut `active`), `startsAt`, `endsAt` ; contrainte unique (`subscriptionId`, `entitlementCode`).
  - Colonnes à ajouter (contenu absorbé de BE-261) : `offreId` (version de plan source, `plan_version`), `capaciteId` (clé étrangère vers le registre de capacités : recommandation appliquée, registre rattaché au registre de modules de BE-021 | QE-SOC-23), `quotaLimite` (entier positif ; unité portée par le registre de capacités | QE-SOC-23), `niveauApplication` (`organisation` | `utilisateur`), `sourceAttribution` (`offre` | `achat_additionnel` | `essai` | `allocation_admin` | `usage_reel`). `organizationId` est nul pour une offre globale : recommandation appliquée, nul seulement si `sourceAttribution` = `offre` (QE-SOC-23).
  - `effet_acces` (BE-261, NON DÉFINI) : recommandation appliquée, porté par `status` (`active` | `inactive` | `expired` | `blocked`, mêmes états que BE-025) ; pas de colonne séparée. | QE-SOC-23
  - Dates de début et de fin : `startsAt` / `endsAt` existants ; état et calcul : voir QE-SOC-19.
- Droits : aucun endpoint. Écriture par les services sous la permission `entitlement.manage` (NON DÉFINI, recommandation de code | QE-SOC-06) ; refus 403. Lecture par les services limitée à l'organisation. Source de vérité : l'état serveur. Un webhook ou un retour UI ne crée jamais un entitlement (règle de la recommandation de paiement).
- Dépendances : BE-021, BE-023
- Critères d'acceptation :
  - CA-1 : l'entitlement calculé provient de la version de plan active (test).
  - CA-2 : un entitlement expiré renvoie l'état `expired` (test).
  - CA-3 (refus) : un événement de webhook seul ne crée aucun entitlement (test).
  - CA-4 (isolation) : l'entitlement de O1 n'est jamais calculé pour O2 (test).
  - CA-5 (ex-BE-261, CA-1) : la migration ajoute les colonnes absorbées ci-dessus et renomme la table ; test binaire de présence des colonnes.
  - CA-6 (ex-BE-261, CA-2) : `niveauApplication` et `sourceAttribution` n'acceptent que les valeurs listées ; une autre valeur est refusée (test).
  - CA-7 (ex-BE-261, CA-3) : chaque combinaison `sourceAttribution` × `niveauApplication` (5 × 2) est enregistrable (test de couverture).
  - CA-8 (ex-BE-261, CA-4) : un entitlement pointant vers une `capaciteId` inexistante est refusé (test).
  - CA-9 (refus, ex-BE-261, CA-5) : une écriture sans `entitlement.manage` renvoie 403 et ne modifie rien (test).
  - CA-10 (isolation, ex-BE-261, CA-6) : un entitlement de l'organisation A n'apparaît pas dans la lecture de l'organisation B (test).
- Documentation attendue : docstrings de chaque fonction publique du module d'entitlements ; doc de module `app/billing/` (entitlements).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Recommandation de paiement` (critère de réversibilité) ; `#2. Faits établis et décisions` (ligne « Abonnement / droits ») ; contenu absorbé de BE-261 : `00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md#Méthode et représentation` (chaîne offre → capacité → quota → niveau → entitlements → effet d'accès) et `#Critères d'acceptation` (matrice offres/droits/quotas/entitlements).

### BE-025 — Garde d'accès module fail-closed (projection canOpen / canActivate)
- Domaine : modules / facturation
- Vague : 7
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/modules/{moduleId}/access` (projection ; QE-SOC-04)
- Tables / migrations : `organization_module`, `subscription_entitlement`.
- Droits : `canOpen` et `canActivate` calculés côté serveur. États `inactive`, `expired` et `blocked` : refus 403. Accès legacy sans entitlement : préservé (non-régression). Dépendance externe : les modules métier Liquid, Tanker et Smart, hors de ce domaine, consomment cette projection (EXT non résolu, QE-SOC-20).
- Dépendances : BE-009, BE-022, BE-024 ; EXT non résolu : consommateurs métier (Liquid, Tanker, Smart) de la projection, sans identifiant BE-nnn unique (QE-SOC-20)
- Critères d'acceptation :
  - CA-1 (non-régression) : sans entitlement, l'accès legacy reste autorisé (test).
  - CA-2 (refus) : `inactive` refuse `canOpen` et `canActivate` en 403 (test).
  - CA-3 (refus) : `expired` refuse `canOpen` et `canActivate` en 403 (test).
  - CA-4 (refus) : `blocked` refuse `canOpen` et `canActivate` en 403 (test).
  - CA-5 (isolation) : un entitlement de O1 n'ouvre aucun module pour O2 (test).
  - CA-6 : la suite du module (14 tests) passe sur base isolée (test).
- Documentation attendue : docstrings ; doc de module `app/modules_registry/` (garde d'accès).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Entitlement et garde d'accès module ») ; `#Priorisation stricte pour permettre l'usage initial` (P0-3, P0-5).

### BE-026 — Abonnement et droits de l'organisation courante (lecture)
- Domaine : facturation
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/subscription` (QE-SOC-04)
  - NON DÉFINI : `GET /api/v1/organizations/current/entitlements` (QE-SOC-04)
- Tables / migrations : `subscription` (table de BE-023, lecture seule, non redéfinie), `subscription_entitlement`, `plan`, `plan_version`.
- Droits : permission de lecture de la facturation, code NON DÉFINI (QE-SOC-06). Refus : 403. Abonnement d'une autre organisation : 404.
- Dépendances : BE-009, BE-024
- Critères d'acceptation :
  - CA-1 : une organisation sans abonnement reçoit un état vide, sans plan ni facture inventés (test).
  - CA-2 (refus) : un membre sans permission reçoit 403 (test).
  - CA-3 (isolation) : l'abonnement de O2 n'est jamais retourné à O1 (test).
  - CA-4 : la réponse ne contient aucun identifiant ou secret du fournisseur de paiement (test).
- Documentation attendue : docstrings des routes ; doc de module `app/billing/`.
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Résultats vérifiés` (route `/api/v1/billing` en état sandbox non configuré) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-5).

### BE-027 — Factures et tentatives de paiement (lecture)
- Domaine : facturation
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/invoices` (QE-SOC-04)
  - NON DÉFINI : `GET /api/v1/organizations/current/invoices/{invoiceId}` (QE-SOC-04)
- Tables / migrations : `invoice`, `payment_attempt` (`app/billing/models.py`).
- Droits : permission de lecture de la facturation, code NON DÉFINI (QE-SOC-06). Refus : 403. Facture d'une autre organisation : 404.
- Dépendances : BE-009, BE-023
- Critères d'acceptation :
  - CA-1 : la liste ne contient que les factures de l'organisation active (test).
  - CA-2 (refus) : un membre sans permission reçoit 403 (test).
  - CA-3 (isolation) : O1 demandant une facture de O2 reçoit 404 (test).
  - CA-4 : le statut affiché est celui de la base serveur, jamais celui d'un retour d'interface (test).
- Documentation attendue : docstrings ; doc de module `app/billing/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-5) ; `#Tableau de suivi persistant P0` (ligne « UI settings/catalogue/billing read »).

### BE-028 — Adaptateur de paiement neutre (stub, sandbox, aucun débit)
- Domaine : facturation
- Vague : 7
- Routes : aucune (aucun checkout ; le statut provider reste lu en BE-027)
- Tables / migrations : `payment_attempt` (intention et tentative, identifiants internes distincts du SDK).
- Droits : aucun checkout live. Configuration provider absente : état « sandbox non configuré » (recommandation : mode par défaut). Fournisseur définitif : NON DÉFINI (QE-SOC-12).
- Dépendances : BE-027
- Critères d'acceptation :
  - CA-1 : aucun appel réseau vers un fournisseur pendant les tests (test avec adaptateur factice).
  - CA-2 (refus) : passer en mode live sans configuration validée est refusé (test).
  - CA-3 : les identifiants internes de tentative ne dépendent pas du SDK du fournisseur (test de contrat sur l'adaptateur).
  - CA-4 : aucun débit réel n'est créé (test sur la base : zéro `payment_attempt` au statut réussi).
- Documentation attendue : docstrings de l'interface et de l'adaptateur ; doc de module `app/billing/` (adaptateur).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Recommandation de paiement` ; `#Tableau de suivi persistant P0` (ligne « Checkout sandbox/config prix »).

### BE-029 — Évènements webhook de paiement (idempotence)
- Domaine : facturation
- Vague : 8
- Routes :
  - aucune (la route d'entrée est portée par BE-083)
- Périmètre : BE-029 possède la table d'idempotence des évènements de paiement et l'effet métier (déduplication, quarantaine). BE-083 (route d'entrée et vérification de signature) dépend de BE-029.
- Tables / migrations : table d'idempotence `payment_webhook_event` (propriétaire BE-029) ; `payment_attempt` (`app/billing/models.py`) mis à jour par BE-029.
- Droits : aucune permission. La signature est vérifiée par BE-083 avant tout appel à BE-029 ; BE-029 ne traite que des évènements vérifiés. Événement dont la référence est inconnue : refus (recommandation 404).
- Dépendances : BE-028
- Critères d'acceptation :
  - CA-1 : le même événement reçu deux fois ne produit qu'un seul effet (test d'idempotence).
  - CA-2 (refus) : un évènement dont la référence est inconnue n'écrit rien (test).
  - CA-3 (refus) : un événement sans effet de paiement reconnu n'accorde aucun entitlement (test).
  - CA-4 (isolation) : un événement référençant une tentative de O2 n'est jamais appliqué sous O1 (test).
  - CA-5 (refus) : un évènement contradictoire avec le même identifiant fournisseur est mis en quarantaine, pas appliqué (test ; critère transféré de BE-083).
- Documentation attendue : docstrings de la route et du service ; doc de module `app/billing/` (webhooks).
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Facturation / abonnement` (`payment_webhook_event`) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Recommandation de paiement`.

### BE-030 — Journal opérateur des lectures sensibles
- Domaine : opérateur / audit
- Vague : 4
- Routes : aucune (écriture par la console, BE-031)
- Tables / migrations : aucune table propre (décision D2 : une seule table d'audit, `audit_event`, propriétaire BE-007). Les lectures sensibles sont écrites dans `audit_event` avec une `action` préfixée `operator.` ; la table develop `operator_audit_log` (`app/operator/audit_models.py`, `app/operator/audit.py`, migration `b7c8d9e0f123_operator_read_audit.py`) est remplacée par `audit_event`. NON DÉFINI : Recommandation appliquée : reprise des lignes dans `audit_event` par BE-007, puis retrait de `operator_audit_log` | QE-SOC-22. Colonnes clés : acteur, portée, action, cible, résultat, request ID.
- Droits : aucun endpoint. Chaque lecture opérateur produit une entrée. Le journal ne contient ni contenu client ni PII.
- Dépendances : BE-001, BE-007
- Critères d'acceptation :
  - CA-1 : chaque lecture opérateur crée exactement une entrée (test).
  - CA-2 : l'entrée contient acteur, portée, action, cible, résultat et request ID (test).
  - CA-3 (refus) : une consultation refusée est journalisée avec le résultat `refus` (test ; recommandation, QE-SOC-15).
  - CA-4 : aucune charge utile de réponse n'est stockée (test).
  - CA-5 : upgrade puis downgrade ciblés réussissent et Alembic a une seule tête (test).
- Documentation attendue : docstrings ; doc de module `app/operator/audit.py`.
- Source : `08-controles/architecture-fondation/REPRISE-TRAVAIL-P0.md#Résultats vérifiés` (journal des lectures opérateur) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Console opérateur / support minimal »).

### BE-031 — Console opérateur en lecture seule
- Domaine : opérateur
- Vague : 7
- Routes :
  - NON DÉFINI : `GET /api/v1/admin/organizations` (liste ; QE-SOC-04, QE-SOC-25)
  - NON DÉFINI : `GET /api/v1/admin/organizations/{orgId}` (détail abonnement et modules ; QE-SOC-04, QE-SOC-25)
  - NON DÉFINI : `GET /api/v1/admin/requests/{request_id}` (recherche par request ID ; QE-SOC-04, QE-SOC-25)
- Tables / migrations : `organization`, `subscription` (table de BE-023, lecture seule), `organization_module`, `payment_webhook_event` (BE-029, lecture seule), `audit_event` (BE-007).
- Droits : liste `OPERATOR_READ_USER_IDS` fail-closed : liste vide, il n'y a aucun accès (source). Utilisateur non listé : 403. Permission de lecture opérateur, code NON DÉFINI (QE-SOC-15). Aucune écriture ni action de réparation (PUT, POST, DELETE renvoient 405).
- Dépendances : BE-001, BE-022, BE-026, BE-030
- Critères d'acceptation :
  - CA-1 (refus) : un utilisateur absent de `OPERATOR_READ_USER_IDS` reçoit 403 sur les trois routes (test).
  - CA-2 (refus) : une liste vide refuse toute lecture (test fail-closed).
  - CA-3 : chaque consultation crée une entrée `audit_event` avec une action `operator.` (test).
  - CA-4 : une recherche par request ID distingue `trouvé`, `non trouvé`, `refus` et `erreur` (test).
  - CA-5 (isolation) : la console n'expose aucun contenu tenant, seulement l'état d'abonnement et de module (test sur la forme de réponse).
  - CA-6 : PUT, POST et DELETE sur ces routes renvoient 405 (test).
- Documentation attendue : docstrings des routes ; doc de module `app/operator/router.py`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-6) ; `#Tableau de suivi persistant P0` (ligne « Console opérateur / support minimal », 13 tests backend rapportés).

### BE-032 — Statut technique du service (health, readiness)
- Domaine : transverse / exploitation
- Vague : 2
- Routes :
  - `GET /api/v1/health` (existe dans develop : renvoie `{"status": "ok"}` sans contrôle de la base ; à conserver, avec contrôle de base ajouté par cette tâche)
  - NON DÉFINI : `GET /api/v1/health/ready` (readiness avec contrôle de base). Recommandation appliquée : route distincte, sans session, GET seul. | QE-SOC-04
- Tables / migrations : aucune. Vérification de connexion base : recommandation.
- Code existant (develop) : `app/api/v1/endpoints/health.py` (`GET /api/v1/health` renvoie `{"status": "ok"}` ; `GET /api/v1/health/error-demo` de démonstration) ; garder : `GET /api/v1/health` ; casser : la route `/api/v1/health/error-demo` (retirée, voir BE-001).
- Droits : accès public minimal, recommandation (QE-SOC-05). La réponse ne contient ni secret, ni URL de base, ni donnée personnelle. Base indisponible : état `not ready`.
- Dépendances : BE-001
- Critères d'acceptation :
  - CA-1 : la réponse ne contient aucun secret, aucune URL de base et aucun courriel (test).
  - CA-2 : base indisponible renvoie l'état `not ready` (test).
  - CA-3 : la route n'exige aucune session (test).
  - CA-4 (refus) : la route refuse les méthodes autres que GET avec 405 (test).
- Documentation attendue : docstrings ; doc de module `app/core/health.py` (chemin prévu, recommandation).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Priorisation stricte pour permettre l'usage initial` (P0-6 : endpoint health et readiness) ; `#Tableau de suivi persistant P0` (note « maintenance illustrative, pas de signal de santé backend »).

### BE-033 — Journal d'audit consultable par l'administrateur d'organisation
- Domaine : audit
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/organizations/current/audit-logs` (QE-SOC-04)
- Tables / migrations : `audit_event`.
- Droits : permission de lecture du journal, code NON DÉFINI (QE-SOC-06). Refus : 403. Lecture seule, aucune édition. Rétention et exhaustivité : NON DÉFINI (QE-SOC-14).
- Dépendances : BE-007, BE-009
- Critères d'acceptation :
  - CA-1 (refus) : un membre sans permission reçoit 403 (test).
  - CA-2 (isolation) : la liste de O1 ne contient aucune entrée de O2 (test).
  - CA-3 : PUT, PATCH et DELETE renvoient 405 (test, lecture seule).
  - CA-4 : les entrées retournées ne contiennent ni mot de passe ni jeton (test).
- Documentation attendue : docstring de la route ; doc de module `app/audit/` (lecture).
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Audit UI organisationnel », périmètre à confirmer) ; `#Priorisation stricte pour permettre l'usage initial` (P1).

### BE-034 — Abonnement push et désabonnement côté serveur
- Domaine : notifications
- Vague : 4
- Routes :
  - NON DÉFINI : `POST /api/v1/notifications/push-subscriptions` (QE-SOC-04)
  - NON DÉFINI : `DELETE /api/v1/notifications/push-subscriptions/{subscriptionId}` (QE-SOC-04)
- Tables / migrations : `notification_push_subscription` (`app/notifications/models.py`) ; migration `f3a4b5c6d7e8_notification_push_subscription.py`.
- Droits : utilisateur authentifié, pour ses propres abonnements. Session absente : 401 (recommandation, QE-SOC-05). Abonnement d'un autre utilisateur : 404.
- Dépendances : BE-003, BE-005
- Critères d'acceptation :
  - CA-1 : le désabonnement côté serveur supprime l'abonnement, puis le navigateur est désabonné (test, 20 tests rapportés).
  - CA-2 (refus) : sans session, la route est refusée (test).
  - CA-3 (isolation) : l'utilisateur A ne peut supprimer l'abonnement de B (test, 404).
- Documentation attendue : docstrings ; doc de module `app/notifications/`.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Notifications et aide P1 ») ; `#Journal chronologique des mises à jour` (entrée 2026-11-03, désinscription push).

### BE-035 — Boîte de réception des notifications
- Domaine : notifications
- Vague : 6
- Routes :
  - NON DÉFINI : `GET /api/v1/notifications/inbox` (QE-SOC-04)
  - NON DÉFINI : `PATCH /api/v1/notifications/inbox/{itemId}` (marquer lu ; QE-SOC-04)
- Tables / migrations : `notification_inbox_item` (migration `d8e9f0a1b2c3_notification_inbox.py`, sans modèle ORM observé, voir BE-037). Colonnes clés : destinataire, état lu, date ; index de lecture présent.
- Droits : destinataire uniquement. Aucun producteur métier activé : la liste vide est l'état attendu (QE-SOC-03). Refus sans session : 401 (recommandation). Élément d'un autre destinataire : 404.
- Dépendances : BE-003, BE-009
- Critères d'acceptation :
  - CA-1 : une liste vide renvoie l'état vide, sans élément inventé (test).
  - CA-2 (isolation) : le destinataire A ne lit ni ne modifie l'élément de B (test, 404).
  - CA-3 : marquer lu persiste après rechargement (test).
  - CA-4 : aucun élément n'est créé par le système sans producteur approuvé (test).
- Documentation attendue : docstrings ; doc de module `app/notifications/` (boîte de réception).
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Notifications` ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#Tableau de suivi persistant P0` (ligne « Notifications et aide P1 », producteurs en attente).

### BE-036 — Cycle de vie de l'organisation : états et transitions (bloqué par décision)
- Domaine : organisation
- Vague : 6
- Routes :
  - NON DÉFINI : `POST /api/v1/organizations/current/suspension` (QE-SOC-10)
  - NON DÉFINI : `POST /api/v1/organizations/current/reactivation` (QE-SOC-10)
  - NON DÉFINI : `POST /api/v1/organizations/current/closure` (QE-SOC-10)
- Tables / migrations : `organization` (statut) ; `audit_event`.
- Droits : permission d'administration, code NON DÉFINI (QE-SOC-06). Refus : 403. Effets d'une suspension sur l'accès et la facturation : NON DÉFINI, décision requise (QE-SOC-11). Recommandation de travail : états `actif`, `suspendu`, `clôturé` ; aucun effet automatique sur la facturation.
- Dépendances : BE-002, BE-007, BE-009
- Critères d'acceptation :
  - CA-1 : seules les transitions de la table d'états (recommandation) sont acceptées ; les autres sont refusées (test).
  - CA-2 (refus) : un membre sans permission reçoit 403 (test).
  - CA-3 : chaque transition crée une entrée d'audit (test).
  - CA-4 (isolation) : la transition de O1 n'affecte pas O2 (test).
- Documentation attendue : docstrings ; doc de module `app/identity/` (cycle de vie).
- Source : `00-pilotage/architecture-fondation/phases/PH-07-modele-saas-organisations.md#Démarche` (étape 4, cycle de vie à valider) ; `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#2. Faits établis et décisions` (ligne « Abonnement / droits » ; décision Q-05 ouverte).

### BE-037 — Réconciliation ORM et migrations (password_reset_token, notification_inbox_item)
- Domaine : transverse / modèles
- Vague : 7
- Routes : aucune
- Tables / migrations : `password_reset_token` (migration `e3c4a8f1b2d6`), `notification_inbox_item` (migration `d8e9f0a1b2c3`).
- Droits : aucun.
- Dépendances : BE-019, BE-035
- Critères d'acceptation :
  - CA-1 : chaque table ci-dessus a une classe ORM dans les métadonnées SQLAlchemy (test).
  - CA-2 : la comparaison ORM et base (autogénération Alembic) ne produit aucune différence (test).
  - CA-3 : si une table reste hors ORM, une exception documentée existe dans le registre de tests (recommandation, QE-SOC-02 et QE-SOC-03).
- Documentation attendue : docstrings des modèles ; doc de module `app/identity/models.py` et `app/notifications/models.py`.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Suite recommandée` (point 1) ; `#Identité / appartenance` et `#Notifications`.

### BE-038 — Suite adversariale d'isolation tenant et de permissions HTTP
- Domaine : transverse / sécurité
- Vague : 9
- Routes : aucune (tests portant sur toutes les routes d'organisation des tâches BE-010 à BE-036)
- Tables / migrations : toutes les tables tenant (liste produite en BE-039).
- Droits : tests de refus 403, de ressource d'autre organisation 404, d'appels directs sans interface, d'objets devinés, de changement de contexte, de session expirée et de privilège supérieur.
- Dépendances : BE-011, BE-015, BE-017, BE-022, BE-026, BE-027, BE-031, BE-033, BE-035
- Critères d'acceptation :
  - CA-1 : 100 % des routes d'organisation listées dans les tâches ont au moins un test de refus de permission (test de couverture).
  - CA-2 : 100 % des routes d'organisation ont au moins un test d'isolation entre deux organisations (test de couverture).
  - CA-3 : un appel direct sans l'interface, avec un identifiant deviné, renvoie la même réponse qu'une ressource inexistante (test).
  - CA-4 : une session expirée pendant une requête est refusée sans fuite de donnée (test).
  - CA-5 : un utilisateur de niveau inférieur ne peut pas réussir une action réservée à un niveau supérieur (test).
- Documentation attendue : doc de module `tests/` (chemin prévu : `tests/isolation/README` non créé ; la documentation est dans la docstring du module de tests) ; docstrings des cas de test.
- Source : `08-controles/architecture-fondation/plan-prochaine-tranche-socle-zylo-office.md#8. Vérifications et revues de la tranche locale` (point 2, tests adversariaux) ; `#5. Tranches de code : livrables et critères` (tranche E).

### BE-039 — Inventaire global tables, propriétaires, portées et tests
- Domaine : transverse
- Vague : 10
- Routes : aucune
- Tables / migrations : toutes les tables du socle (liste de référence : INVENTAIRE-TABLES-SOCLE-ISS-084).
- Droits : aucun.
- Dépendances : BE-037, BE-038
- Critères d'acceptation :
  - CA-1 : chaque table du socle figure avec un propriétaire, une portée (tenant, organisation ou global), les endpoints et les tests associés (test de génération).
  - CA-2 : aucune table tenant n'a une portée « non définie » (test).
  - CA-3 : le document d'inventaire est produit et vérifié contre le métadonnée SQLAlchemy (test).
- Documentation attendue : document d'inventaire `docs/architecture/inventaire-tables-socle.md` (chemin prévu), docstrings des générateurs éventuels.
- Source : `08-controles/architecture-fondation/INVENTAIRE-TABLES-SOCLE-ISS-084.md#Suite recommandée` (points 2 et 4).

---

## Points ouverts

- Question : la cardinalité entre compte client, payeur et Organization (une ou plusieurs organisations par compte) est-elle tranchée ?
  - NON DÉFINI : Recommandation appliquée : chaque abonnement référence exactement une organisation et chaque organisation a un seul payeur déclaré, vérifié par un test de contrainte. | QE-SOC-01
- Question : la table `password_reset_token` a-t-elle une classe ORM ou doit-elle rester hors ORM ?
  - NON DÉFINI : Recommandation appliquée : créer la classe ORM dans `app/auth/` et vérifier qu'elle figure dans les métadonnées SQLAlchemy (BE-037, CA-1). | QE-SOC-02
- Question : la table `notification_inbox_item` a-t-elle un modèle ORM et des usages applicatifs ?
  - NON DÉFINI : Recommandation appliquée : créer le modèle ORM dans `app/notifications/models.py` avant tout producteur, avec un test de métadonnées (BE-035, BE-037). | QE-SOC-03
- Question : quels sont les chemins exacts des routes back-end d'organisation, membres, catalogue, facturation, santé et opérateur ?
  - NON DÉFINI : Recommandation appliquée : utiliser les chemins proposés dans chaque tâche, les figer dans la spécification OpenAPI avant implémentation, et tenir la liste à jour dans BE-039. | QE-SOC-04
- Question : quels codes HTTP renvoyer pour session absente, identifiants invalides et ressource hors organisation ?
  - NON DÉFINI : Recommandation appliquée : 401 pour session absente ou identifiants invalides (même réponse), 404 pour ressource hors organisation, 403 pour permission absente, sans distinguer l'existence d'une ressource. | QE-SOC-05
- Question : quels sont les codes de permission (nom et granularité) exigés par chaque route ?
  - NON DÉFINI : Recommandation appliquée : format `ressource.action` (par exemple `organization.settings.update`) et une liste unique de codes produite avant BE-008. | QE-SOC-06
- Question : quelle règle s'applique quand un grant `allow` et un grant `deny` coexistent ?
  - NON DÉFINI : Recommandation appliquée : le `deny` l'emporte sur le `allow` (test CA-3 de BE-008). | QE-SOC-07
- Question : quels sont le seuil et la fenêtre de limitation des tentatives de connexion ?
  - NON DÉFINI : Recommandation appliquée : 5 tentatives échouées par compte et par 15 minutes, puis blocage de la connexion pour ce compte pendant 15 minutes. | QE-SOC-08
- Question : quelle est la durée de validité des invitations et des jetons de réinitialisation ?
  - NON DÉFINI : Recommandation appliquée : invitation valable 7 jours, jeton de réinitialisation valable 60 minutes, usage unique pour les deux. | QE-SOC-09
- Question : quels sont les états et transitions du cycle de vie de l'organisation ?
  - NON DÉFINI : Recommandation appliquée : états `actif`, `suspendu`, `clôturé`, avec transitions `actif` vers `suspendu`, `suspendu` vers `actif`, `actif` ou `suspendu` vers `clôturé`, et refus de toute autre transition (BE-036, CA-1). | QE-SOC-10
- Question : quels effets une suspension doit-elle produire sur l'accès et sur la facturation ?
  - NON DÉFINI : Recommandation appliquée : une suspension bloque l'ouverture des modules (`blocked`) sans modifier l'abonnement ni créer de facture ; aucun automatisme de facturation (BE-025, BE-036). | QE-SOC-11
- Question : quel fournisseur de paiement et quelle éligibilité du compte marchand sont retenus ?
  - NON DÉFINI : Recommandation appliquée : adaptateur neutre en mode stub ou sandbox uniquement, sans clé live, sans checkout actif (BE-028, CA-2). | QE-SOC-12
- Question : quelle route et quelle vérification de signature sont utilisées pour les webhooks de paiement ?
  - NON DÉFINI : Recommandation appliquée : route `POST /api/v1/billing/provider-events` portée par BE-083, avec vérification de signature du fournisseur et rejet de toute signature invalide (BE-083, CA-1) ; BE-029 possède la table d'idempotence et n'a pas de route propre. | QE-SOC-13
- Question : quelles actions doivent être journalisées et pendant combien de temps conserver le journal d'audit ?
  - NON DÉFINI : Recommandation appliquée : toute mutation sensible est journalisée (liste de BE-007, CA-1) ; la rétention reste bloquante et n'est pas implémentée tant que PH-13 ne la tranche pas. | QE-SOC-14
- Question : comment la liste `OPERATOR_READ_USER_IDS` s'articule-t-elle avec les permissions RBAC ?
  - NON DÉFINI : Recommandation appliquée : conserver la liste fail-closed comme seul contrôle d'accès opérateur, sans permission RBAC côté client, et journaliser les refus (BE-030, CA-3 ; BE-031, CA-1 et CA-2). | QE-SOC-15
- Question : quelles règles exactes protègent le rôle propriétaire ?
  - NON DÉFINI : Recommandation appliquée : le rôle propriétaire ne peut être ni attribué, ni retiré, ni modifié par un utilisateur qui n'est pas propriétaire (BE-014, CA-5 ; BE-015, CA-3). | QE-SOC-16
- Question : la révocation des sessions et la gestion MFA sont-elles dans le périmètre du changement de mot de passe ?
  - NON DÉFINI : Recommandation appliquée : hors périmètre de BE-018 ; le changement de mot de passe ne révoque pas les sessions existantes et l'exclusion est documentée. | QE-SOC-17
- Question : l'envoi réel de courriels de récupération et d'invitation est-il vérifié ?
  - NON DÉFINI : Recommandation appliquée : tests avec SMTP factice seulement ; aucune réponse de l'API ne confirme la livraison (BE-019, CA-4). | QE-SOC-18
- Question : l'activation d'un module doit-elle dépendre de l'entitlement de l'abonnement ?
  - NON DÉFINI : Recommandation appliquée : l'activation est enregistrée par BE-022 sans condition commerciale ; l'ouverture du module est conditionnée par la garde BE-025, en attendant la décision Q-04 et Q-05. | QE-SOC-19
- Question : quel modèle ou quelle tâche BE-nnn représente les consommateurs métier (Liquid, Tanker, Smart) de la projection `canOpen` / `canActivate` de BE-025 ?
  - NON DÉFINI : Recommandation appliquée : BE-025 reste sans identifiant consommateur unique ; la projection est figée côté socle, et chaque module métier déclarera sa dépendance à BE-025 quand il sera planifié. | QE-SOC-20
- Question : quel code HTTP et quel code d'erreur renvoyer quand l'inscription publique est fermée (`POST /api/v1/auth/register`) ?
  - NON DÉFINI : Recommandation appliquée : 404 et code `registration_disabled`, comportement de develop (`app/auth/router.py`), pour ne pas révéler la route ; la recommandation 403 de la version précédente est écartée. | QE-SOC-21
- Question : les tables `audit_event` et `subscription_entitlement` suivent-elles la convention de casse du CLAUDE.md du backend (tables camelCase) ?
  - NON DÉFINI : Recommandation appliquée : snake_case pour toutes les tables (décision du coordinateur, point A) : les tables camelCase de ce fichier sont renommées en snake_case (`refresh_token`, `login_attempt`, `organization_user`, `user_role`, `role_permission`, `user_permission_grant`, `organization_module`, `user_invitation`, `plan_version`, `subscription_entitlement`, `payment_attempt`, `payment_webhook_event`, `notification_push_subscription`, `password_reset_token`, `notification_inbox_item`, `audit_event`) ; `audit_log` et `operator_audit_log` sont les anciens noms, remplacés par `audit_event` (décision D2) ; les colonnes restent en camelCase (code develop) ; la convention écrite dans le CLAUDE.md du backend (tables camelCase) n'est pas modifiée ici et reste à réaligner | QE-SOC-24
- Question : quelles colonnes la table `audit_event` doit-elle porter pour le request ID, le résultat et la reprise des tables d'audit opérateur ?
  - NON DÉFINI : Recommandation appliquée : ajouter `request_id` (obligatoire) et `result` (`success` | `refused` | `error`) dans la migration de renommage de BE-007 ; reprendre les lectures de `operator_audit_log` dans `audit_event` avec une `action` préfixée `operator.`, puis retirer `operator_audit_log` (BE-030). | QE-SOC-22
- Question : quels sont les valeurs et les rattachements exacts des entitlements (registre de capacités, unité du quota, nullité de l'organisation, effet d'accès) ?
  - NON DÉFINI : Recommandation appliquée : `capaciteId` pointe vers un registre de capacités rattaché au registre de modules (BE-021) ; `quotaLimite` est un entier positif dont l'unité vient du registre ; `organizationId` est nul seulement pour une offre globale (`sourceAttribution` = `offre`) ; `effet_acces` est porté par `status` (`active` | `inactive` | `expired` | `blocked`). | QE-SOC-23
- Question : sous quel préfixe les routes de la console opérateur sont-elles montées ?
  - NON DÉFINI : Recommandation appliquée : toutes les routes de la console opérateur sont montées sous `/api/v1/admin/...` (BE-031) ; ce fichier ne définit aucune route `/api/v1/internal/...`. | QE-SOC-25
