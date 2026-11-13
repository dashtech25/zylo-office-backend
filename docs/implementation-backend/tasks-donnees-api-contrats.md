# Tâches back-end — Données, API et contrats (socle Zylo Office)

- **Domaine :** back-end du socle Zylo Office, données, API, événements, droits, audit, facturation, notifications. Le front-end, le design et les écrans ne sont pas traités ; ils n'apparaissent que pour leurs contrats (routes, payloads, codes d'erreur).
- **Statut :** provisoire. Sources issues de la phase PH-14 au statut DRAFT / BLOCKED ; les valeurs absentes sont marquées NON DÉFINI et leur recommandation est appliquée (voir « Points ouverts »).
- **Sources lues** (chemins relatifs à `definition-travail/`) :
  - `00-pilotage/architecture-fondation/phases/PH-14-donnees-api-backend-frontend-extension.md`
  - `00-pilotage/architecture-fondation/architecture-donnees-api-backend-frontend.md`
  - `00-pilotage/architecture-fondation/contrats-api-et-evenements.md`
  - `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md`
  - Lecture de résolution de références croisées : `03-plateforme/architecture-donnees-api/01-modele-logique.md`
- **Plage d'identifiants :** BE-180 à BE-215 (36 tâches, sans trou, dans l'ordre de dépendance). Plage non épuisée.
- **Conventions transverses appliquées :** chemins de routes préfixés par `/api/v1` (QE-API-01), administration plateforme sous `/api/v1/admin` (QE-API-30) ; identifiants UUID (QE-API-04) ; scope tenant serveur sur toute donnée d'organisation ; hors scope renvoie 404 (QE-API-03).

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-180 | Enveloppe d'erreur et codes HTTP stables | 0 | BE-001, BE-002, BE-005, BE-009 |
| BE-181 | Contexte de requête : correlationId et operationId (request_id fourni par BE-001) | 0 | BE-001, BE-180 |
| BE-182 | Scope tenant et identifiants opaques | 0 | BE-181 |
| BE-183 | Idempotence des mutations et contrôle de version | 0 | BE-180, BE-181, BE-182 |
| BE-184 | Journal d'audit append-only | 1 | BE-007, BE-181, BE-182 |
| BE-185 | Tenant : cycle de vie | 3 | BE-182 |
| BE-186 | Organisation et Workspace (candidat) | 1 | BE-185 |
| BE-187 | Identité utilisateur | 0 | BE-182 |
| BE-188 | Session et authentification | 1 | BE-005, BE-180, BE-187 |
| BE-189 | Membership et sélection de contexte | 6 | BE-183, BE-186, BE-188 |
| BE-190 | RBAC : rôles, permissions, grants et autorisation serveur | 2 | BE-184, BE-189 |
| BE-191 | Pagination par curseur et quotas | 0 | BE-180 |
| BE-192 | Outbox producteur et enveloppe d'événement | 0 | BE-182, BE-183 |
| BE-193 | Inbox consommateur et dispatcher | 0 | BE-192 |
| BE-194 | Catalogue Module et ModuleVersion | 3 | BE-182, BE-190 |
| BE-195 | Manifeste de module et registre | 1 | BE-194 |
| BE-196 | Cycle de vie OrganizationModule | 6 | BE-183, BE-189, BE-190, BE-192, BE-195 |
| BE-197 | Hooks de module | 0 | BE-180, BE-196 |
| BE-198 | Migration de module : expand, migrate, verify, contract, dry-run | 4 | BE-183, BE-196 |
| BE-199 | Navigation et configuration de module | 3 | BE-190, BE-196 |
| BE-200 | Plan et PlanVersion | 3 | BE-194 |
| BE-201 | Entitlements et décision d'accès | 4 | BE-024, BE-190, BE-196, BE-200 |
| BE-202 | Devis, checkout et consentement | 3 | BE-183, BE-189, BE-190, BE-200 |
| BE-203 | Cycle de vie Subscription et commandes | 6 | BE-023, BE-192, BE-201, BE-202 |
| BE-204 | Facture (Invoice) | 4 | BE-183, BE-203 |
| BE-205 | Avoir (CreditNote) | 2 | BE-204 |
| BE-206 | Tentative et paiement (PaymentAttempt, Payment) | 3 | BE-183, BE-204 |
| BE-207 | Reçu (Receipt) | 2 | BE-206 |
| BE-208 | Remboursement et litige (Refund, Dispute) | 3 | BE-206 |
| BE-209 | Webhook PSP entrant | 1 | BE-193, BE-206 |
| BE-210 | Configuration d'intégration et référence de credential | 4 | BE-183, BE-190 |
| BE-211 | Webhook sortant | 3 | BE-192, BE-210 |
| BE-212 | Notifications par catégorie | 2 | BE-190, BE-211 |
| BE-213 | Jobs d'import et d'export | 4 | BE-183, BE-190, BE-191, BE-192 |
| BE-214 | Rétention, sauvegarde et purge | 1 | BE-183, BE-184, BE-204 |
| BE-215 | Compatibilité et versionnement des contrats | 1 | BE-192, BE-193, BE-211, BE-008, BE-226 |

---

## Tâches

### BE-180 — Enveloppe d'erreur et codes HTTP stables
- Domaine : Transverse (socle API)
- Vague : 6
- Routes : aucune
- Tables / migrations : aucune
- Droits : aucun droit requis pour la tâche. Codes attendus : 401 non authentifié ; 403 permission refusée ; 404 ressource absente ou hors scope (réponse identique) ; 409 conflit d'état, de version ou d'idempotence ; 422 règle de domaine ; 429 limite dépassée ; 5xx incident. Mapping complet : QE-API-03.
- Dépendances : BE-001 (enveloppe d'erreur, format propriétaire), BE-002 (tenant : isolation 404), BE-005 (authentification : 401), BE-009 (garde d'autorisation : 403)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : toute erreur renvoie l'enveloppe fixée par BE-001 (`error.code`, `error.message`, `error.field_errors`, `error.details`, `request_id`) ; le format n'est pas redéfini ici (test de contrat sur un jeu de 8 erreurs).
  - CA-2 : requête sans session reçoit 401 ; requête authentifiée sans permission reçoit 403 (test de refus).
  - CA-3 : une ressource d'un autre tenant et une ressource inexistante renvoient le même statut 404 et le même corps, hors `request_id` (test d'isolation tenant).
  - CA-4 : une réponse 429 porte l'en-tête `Retry-After` (test). NON DÉFINI : Recommandation appliquée : les champs `retryable` et `retryAfter` ne sont pas ajoutés au corps ; l'enveloppe de BE-001 reste inchangée. | QE-API-31
  - CA-5 : une réponse 5xx ne contient ni trace d'exécution ni secret (test).
  - CA-6 : chaque code HTTP du mapping QE-API-03 est couvert par exactement un test.
- Documentation attendue : docstrings de la fabrique d'erreurs et de chaque code ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Codes d’erreur / cohérence / testabilité`
- Code existant (develop) : `app/core/errors.py` (`AppError` ; handlers : enveloppe `error` {`code`, `message`, `field_errors`, `details`} + `request_id`, 422 `validation_error`, `http_<status>`, 500 `internal_error` sans détail) ; `app/auth/ratelimit.py` (429 `rate_limited` avec en-tête `Retry-After`) ; garder : l'enveloppe et les handlers de `app/core/errors.py` (format de BE-001), le 429 avec `Retry-After` ; casser : remplacer `http_<status>` par des codes stables change les codes déjà renvoyés, et ajouter `retryable`/`retryAfter` au corps modifie l'enveloppe de BE-001 (voir QE-API-31).

### BE-181 — Contexte de requête : correlationId et operationId (request_id fourni par BE-001)
- Domaine : Transverse (socle API)
- Vague : 7
- Routes : aucune
- Tables / migrations : aucune (champs ajoutés aux journaux et à l'audit)
- Droits : aucun. Un en-tête de correlation mal formé renvoie 400 (QE-API-03).
- Dépendances : BE-001 (propriétaire de `request_id`), BE-180
- Critères d'acceptation :
  - CA-1 : chaque réponse porte le `request_id` produit par BE-001 (BE-181 ne génère aucun second `request_id`) ; deux requêtes successives ont deux identifiants distincts (test de consommation).
  - CA-2 : un `correlationId` fourni par le client est repris à l'identique ; à défaut, il est généré (test).
  - CA-3 : chaque mutation reçoit un `operationId` stable, réutilisé lors d'un rejeu (test).
  - CA-4 : chaque ligne de journal d'une requête contient son `request_id` (test).
  - CA-5 : un en-tête contenant un secret n'est jamais écrit dans le journal (test, refus de fuite).
- Documentation attendue : docstrings du middleware de contexte ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Statut (paragraphe « Format commun »)`
- Code existant (develop) : `app/core/middleware.py` (`RequestIdMiddleware` : reprend `X-Request-Id` ou `X-Correlation-Id` s'ils respectent `^[A-Za-z0-9._:-]{1,128}$`, sinon génère un UUID ; renvoie les deux en-têtes avec la même valeur) ; `app/core/logging.py` (`request_id_ctx`, champ `request_id` du `JsonFormatter`) ; garder : `RequestIdMiddleware` et `request_id_ctx` ; casser : `request_id` et `correlationId` sont aujourd'hui le même identifiant, les séparer modifie les en-têtes `X-Request-Id` et `X-Correlation-Id` (voir QE-API-35) ; un en-tête mal formé est aujourd'hui ignoré (identifiant généré), non rejeté en 400 comme le prévoit QE-API-03 ; `operationId` n'existe pas.

### BE-182 — Scope tenant et identifiants opaques
- Domaine : Données transverses
- Vague : 8
- Routes : aucune
- Tables / migrations : toute table tenant-scoped reçoit `tenantId` NOT NULL ; les unicités locales incluent `tenantId` ; les références composites (`tenantId`, clé) interdisent un lien inter-tenant ; identifiants UUID opaques (QE-API-04), noms de tables QE-API-28.
- Droits : toute lecture ou écriture tenant-scoped vérifie `tenantId` côté serveur ; hors scope 404 (QE-API-03) ; aucun accès transversal sans permission plateforme explicite (refus 403).
- Dépendances : BE-181
- Critères d'acceptation :
  - CA-1 : la migration crée `tenantId` NOT NULL sur chaque table tenant-scoped listée (test de schéma).
  - CA-2 : l'insertion d'une ligne dont la référence pointe vers un autre tenant échoue (test d'isolation).
  - CA-3 : une requête portant le `tenantId` d'un autre tenant renvoie 404 (test d'isolation).
  - CA-4 : un identifiant de ressource seul, sans tenant résolu, n'accorde aucun accès (test de refus, 404).
  - CA-5 : deux lignes de tenants différents peuvent porter la même clé locale ; deux lignes du même tenant ne le peuvent pas (test de contrainte).
- Documentation attendue : docstrings des fonctions de résolution du tenant ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/architecture-donnees-api-backend-frontend.md#Frontières et responsabilités` ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Invariants de cohérence à valider`

### BE-183 — Idempotence des mutations et contrôle de version
- Domaine : Transverse (socle API)
- Vague : 9
- Routes : aucune propre ; en-tête `Idempotency-Key` obligatoire sur toute mutation répétable ; `expectedVersion` dans le corps de toute mutation d'agrégat versionné.
- Tables / migrations : table proposée `idempotency_record` (clé, `tenantId`, opération, empreinte du payload, statut, résultat, `createdAt`) ; contrainte d'unicité (`tenantId`, opération, clé). Nom de table : QE-API-28.
- Droits : aucun droit propre. Même clé avec payload différent : 409. `expectedVersion` obsolète : 409. Clé d'un autre tenant : traitée comme absente.
- Dépendances : BE-180, BE-181, BE-182
- Critères d'acceptation :
  - CA-1 : même clé et même payload rejouent le résultat initial sans second effet (test).
  - CA-2 : même clé avec payload différent renvoie 409 (test de refus).
  - CA-3 : `expectedVersion` différent de la version courante renvoie 409 et n'écrit rien (test de concurrence).
  - CA-4 : une clé de tenant A ne rejoue jamais le résultat d'un tenant B (test d'isolation).
  - CA-5 : après une panne simulée après commit, le rejeu renvoie le résultat commis sans second effet (test).
- Documentation attendue : docstrings du contrôle d'idempotence et du contrôle de version ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Codes d’erreur / cohérence / testabilité` ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (ligne Commerce)

### BE-184 — Journal d'audit append-only
- Domaine : Audit
- Vague : 9
- Routes : `GET /api/v1/audit/records` (QE-API-01)
- Tables / migrations : aucune table créée ici. Réutilise `audit_event` (propriétaire BE-007, qui migre `audit_log`) : colonnes `auditId`, `tenantId` nullable pour les actions plateforme, `actorId`, `action`, `scope`, `target`, `reason`, `correlationId`, `diffMinimal`, `createdAt`. NON DÉFINI : Recommandation appliquée : ces noms sont ceux de `audit_event` ; BE-007 confirme ou renomme, BE-184 suit. | QE-API-33 ; index (`tenantId`, `createdAt`), (`actorId`, `createdAt`), (`target`) ajoutés sur `audit_event` par migration additive. Aucune mise à jour ni suppression.
- Droits : écriture réservée au service d'audit (writer scoped) ; lecture par permission `audit.read` (QE-API-27), portée tenant ; lecture auditée. Sans permission : 403. Journal d'un autre tenant : 404.
- Dépendances : BE-007, BE-181, BE-182
- Critères d'acceptation :
  - CA-1 : une insertion réussit ; une mise à jour et une suppression sont rejetées par le moteur (test append-only).
  - CA-2 : lecture sans permission `audit.read` renvoie 403 (test de refus).
  - CA-3 : lecture d'un journal d'un autre tenant renvoie 404 (test d'isolation).
  - CA-4 : un mot de passe, un token ou une clé API présents dans un diff sont absents de l'enregistrement (test).
  - CA-5 : chaque lecture du journal produit elle-même une entrée d'audit (test).
  - CA-6 : une mutation échoue si son entrée d'audit ne peut être écrite (test, politique fail-closed, QE-API-08).
- Documentation attendue : docstrings de la fonction d'écriture et de lecture ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (ligne Audit) ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (AuditRecord)

### BE-185 — Tenant : cycle de vie
- Domaine : Tenant (plateforme)
- Vague : 9
- Routes :
  - `POST /api/v1/tenants` (demande de création, QE-API-01)
  - `GET /api/v1/tenants/{tenant_id}` (QE-API-01)
  - `POST /api/v1/tenants/{tenant_id}/transitions` (QE-API-01)
- Tables / migrations : `tenant` (`tenantId`, `state`, `version`, `createdAt`, `closedAt`). États : requested, provisioning, active, suspended, closing, closed. Unicité du slug : QE-API-05 et QE-API-28.
- Droits : création et transitions réservées à la permission plateforme `platform.tenant.manage` (QE-API-27) ; refus 403. Tenant `closed` lu par un utilisateur de tenant : 404.
- Dépendances : BE-182
- Critères d'acceptation :
  - CA-1 : une transition du graphe passe ; une transition absente du graphe (par exemple closed vers active) renvoie 422 (test par transition interdite).
  - CA-2 : un utilisateur de tenant sans permission plateforme demande une transition : 403 (test de refus).
  - CA-3 : un utilisateur du tenant A obtient 404 sur `GET /api/v1/tenants/{id}` du tenant B (test d'isolation).
  - CA-4 : chaque transition réussie écrit une entrée d'audit et une entrée outbox (test).
  - CA-5 : deux demandes identiques de même transition sur le même état renvoient 409 au second appel (test d'idempotence).
- Documentation attendue : docstrings des transitions ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Tenant) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Sélection tenant)

### BE-186 — Organisation et Workspace (candidat)
- Domaine : Organisation
- Vague : 10
- Routes :
  - `GET /api/v1/organizations/{organization_id}` (QE-API-01)
  - PATCH : aucune (la route `PATCH /api/v1/organizations/{organization_id}` est portée par BE-104)
- Tables / migrations : `organization` (`organizationId`, `tenantId` FK composite, `name`, identifiants légaux confidentiels, `version`). Un tenant porte exactement une organisation en v1 ; aucune table `workspace` en v1 (QE-API-05).
- Droits : `organization.read` et `organization.update` (QE-API-27), portée tenant. Sans permission sur PATCH : 403. Organisation d'un autre tenant : 404. Identifiants légaux visibles seulement avec permission dédiée `organization.legal.read` (QE-API-27), sinon absents de la réponse.
- Dépendances : BE-185
- Critères d'acceptation :
  - CA-1 : un tenant actif possède exactement une organisation (contrainte d'unicité sur `tenantId`, test).
  - CA-2 : PATCH avec `expectedVersion` obsolète renvoie 409 (test).
  - CA-3 : GET sur une organisation d'un autre tenant renvoie 404 (test d'isolation).
  - CA-4 : PATCH sans `organization.update` renvoie 403 (test de refus).
  - CA-5 : les identifiants légaux sont absents de la réponse sans `organization.legal.read` (test).
- Documentation attendue : docstrings des fonctions publiques du service ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Organisation, Workspace) ; `00-pilotage/architecture-fondation/phases/PH-14-donnees-api-backend-frontend-extension.md#Dépendances` (PH-07 forme tenant/organisation/workspace)

### BE-187 — Identité utilisateur
- Domaine : Identité (IAM)
- Vague : 9
- Routes : aucune publique ; la création d'un utilisateur passe par l'invitation (BE-189).
- Tables / migrations : `user_identity` (`userId`, `emailNormalized` unique globalement, `passwordHash`, `status`, `version`, `createdAt`). États : pending, active, locked, deactivated, deleted (QE-API-07).
- Droits : aucun droit de création direct. Le hash de mot de passe n'est jamais retourné.
- Dépendances : BE-182
- Critères d'acceptation :
  - CA-1 : le hash de mot de passe n'apparaît dans aucune réponse ni aucun journal (test).
  - CA-2 : deux e-mails identiques à la casse près sont refusés comme doublon (test de contrainte).
  - CA-3 : une transition de statut hors graphe renvoie 422 (test).
  - CA-4 : un utilisateur `locked` ne peut ouvrir de session : 401 (test de refus).
  - CA-5 : un utilisateur `deleted` ne renvoie plus aucune donnée personnelle (test).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (User / Identity) ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Confidentialité, historique et rétention`

### BE-188 — Session et authentification
- Domaine : Authentification (IAM)
- Vague : 10
- Routes :
  - connexion : aucune (la route `/api/v1/auth/login` est portée par BE-005)
  - `POST /api/v1/auth/logout` (QE-API-01)
  - Les routes d'échange de session GET /api/v1/auth/me et POST /api/v1/auth/refresh sont portées par BE-005 (doublon retiré ici).
- Tables / migrations : `session` (`sessionId`, `userId`, `createdAt`, `expiresAt`, `revokedAt`, `refreshTokenHash`). Durées : QE-API-06.
- Droits : `login` public ; `refresh`, `logout` et `me` exigent une session valide. Session absente, expirée ou révoquée : 401. Mutation par cookie sans origine valide : 403 (CSRF).
- Dépendances : BE-005, BE-180, BE-187
- Critères d'acceptation :
  - CA-1 : une session révoquée reçoit 401 sur `GET /api/v1/auth/me` (test de refus) (test porté par BE-005 ; BE-188 le réutilise).
  - CA-2 : une mutation par cookie avec origine invalide renvoie 403 (test CSRF).
  - CA-3 : un refresh token déjà utilisé après rotation renvoie 401 (test).
  - CA-4 : un login échoué est journalisé sans mot de passe (test).
  - CA-5 : `GET /api/v1/auth/me` ne renvoie que le principal courant et ses memberships actifs, sans donnée d'autre utilisateur (test d'isolation) (test porté par BE-005 ; BE-188 le réutilise).
- Documentation attendue : docstrings des routes d'authentification ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Auth/session) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (401 vs 403)

### BE-189 — Membership et sélection de contexte
- Domaine : Membership et contexte (IAM / organisation)
- Vague : 11
- Routes :
  - `GET /api/v1/contexts` (QE-API-01)
  - `POST /api/v1/contexts/select` (QE-API-01)
  - `GET /api/v1/memberships` (QE-API-01)
  - `POST /api/v1/memberships` (invitation, QE-API-01)
  - `PATCH /api/v1/memberships/{membership_id}` (QE-API-01)
  - `DELETE /api/v1/memberships/{membership_id}` (révocation, QE-API-01)
- Tables / migrations : `membership` (`membershipId`, `tenantId`, `userId`, `state` parmi invited, active, suspended, revoked, `version`) ; unicité (`tenantId`, `userId`). `workspaceId` absent en v1 (QE-API-05). Historique de révocation conservé (QE-API-15).
- Droits : `membership.manage` (QE-API-27) pour invitation, changement et révocation ; seul un membership `active` ouvre un contexte. Contexte d'un tenant sans membership actif : 404 (opaque). Invitation sans permission : 403.
- Dépendances : BE-183, BE-186, BE-188
- Critères d'acceptation :
  - CA-1 : `POST /api/v1/contexts/select` sur un tenant sans membership actif renvoie 404 (test d'isolation et de refus).
  - CA-2 : deux invitations identiques avec la même `Idempotency-Key` n'ajoutent qu'un seul membership (test d'idempotence).
  - CA-3 : invitation sans `membership.manage` renvoie 403 (test de refus).
  - CA-4 : `GET /api/v1/memberships` ne renvoie que les membres du tenant courant (test d'isolation).
  - CA-5 : après `DELETE`, la sélection du contexte renvoie 404 (test).
  - CA-6 : chaque changement de contexte et chaque changement de membership écrit une entrée d'audit (test).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Sélection tenant/membership)

### BE-190 — RBAC : rôles, permissions, grants et autorisation serveur
- Domaine : Autorisation (IAM)
- Vague : 12
- Routes :
  - `GET /api/v1/roles` (QE-API-01)
  - `POST /api/v1/roles/{role_id}/grants` (QE-API-01)
- Tables / migrations : `role` (`roleId`, `tenantId` NULL pour les rôles plateforme, `code`, `version`) ; `permission` (`code` stable, QE-API-27) ; `role_permission` ; `grant` (`grantId`, `tenantId`, `membershipId`, `roleId`, `scope`) ; index (sujet, scope).
- Droits : toute mutation évalue la permission côté serveur. Permission absente : 403. Rôle client ne peut pas accorder une permission plateforme : 403. Une permission inconnue est refusée : 422 à la déclaration.
- Dépendances : BE-184, BE-189
- Critères d'acceptation :
  - CA-1 : une permission non accordée renvoie 403 (test de refus).
  - CA-2 : un rôle d'un tenant ne s'applique pas à un autre tenant (test d'isolation, 404 sur la ressource).
  - CA-3 : une permission inconnue dans une déclaration est refusée 422 (test).
  - CA-4 : un rôle client qui tente d'accorder une permission plateforme reçoit 403 (test de refus).
  - CA-5 : chaque grant accordé ou révoqué écrit une entrée d'audit (test).
  - CA-6 : un bouton masqué côté interface n'accorde rien : un appel direct sans grant renvoie 403 (test).
- Documentation attendue : docstrings de la fonction `authorize` et de chaque permission déclarée ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Role / Permission / Grant) ; `00-pilotage/architecture-fondation/architecture-donnees-api-backend-frontend.md#Frontières et responsabilités`

### BE-191 — Pagination par curseur et quotas
- Domaine : Transverse (socle API)
- Vague : 7
- Routes : aucune propre ; paramètres `cursor` et `limit` sur toute liste.
- Tables / migrations : aucune.
- Droits : quota dépassé : 429 avec `retryAfter`. `limit` hors bornes : 400. Curseur d'un autre tenant : 404.
- Dépendances : BE-180
- Critères d'acceptation :
  - CA-1 : une liste renvoie un curseur opaque et un ordre déterministe (test).
  - CA-2 : un curseur produit pour le tenant A, présenté par le tenant B, renvoie 404 (test d'isolation).
  - CA-3 : un dépassement de quota renvoie 429 avec `retryAfter` et `retryable = true` (test).
  - CA-4 : les quotas produit et les limites techniques sont configurés séparément (test sur deux configurations).
  - CA-5 : un `limit` supérieur au maximum renvoie 400 (test ; bornes QE-API-17).
- Documentation attendue : docstrings du paginateur et du contrôle de quota ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Statut (paragraphe « Format commun »)` (pagination, limites) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Codes d’erreur / cohérence / testabilité` (429)
- Code existant (develop) : `app/shared/pagination.py` (`PaginationParams` : `limit` défaut 20, borne 1 à 100, `offset` ; `paginate()` : décalage et total ; schémas `Page` et `PageMeta` de `app/shared/schemas.py`) ; aucun quota produit (`app/auth/ratelimit.py` ne limite que les tentatives de connexion) ; garder : les bornes de `limit` (QE-API-17) et `PaginationParams` pour les listes existantes ; casser : remplacer le décalage par un curseur change la réponse des listes déjà paginées (`app/alerts`, `app/audit`, `app/billing`, `app/location`, `app/modules/zylo_liquid`), voir QE-API-36.

### BE-192 — Outbox producteur et enveloppe d'événement
- Domaine : Événements
- Vague : 10
- Routes : aucune publique. Lecture d'exploitation : NON DÉFINI (QE-API-01).
- Tables / migrations : `event_outbox` (`eventId` unique, `eventType`, `schemaVersion`, `occurredAt`, `recordedAt`, `tenantId`, `aggregateType`, `aggregateId`, `aggregateVersion`, `producer`, `correlationId`, `causationId`, `payload`, `publishedAt`). Nom de table : QE-API-28.
- Droits : écriture de l'outbox dans la même transaction que le changement local ; `tenantId` de la ligne égal à celui de l'agrégat, sinon rejet. Hors droit : 403 sur la lecture d'exploitation.
- Dépendances : BE-182, BE-183
- Critères d'acceptation :
  - CA-1 : le changement métier et sa ligne outbox sont validés ou annulés ensemble (test de panne injectée avant commit : aucune ligne).
  - CA-2 : l'enveloppe contient tous les champs listés (test de schéma).
  - CA-3 : le payload ne contient ni secret ni donnée personnelle superflue (test).
  - CA-4 : `eventId` est unique (test de contrainte).
  - CA-5 : une ligne dont le `tenantId` diffère de celui de l'agrégat est rejetée (test d'isolation).
- Documentation attendue : docstrings de l'écriture outbox et de l'enveloppe ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Enveloppe évènementielle` ; `00-pilotage/architecture-fondation/architecture-donnees-api-backend-frontend.md#Frontières et responsabilités` (Consistance)

### BE-193 — Inbox consommateur et dispatcher
- Domaine : Événements
- Vague : 11
- Routes : aucune
- Tables / migrations : `event_inbox` (`subscriber`, `eventId`, `status` parmi processed, retry, quarantine, `attempts`, `receivedAt`) ; unicité (`subscriber`, `eventId`).
- Droits : le consommateur vérifie le scope tenant de chaque événement ; tenant inconnu : quarantaine. Nombre maximal de tentatives : QE-API-16. Livraison : QE-API-22.
- Dépendances : BE-192
- Critères d'acceptation :
  - CA-1 : un même couple (`subscriber`, `eventId`) n'est traité qu'une fois (test de déduplication).
  - CA-2 : un événement d'un tenant inconnu du consommateur est mis en quarantaine (test d'isolation).
  - CA-3 : un événement hors ordre pour un agrégat qui exige l'ordre est mis en attente (test).
  - CA-4 : après le nombre maximal de tentatives, l'événement passe en quarantaine (test de reprise bornée).
  - CA-5 : un événement de schéma incompatible passe en quarantaine (test).
  - CA-6 : après un crash suivant la publication, le dispatcher republie l'événement (test d'au-moins-une-fois).
- Documentation attendue : docstrings du consommateur et du dispatcher ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Enveloppe évènementielle`

### BE-194 — Catalogue Module et ModuleVersion
- Domaine : Catalogue plateforme
- Vague : 13
- Routes :
  - `GET /api/v1/modules` (QE-API-01)
  - `GET /api/v1/modules/{module_code}` (QE-API-01)
  - `GET /api/v1/modules/{module_code}/versions/{version}` (QE-API-01)
- Tables / migrations : `module` (`moduleId`, `code` unique, `status` parmi draft, published, deprecated) ; `module_version` (`moduleId`, `version`, `compatibility`, `manifest`, `status`). Visibilité du catalogue : QE-API-27.
- Droits : la lecture du catalogue ne donne aucun droit (aucun droit inféré du listing). Écriture du catalogue : permission plateforme `platform.catalog.manage` (QE-API-27) ; refus 403. Version inconnue : 404 ; version dépréciée : 422 à l'activation.
- Dépendances : BE-182, BE-190
- Critères d'acceptation :
  - CA-1 : une version dépréciée ou inconnue reçoit une erreur explicite (test : 422 ou 404 selon le cas).
  - CA-2 : après un listing, une action sans grant reste refusée 403 (test de non-inférence de droit).
  - CA-3 : une écriture du catalogue sans `platform.catalog.manage` renvoie 403 (test de refus).
  - CA-4 : seules les versions `published` et compatibles sont proposées à l'installation (test).
  - CA-5 : deux modules de même code ne peuvent coexister (test de contrainte).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Catalogue) ; `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Catalog registration)

### BE-195 — Manifeste de module et registre
- Domaine : Extension (registre des modules)
- Vague : 14
- Routes : `POST /api/v1/admin/modules/{module_code}/versions` (publication du manifeste, QE-API-01)
- Tables / migrations : `module_version.manifest` (JSON validé) ; champs requis du manifeste : identifiant et code, release, versions de contrats API et événements, dépendances, schéma de configuration, permissions demandées, routes, migrations, compatibilité (QE-API-27).
- Droits : `platform.catalog.manage` (QE-API-27) ; refus 403. Une permission déclarée n'est jamais accordée par la seule déclaration.
- Dépendances : BE-194
- Critères d'acceptation :
  - CA-1 : un manifeste incomplet (champ requis absent) est refusé 422 (test de refus).
  - CA-2 : une dépendance absente du catalogue est refusée 422 (test).
  - CA-3 : une permission inconnue est refusée 422 (test).
  - CA-4 : la publication d'un manifeste ne crée aucun grant (test : nombre de grants inchangé).
  - CA-5 : une publication sans `platform.catalog.manage` renvoie 403 (test de refus).
  - CA-6 : chaque rejet de manifeste écrit une entrée d'audit (test).
- Documentation attendue : docstrings du validateur de manifeste et de chaque règle ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Manifest)

### BE-196 — Cycle de vie OrganizationModule
- Domaine : Lifecycle module par organisation
- Vague : 15
- Routes :
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/preflight` (QE-API-01)
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/activate` (QE-API-01)
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/suspend` (QE-API-01)
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/resume` (QE-API-01)
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/upgrade` (QE-API-01)
  - `POST /api/v1/organizations/{organization_id}/modules/{module_code}/uninstall` (QE-API-01)
- Tables / migrations : `organization_module` (`organizationModuleId`, `tenantId`, `organizationId`, `moduleId`, `moduleVersion`, `state`, `expectedVersion`, `operationId`, `version`) ; unicité (`organizationId`, `moduleId`). Liste des états détaillés : QE-API-13 et QE-API-27.
- Droits : `module.manage` (QE-API-27) pour l'administrateur d'organisation, plus l'entitlement de capacité, évalués séparément. Permission absente : 403. Entitlement absent : 422. Organisation d'un autre tenant : 404.
- Dépendances : BE-183, BE-189, BE-190, BE-192, BE-195
- Critères d'acceptation :
  - CA-1 : deux activations successives du même module ne provisionnent qu'une fois (test d'idempotence).
  - CA-2 : un entitlement absent bloque l'activation : 422 (test de refus).
  - CA-3 : une permission `module.manage` absente renvoie 403 (test de refus).
  - CA-4 : un échec de hook laisse l'état `failed`, récupérable et rejouable (test).
  - CA-5 : activer un module pour l'organisation A ne modifie pas l'organisation B (test d'isolation).
  - CA-6 : chaque activation écrit une entrée d'audit et une entrée outbox (test).
- Documentation attendue : docstrings de chaque opération du cycle de vie ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Activation) ; `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Tenant allocation)

### BE-197 — Hooks de module
- Domaine : Extension (hooks)
- Vague : 16
- Routes : aucune
- Tables / migrations : `hook_invocation` (`hookId`, `tenantId`, `durationMs`, `status`, `correlationId`) ; schémas d'entrée et de sortie versionnés.
- Droits : le contexte du hook est restreint au tenant ; un hook ne reçoit aucun privilège élevé. Permission élevée demandée dans un hook : refusée 403.
- Dépendances : BE-180, BE-196
- Critères d'acceptation :
  - CA-1 : une exception dans un hook n'altère pas un autre agrégat (test).
  - CA-2 : un hook qui dépasse le délai est interrompu, tracé, et n'écrit rien (test ; délai : QE-API-16).
  - CA-3 : un hook demandant une permission élevée est refusé 403 (test de refus).
  - CA-4 : une nouvelle tentative de hook n'a lieu que si le hook déclare son idempotence (test).
  - CA-5 : une entrée ou une sortie hors schéma versionné est rejetée 422 (test).
- Documentation attendue : docstrings de l'enregistrement et de l'invocation des hooks ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Hook)

### BE-198 — Migration de module : expand, migrate, verify, contract, dry-run
- Domaine : Migration (extension)
- Vague : 16
- Routes :
  - `POST /api/v1/admin/migrations/{migration_id}/dry-run` (QE-API-01)
  - `POST /api/v1/admin/migrations/{migration_id}/run` (QE-API-01)
  - `POST /api/v1/admin/migrations/{migration_id}/resume` (QE-API-01)
  - `POST /api/v1/admin/migrations/{migration_id}/rollback` (QE-API-01)
- Tables / migrations : `migration_run` (`migrationId`, `state`, `checkpoint`, `lockOwner`, `leaseExpiresAt`, `startedAt`, `report`). Aucune migration métier n'est exécutée par cette tâche ; seul le cadre est livré.
- Droits : permission de maintenance `platform.maintenance.run` (QE-API-27), accès audité ; refus 403. Migration sur un tenant `suspended` ou `closed` : 422.
- Dépendances : BE-183, BE-196
- Critères d'acceptation :
  - CA-1 : un dry-run n'écrit aucune donnée métier (test : compteurs inchangés).
  - CA-2 : une interruption en cours de run reprend au dernier checkpoint (test de crash).
  - CA-3 : un verrou perdu arrête les écritures du run (test).
  - CA-4 : un échec après effet externe ne déclenche aucun rollback destructif ; la correction est en avant (test).
  - CA-5 : un accès de maintenance sans `platform.maintenance.run` renvoie 403 (test de refus).
  - CA-6 : une migration sur un tenant inactif renvoie 422 (test).
- Documentation attendue : docstrings des étapes et du contrôle de verrou ; doc de module, chemin : NON DÉFINI (QE-API-02) ; runbook de reprise : NON DÉFINI (QE-API-15).
- Source : `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Migration/coexistence conceptuelles` ; `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Migration module)

### BE-199 — Navigation et configuration de module
- Domaine : Extension (navigation et configuration)
- Vague : 16
- Routes :
  - `GET /api/v1/me/navigation` (QE-API-01)
  - `GET /api/v1/organizations/{organization_id}/modules/{module_code}/config` (QE-API-01)
  - `PUT /api/v1/organizations/{organization_id}/modules/{module_code}/config` (QE-API-01)
- Tables / migrations : `module_config` (`tenantId`, `organizationModuleId`, `schemaVersion`, `values` JSON, `version`). Configuration tenant séparée des réglages plateforme.
- Droits : `module.config.manage` (QE-API-27) ; refus 403. Organisation d'un autre tenant : 404. Réglage plateforme modifié par un administrateur de tenant : 403.
- Dépendances : BE-190, BE-196
- Critères d'acceptation :
  - CA-1 : une entrée de menu visible ne donne accès à la route que si le backend revalide la permission ; sans permission : 403 (test).
  - CA-2 : la configuration du tenant A n'est pas lisible par le tenant B (test d'isolation, 404).
  - CA-3 : une configuration non conforme à `schemaVersion` renvoie 422 (test).
  - CA-4 : un administrateur de tenant ne peut pas modifier un réglage plateforme : 403 (test de refus).
  - CA-5 : `PUT` avec `expectedVersion` obsolète renvoie 409 (test).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (Navigation/config)

### BE-200 — Plan et PlanVersion
- Domaine : Commercial plateforme
- Vague : 14
- Routes :
  - `GET /api/v1/plans` (QE-API-01)
  - `GET /api/v1/plans/{plan_code}/versions/{version}` (QE-API-01)
  - `POST /api/v1/admin/plans/{plan_code}/versions` (QE-API-01)
- Tables / migrations : `plan` (`planId`, `code` unique) ; `plan_version` (`planVersionId`, `planId`, `version`, `status`, `priceAmount`, `currency`) ; unicité (`planId`, `version`). Montants : QE-API-24 (valeurs NON DÉFINIES).
- Droits : `platform.catalog.manage` (QE-API-27) ; refus 403. Version publiée non modifiable : 409.
- Dépendances : BE-194
- Critères d'acceptation :
  - CA-1 : une modification d'une version publiée est refusée 409 (test d'immutabilité).
  - CA-2 : un changement de prix crée une nouvelle version (test).
  - CA-3 : une création sans `platform.catalog.manage` renvoie 403 (test de refus).
  - CA-4 : un montant sans devise est refusé 422 (test).
  - CA-5 : aucun montant n'apparaît dans les contrats d'interface tant que la valeur n'est pas validée (test de schéma, QE-API-24).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Plan / PlanVersion) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé`

### BE-201 — Entitlements et décision d'accès
- Domaine : Accès et capacités
- Vague : 16
- Routes :
  - `POST /api/v1/entitlements` (octroi, QE-API-01)
  - `PATCH /api/v1/entitlements/{entitlement_id}` (changement, QE-API-01)
  - `POST /api/v1/entitlements/{entitlement_id}/revoke` (révocation, QE-API-01)
  - `GET /api/v1/access/decisions` (décision d'accès et provenance, QE-API-01)
- Tables / migrations : aucune table créée ici. Réutilise `subscription_entitlement` (propriétaire BE-024) : colonnes `entitlementId`, `tenantId`, `beneficiaryId`, `capability`, `scope`, `source`, `effectiveFrom`, `effectiveTo`, `state` parmi granted, pending, revoked, expired, `version`. NON DÉFINI : Recommandation appliquée : BE-024 porte ces colonnes et leur unicité (`beneficiaryId`, `capability`, `source`, intervalle) ; BE-201 n'ajoute aucune colonne. | QE-API-34. Cache de décision : dérivé seulement, jamais source de vérité.
- Droits : la source (facturation ou catalogue) doit être autorisée ; octroi par `entitlement.manage` (QE-API-27). Un entitlement n'est pas une permission d'action : une action sans grant renvoie 403. Décision d'un autre tenant : refus 404.
- Dépendances : BE-024, BE-190, BE-196, BE-200
- Critères d'acceptation :
  - CA-1 : une action dont seul l'entitlement est présent renvoie 403 (test de non-substitution).
  - CA-2 : `GET /api/v1/access/decisions` renvoie la décision et sa provenance (test).
  - CA-3 : après révocation, un cache obsolète n'accorde plus l'accès (test).
  - CA-4 : une décision demandée pour le tenant B ne reflète pas un entitlement du tenant A (test d'isolation).
  - CA-5 : un double octroi identique ne crée pas de second entitlement (test d'idempotence).
  - CA-6 : chaque révocation écrit une entrée d'audit (test).
- Documentation attendue : docstrings de la décision d'accès et de la provenance ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Entitlements) ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Invariants de cohérence à valider`

### BE-202 — Devis, checkout et consentement
- Domaine : Commerce (facturation)
- Vague : 15
- Routes :
  - `POST /api/v1/quotes` (QE-API-01)
  - `POST /api/v1/checkouts` (QE-API-01)
  - `POST /api/v1/consents` (QE-API-01)
- Tables / migrations : `quote` (`quoteId`, `tenantId`, `payerId`, `beneficiaryId`, `planVersionId`, `state`, `version`) ; `checkout` (`checkoutId`, `quoteId`, `state`) ; `consent` (`consentId`, `payerId`, `kind`, `recordedAt`). Payeur, bénéficiaire et tenant sont trois champs distincts.
- Droits : rôle `billing.operate` (QE-API-27) revalidé, plus autorité du payeur et du délégué ; refus 403. Devis d'un autre tenant : 404. Consentement d'essai explicite requis (QE-API-25).
- Dépendances : BE-183, BE-189, BE-190, BE-200
- Critères d'acceptation :
  - CA-1 : un payeur sans rôle `billing.operate` reçoit 403 (test de refus).
  - CA-2 : un essai sans consentement explicite est refusé 422 (test).
  - CA-3 : un devis d'un autre tenant renvoie 404 (test d'isolation).
  - CA-4 : un rejeu avec la même `Idempotency-Key` renvoie le même résultat sans second effet (test).
  - CA-5 : un devis sur une version de plan non publiée renvoie 422 (test).
  - CA-6 : un paiement ne crée aucun entitlement : la conséquence d'accès passe par BE-201 (test).
- Documentation attendue : docstrings des commandes ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Commerce) ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Subscription) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé`

### BE-203 — Cycle de vie Subscription et commandes
- Domaine : Facturation (abonnements)
- Vague : 17
- Routes :
  - `POST /api/v1/subscriptions` (CreateSubscription, QE-API-01)
  - `POST /api/v1/subscriptions/{subscription_id}/confirm` (ConfirmSubscription, QE-API-01)
  - `POST /api/v1/subscriptions/{subscription_id}/change-plan` (QE-API-01)
  - `POST /api/v1/subscriptions/{subscription_id}/cancel` (QE-API-01)
  - `POST /api/v1/subscriptions/{subscription_id}/expire` (QE-API-01)
  - `POST /api/v1/subscriptions/{subscription_id}/close` (CloseSubscription, QE-API-01)
- Tables / migrations : utilise la table `subscription` de BE-023 (colonnes `subscriptionId`, `tenantId`, `payerId`, `beneficiaryIds`, `planVersionId`, `status`, `effectiveFrom`, `effectiveTo`, `version`) ; BE-203 ne crée pas de table `subscription` ; `subscription_transition` (historique). États retenus : pending, trialing, active, past_due, grace, suspended, cancel_scheduled, cancelled, expired, subscription_closed ; `incomplete` et `disputed` : QE-API-14 ; sous-états close_pending_finance, close_pending_entitlement, close_pending_data.
- Droits : `billing.operate` (QE-API-27) ; refus 403. Transition hors graphe : 422. Version obsolète : 409. Abonnement d'un autre tenant : 404.
- Dépendances : BE-023, BE-192, BE-201, BE-202
- Critères d'acceptation :
  - CA-1 : chaque transition hors graphe renvoie 422 (test par transition interdite).
  - CA-2 : les statuts `incomplete` et `disputed` ne sont pas transitionnables sur `subscription` (test, QE-API-14).
  - CA-3 : l'annulation prend effet à `periodEnd` par défaut (test, QE-API-12).
  - CA-4 : `expire` ne fait pas passer à `subscription_closed` sans prérequis de clôture vérifiés (test).
  - CA-5 : une commande sans `billing.operate` renvoie 403 (test de refus).
  - CA-6 : un abonnement d'un autre tenant renvoie 404 (test d'isolation).
  - CA-7 : chaque transition réussie écrit une entrée outbox et une entrée d'audit (test).
- Documentation attendue : docstrings de chaque commande et du graphe de transitions ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Correspondance du cycle Subscription avec PH-10` ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Commerce)

### BE-204 — Facture (Invoice)
- Domaine : Documents financiers
- Vague : 18
- Routes :
  - `GET /api/v1/invoices` (QE-API-01)
  - `GET /api/v1/invoices/{invoice_id}` (QE-API-01)
  - `POST /api/v1/invoices/{invoice_id}/finalize` (QE-API-01)
  - `POST /api/v1/invoices/{invoice_id}/void` (QE-API-01)
- Tables / migrations : `invoice` (`invoiceId`, `tenantId`, `payerId`, `issuer`, `number` NULL avant émission, `state`, `snapshot` JSON, `issuedAt`, `version`) ; unicité (`issuer`, `number`). Numérotation : QE-API-10 ; émetteur : QE-API-11.
- Droits : `billing.documents.read` (QE-API-27) pour la lecture, `billing.operate` pour finaliser et annuler ; refus 403. Facture d'un autre tenant : 404.
- Dépendances : BE-183, BE-203
- Critères d'acceptation :
  - CA-1 : une facture émise ne peut être modifiée : UPDATE rejeté, test de refus 409.
  - CA-2 : deux factures du même émetteur ne peuvent porter le même numéro (test de contrainte).
  - CA-3 : téléchargement ou lecture d'une facture d'un autre tenant renvoie 404 (test d'isolation).
  - CA-4 : `finalize` sans `billing.operate` renvoie 403 (test de refus).
  - CA-5 : `void` ne supprime pas la facture et ajoute l'état `void` (test).
  - CA-6 : chaque émission écrit une entrée d'audit (test).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Invoice) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Documents financiers)

### BE-205 — Avoir (CreditNote)
- Domaine : Documents financiers
- Vague : 19
- Routes :
  - `POST /api/v1/invoices/{invoice_id}/credit-notes` (QE-API-01)
  - `GET /api/v1/credit-notes/{credit_note_id}` (QE-API-01)
- Tables / migrations : `credit_note` (`creditNoteId`, `tenantId`, `invoiceId` NOT NULL, `number`, `amount`, `currency`, `reason`, `state`, `snapshot`).
- Droits : `billing.operate` pour créer ; `billing.documents.read` pour lire ; refus 403. Avoir sur une facture d'un autre tenant : 404.
- Dépendances : BE-204
- Critères d'acceptation :
  - CA-1 : un avoir sans référence de facture est refusé 422 (test).
  - CA-2 : la somme des avoirs dépassant le montant de la facture est refusée 422 (test).
  - CA-3 : la facture source n'est pas modifiée par l'avoir (test).
  - CA-4 : création sans `billing.operate` renvoie 403 (test de refus).
  - CA-5 : avoir sur facture d'un autre tenant renvoie 404 (test d'isolation).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (CreditNote)

### BE-206 — Tentative et paiement (PaymentAttempt, Payment)
- Domaine : Paiement
- Vague : 19
- Routes :
  - `POST /api/v1/invoices/{invoice_id}/payment-attempts` (QE-API-01)
  - `GET /api/v1/payment-attempts/{payment_attempt_id}` (QE-API-01)
  - `GET /api/v1/payments/{payment_id}` (QE-API-01)
- Tables / migrations : `payment_attempt` (`paymentAttemptId`, `tenantId`, `invoiceId`, `payerId`, `providerAccountId`, `providerRef`, `idempotencyKey`, `state` parmi created, submitted, requires_action, pending, unknown, succeeded, failed, cancelled) ; `payment` (`paymentId`, `tenantId`, `providerRef`, `gross`, `fees`, `net`, `currency`, `state` parmi pending, succeeded, partially_refunded, refunded). Fournisseur : QE-API-20.
- Droits : `billing.operate` ; refus 403. Paiement d'un autre tenant : 404. Aucun numéro de carte ni CVV accepté (QE-API-20).
- Dépendances : BE-183, BE-204
- Critères d'acceptation :
  - CA-1 : un timeout place la tentative en `unknown`, jamais en `failed` (test).
  - CA-2 : un rejeu avec la même clé ne crée pas de second débit (test d'idempotence).
  - CA-3 : un payload contenant un numéro de carte est refusé 422 (test de minimisation).
  - CA-4 : une allocation de paiement dépassant le solde de la facture est refusée 422 (test de non double comptabilisation).
  - CA-5 : création sans `billing.operate` renvoie 403 (test de refus).
  - CA-6 : un paiement d'un autre tenant renvoie 404 (test d'isolation).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (PaymentAttempt, Payment) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Payment)

### BE-207 — Reçu (Receipt)
- Domaine : Paiement
- Vague : 20
- Routes :
  - `POST /api/v1/payments/{payment_id}/receipts` (QE-API-01)
  - `GET /api/v1/receipts/{receipt_id}` (QE-API-01)
- Tables / migrations : `receipt` (`receiptId`, `tenantId`, `paymentId`, `amount`, `currency`, `state` parmi issued, void, corrected, `issuer`).
- Droits : `billing.operate` pour émettre ; `billing.documents.read` pour lire ; refus 403. Reçu d'un autre tenant : 404.
- Dépendances : BE-206
- Critères d'acceptation :
  - CA-1 : un reçu sans paiement de référence est refusé 422 (test).
  - CA-2 : le montant ou la devise du reçu ne peut différer du paiement (test).
  - CA-3 : émission sans `billing.operate` renvoie 403 (test de refus).
  - CA-4 : reçu d'un autre tenant renvoie 404 (test d'isolation).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Receipt)

### BE-208 — Remboursement et litige (Refund, Dispute)
- Domaine : Paiement
- Vague : 20
- Routes :
  - `POST /api/v1/payments/{payment_id}/refunds` (QE-API-01)
  - `GET /api/v1/refunds/{refund_id}` (QE-API-01)
  - `GET /api/v1/disputes/{dispute_id}` (QE-API-01)
- Tables / migrations : `refund` (`refundId`, `tenantId`, `paymentId`, `providerRefundRef` unique, `amount`, `state` parmi requested, pending, unknown, succeeded, failed, cancelled, `approvedBy`) ; `dispute` (`disputeId`, `tenantId`, `paymentId`, `providerDisputeId` unique, `state` parmi opened, evidence_due, submitted, won, lost, closed, `dueAt`).
- Droits : `billing.refund.approve` (QE-API-27) : approbation humaine obligatoire avant tout remboursement ; refus 403 sans approbation. Remboursement cumulé supérieur au plafond : 422. Remboursement d'un autre tenant : 404.
- Dépendances : BE-206
- Critères d'acceptation :
  - CA-1 : un cumul de remboursements supérieur au net du paiement est refusé 422 (test).
  - CA-2 : un remboursement sans approbation humaine n'est jamais envoyé au fournisseur (test de refus).
  - CA-3 : un remboursement n'écrase pas le paiement (test).
  - CA-4 : demande de remboursement sans `billing.operate` renvoie 403 (test de refus).
  - CA-5 : litige ou remboursement d'un autre tenant renvoie 404 (test d'isolation).
  - CA-6 : l'état d'un litige ne modifie jamais l'état du paiement (test).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Refund, Dispute) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Payment) ; `00-pilotage/architecture-fondation/phases/PH-14-donnees-api-backend-frontend-extension.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` (contrôle humain des actions irréversibles)

### BE-209 — Webhook PSP entrant
- Domaine : Paiement (intégration entrante)
- Vague : 20
- Routes : `POST /api/v1/webhooks/psp/{provider}` (QE-API-01)
- Tables / migrations : `psp_webhook_receipt` (`provider`, `providerEventId`, `signatureVerified`, `payloadHash`, `receivedAt`, `processedStatus`) ; unicité (`provider`, `providerEventId`).
- Droits : pas de session ; authentification par signature. Signature invalide : 401 et aucun effet. Algorithme et fenêtre anti-rejeu : QE-API-19. Tenant inconnu : quarantaine via BE-193.
- Dépendances : BE-193, BE-206
- Critères d'acceptation :
  - CA-1 : une signature invalide renvoie 401 sans aucun effet métier (test de refus).
  - CA-2 : un doublon d'événement fournisseur ne double ni paiement ni remboursement (test).
  - CA-3 : un événement arrivé hors ordre n'écrase pas un état plus récent (test).
  - CA-4 : un rejeu hors fenêtre anti-rejeu est refusé 401 (test).
  - CA-5 : un événement référençant un tenant inconnu est mis en quarantaine (test d'isolation).
- Documentation attendue : docstrings du récepteur et de la vérification de signature ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Payment) ; `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Enveloppe évènementielle`

### BE-210 — Configuration d'intégration et référence de credential
- Domaine : Intégrations
- Vague : 13
- Routes :
  - `POST /api/v1/integrations` (QE-API-01)
  - `GET /api/v1/integrations/{integration_id}` (QE-API-01)
  - `POST /api/v1/integrations/{integration_id}/rotate` (QE-API-01)
  - `POST /api/v1/integrations/{integration_id}/revoke` (QE-API-01)
- Tables / migrations : `integration` (`integrationId`, `tenantId`, `provider`, `purpose`, `scopes`, `configSchemaVersion`, `state` parmi configured, active, degraded, revoked, `credentialRef`) ; unicité (`tenantId`, `provider`, `purpose`). Le secret est stocké dans un coffre dédié ; seule la référence est en base (QE-API-20).
- Droits : `integration.manage` (QE-API-27), portée tenant ; refus 403. Intégration d'un autre tenant : 404.
- Dépendances : BE-183, BE-190
- Critères d'acceptation :
  - CA-1 : après création, le secret ne peut plus être relu (test : `GET` ne renvoie aucun secret).
  - CA-2 : aucun secret, token ou ciphertext n'apparaît dans les journaux ni les exports (test).
  - CA-3 : après révocation, tout appel utilisant la référence est refusé (test).
  - CA-4 : pendant une rotation, l'ancien secret reste valide jusqu'à révocation explicite puis est refusé (test).
  - CA-5 : création sans `integration.manage` renvoie 403 (test de refus).
  - CA-6 : une intégration d'un autre tenant renvoie 404 (test d'isolation).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Integration config) ; `03-plateforme/architecture-donnees-api/01-modele-logique.md#Objets et responsabilité` (Integration / CredentialRef)

### BE-211 — Webhook sortant
- Domaine : Intégrations (sortant)
- Vague : 14
- Routes :
  - `POST /api/v1/webhook-endpoints` (QE-API-01)
  - `POST /api/v1/webhook-endpoints/{endpoint_id}/rotate-secret` (QE-API-01)
  - `GET /api/v1/webhook-deliveries/{delivery_id}` (QE-API-01)
- Tables / migrations : `webhook_endpoint` (`endpointId`, `tenantId`, `url`, `secretRef`, `state`) ; `webhook_delivery` (`deliveryId`, `endpointId`, `eventId`, `attempts`, `status` parmi pending, delivered, failed, dlq, `nextAttemptAt`).
- Droits : `integration.manage` pour créer et faire tourner le secret ; refus 403. Livraison d'un autre tenant : 404. Signature, retries et DLQ : QE-API-16 et QE-API-19.
- Dépendances : BE-192, BE-210
- Critères d'acceptation :
  - CA-1 : chaque livraison porte une signature et un horodatage (test).
  - CA-2 : des échecs répétés placent la livraison en DLQ après le nombre maximal de tentatives (test).
  - CA-3 : `deliveryId` n'est consultable que par le tenant propriétaire ; autre tenant : 404 (test d'isolation).
  - CA-4 : pendant l'overlap de rotation, l'ancienne signature est acceptée ; après l'overlap, elle est refusée (test).
  - CA-5 : le payload ne contient que les champs de l'enveloppe minimisée (test).
  - CA-6 : création d'un endpoint sans `integration.manage` renvoie 403 (test de refus).
- Documentation attendue : docstrings du dispatcher et de la signature ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Webhook sortant)

### BE-212 — Notifications par catégorie
- Domaine : Notifications
- Vague : 15
- Routes :
  - `GET /api/v1/notification-preferences` (QE-API-01)
  - `PUT /api/v1/notification-preferences` (QE-API-01)
- Tables / migrations : `notification` (`notificationId`, `tenantId`, `recipientId`, `category`, `state` parmi queued, sent, failed, `createdAt`) ; `notification_preference` (`tenantId`, `userId`, `category`, `enabled`). Catégories : QE-API-21.
- Droits : chaque utilisateur ne lit et ne modifie que ses préférences ; autre utilisateur : 404 ; catégorie inconnue : 422. Envoi limité aux membres actifs du tenant.
- Dépendances : BE-190, BE-211
- Critères d'acceptation :
  - CA-1 : aucune notification ne contient de secret (test).
  - CA-2 : la préférence d'un autre utilisateur n'est pas accessible (test d'isolation, 404).
  - CA-3 : une catégorie inconnue renvoie 422 (test).
  - CA-4 : une notification d'un tenant n'est envoyée qu'aux membres actifs de ce tenant (test d'isolation).
  - CA-5 : un envoi en échec est repris jusqu'à la limite de tentatives puis passe en `failed` (test ; limite QE-API-16).
- Documentation attendue : docstrings des fonctions publiques ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` (contrats de notification par catégorie)

### BE-213 — Jobs d'import et d'export
- Domaine : Jobs (import, export)
- Vague : 13
- Routes :
  - `POST /api/v1/jobs` (CreateJob, QE-API-01)
  - `GET /api/v1/jobs/{job_id}` (QE-API-01)
  - `POST /api/v1/jobs/{job_id}/cancel` (QE-API-01)
  - `GET /api/v1/jobs/{job_id}/download` (QE-API-01)
- Tables / migrations : `job` (`jobId`, `tenantId`, `actorId`, `type`, `manifestSchemaVersion`, `state` parmi queued, running, succeeded, failed, cancelled, expired, `idempotencyKey`, `filePointer`, `expiresAt`) ; `job_error_report`. Expiration : QE-API-18.
- Droits : permission par type de job (QE-API-27), ACL vérifiée à chaque lecture et à chaque téléchargement ; refus 403 ; job d'un autre tenant : 404. Fichier non prêt : 409 `DOCUMENT_NOT_READY`. Fichier expiré : 404 `EXPORT_EXPIRED`.
- Dépendances : BE-183, BE-190, BE-191, BE-192
- Critères d'acceptation :
  - CA-1 : téléchargement par un autre tenant renvoie 404 (test d'isolation).
  - CA-2 : un doublon d'import avec la même `idempotencyKey` ne réimporte rien (test).
  - CA-3 : un fichier expiré renvoie 404 `EXPORT_EXPIRED` (test).
  - CA-4 : `CreateJob` sans permission du type renvoie 403 (test de refus).
  - CA-5 : un job interrompu reprend et aboutit au même résultat qu'un job non interrompu (test de reprise).
  - CA-6 : un téléchargement pendant la génération renvoie 409 `DOCUMENT_NOT_READY` (test).
- Documentation attendue : docstrings des fonctions publiques et du worker ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Contrats de domaine` (Import/export/job/search et Documents financiers)

### BE-214 — Rétention, sauvegarde et purge
- Domaine : Données (rétention)
- Vague : 19
- Routes : `POST /api/v1/admin/retention/purges` (QE-API-01)
- Tables / migrations : `retention_policy` (`category`, `duration`) : durées NON DÉFINIES (QE-API-15) ; `legal_hold` (`tenantId`, `scope`, `setAt`, `releasedAt`). Mécanisme de sauvegarde : QE-API-15.
- Droits : `platform.retention.manage` (QE-API-27) ; refus 403. Purge refusée si un `legal_hold` est actif : 422. Purge d'un tenant n'affecte jamais un autre tenant.
- Dépendances : BE-183, BE-184, BE-204
- Critères d'acceptation :
  - CA-1 : une purge sous `legal_hold` actif est refusée 422 (test de refus).
  - CA-2 : tant que la durée d'une catégorie est NON DÉFINIE, la purge de cette catégorie ne supprime rien (test).
  - CA-3 : une restauration de sauvegarde reproduit le nombre de lignes et les contrôles d'intégrité (test).
  - CA-4 : la purge d'un tenant laisse intact le tenant voisin (test d'isolation).
  - CA-5 : une demande d'effacement de donnée personnelle produit une entrée d'audit (test).
- Documentation attendue : docstrings de la politique de rétention et de la purge ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `03-plateforme/architecture-donnees-api/01-modele-logique.md#Confidentialité, historique et rétention` ; `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Migration/coexistence conceptuelles` (retention, sauvegarde)

### BE-215 — Compatibilité et versionnement des contrats
- Domaine : Contrats (API et événements)
- Vague : 15
- Routes : `GET /api/v1/contracts/{contract_name}/versions` (QE-API-01)
- Tables / migrations : `contract_version` (`contractName`, `version`, `status` parmi current, deprecated, `removedAt`) ; période de coexistence N/N-1 : QE-API-23.
- Droits : lecture réservée à la permission plateforme `platform.catalog.manage` (QE-API-27) ; refus 403.
- Dépendances : BE-192, BE-193, BE-211, BE-008, BE-226
- Dépendances externes : BE-008 (permission `platform.catalog.manage` définie dans le modèle RBAC) ; BE-226 (refus 403 appliqué par le moteur d'autorisation) | QE-DON-03
- Critères d'acceptation :
  - CA-1 : un changement additif passe sans nouveau major (test de compatibilité).
  - CA-2 : un changement cassant sans nouveau major est refusé (test de refus).
  - CA-3 : les versions N et N-1 sont toutes deux acceptées pendant la période de coexistence (test ; durée QE-API-23).
  - CA-4 : un consommateur N-1 reçoit un champ inconnu sans erreur (test).
  - CA-5 : une version dépréciée n'est plus sélectionnable pour une nouvelle souscription (test).
- Documentation attendue : docstrings du registre de versions ; doc de module, chemin : NON DÉFINI (QE-API-02).
- Source : `00-pilotage/architecture-fondation/contrats-api-et-evenements.md#Enveloppe évènementielle` (breaking schema) ; `00-pilotage/architecture-fondation/regles-extension-sans-duplication-metier.md#Contrat candidat` (API/events)

---

## Points ouverts

Chaque point est tranché par la recommandation appliquée ; aucune décision n'est présentée comme acquise.

- Question : quels chemins, préfixe et transport d'API retenir (les sources ne fixent ni endpoint ni versionnement) ?
  - NON DÉFINI : Recommandation appliquée : préfixe `/api/v1`, JSON sur HTTPS, cookie de session pour le navigateur, chemins des routes de la section Tâches. | QE-API-01
- Question : où placer les modules et la documentation de module du back-end ?
  - NON DÉFINI : Recommandation appliquée : un dossier par domaine dans le dépôt back-end, docstring en tête de chaque module, aucun fichier de documentation supplémentaire. | QE-API-02
- Question : quel est le mapping exact des codes d'erreur ?
  - NON DÉFINI : Recommandation appliquée : 400, 401, 403, 404, 409, 422, 429, 5xx selon BE-180 ; entitlement absent = 422 ; `EXPORT_EXPIRED` = 404 ; `DOCUMENT_NOT_READY` = 409. | QE-API-03
- Question : quel format d'identifiant retenir (UUID, ULID) ?
  - NON DÉFINI : Recommandation appliquée : UUID v4 opaques, sans signification métier. | QE-API-04
- Question : quelle est la cardinalité Tenant, Organisation et Workspace ?
  - NON DÉFINI : Recommandation appliquée : un tenant porte exactement une organisation, aucune table `workspace` en v1. | QE-API-05
- Question : quelles sont la MFA et les durées de session et de CSRF ?
  - NON DÉFINI : Recommandation appliquée : MFA hors v1 ; durées de session NON DÉFINI ; mutation par cookie avec origine invalide renvoie 403. | QE-API-06
- Question : l'e-mail utilisateur est-il unique globalement ?
  - NON DÉFINI : Recommandation appliquée : e-mail normalisé en minuscules, unique globalement. | QE-API-07
- Question : que fait une mutation si l'entrée d'audit échoue (politique par opération) ?
  - NON DÉFINI : Recommandation appliquée : fail-closed, la mutation échoue et n'est pas écrite. | QE-API-08
- Question : quel fuseau retenir pour les dates contractuelles ?
  - NON DÉFINI : Recommandation appliquée : stockage en UTC ; fuseau contractuel NON DÉFINI et non utilisé en v1. | QE-API-09
- Question : quelle est la règle de numérotation des factures et avoirs ?
  - NON DÉFINI : Recommandation appliquée : numéro unique par émetteur (contrainte d'unicité), séquence attribuée à l'émission uniquement. | QE-API-10
- Question : qui est l'émetteur des documents financiers (Zylo ou ERP) ?
  - NON DÉFINI : Recommandation appliquée : Zylo émetteur par défaut ; aucune écriture ERP en v1. | QE-API-11
- Question : une annulation prend-elle effet immédiatement ou à la fin de période ?
  - NON DÉFINI : Recommandation appliquée : effet à `periodEnd` par défaut. | QE-API-12
- Question : les états past_due, grace et suspended passent-ils automatiquement ?
  - NON DÉFINI : Recommandation appliquée : aucune transition automatique ; la commande est manuelle ; durées NON DÉFINI. | QE-API-13
- Question : que deviennent les statuts `incomplete` et `disputed` du Subscription ?
  - NON DÉFINI : Recommandation appliquée : `incomplete` non mappé et non transitionnable (422) ; `disputed` porté uniquement par Dispute, jamais par Subscription. | QE-API-14
- Question : quelles sont les durées de rétention, de purge et le mécanisme de sauvegarde ?
  - NON DÉFINI : Recommandation appliquée : aucune purge tant que la durée de la catégorie est NON DÉFINI ; sauvegarde selon mécanisme NON DÉFINI, test de restauration exigé. | QE-API-15
- Question : quelles sont les limites de retry, le délai de hook, la DLQ et le SLA ?
  - NON DÉFINI : Recommandation appliquée : 5 tentatives à intervalle croissant, délai de hook 10 secondes, DLQ après la dernière tentative. | QE-API-16
- Question : quelles sont les bornes des quotas et de `limit` de pagination ?
  - NON DÉFINI : Recommandation appliquée : `limit` par défaut 20, maximum 100 ; quotas produit configurables séparément. | QE-API-17
- Question : quelle durée de validité pour les URL temporaires et les exports ?
  - NON DÉFINI : Recommandation appliquée : URL valide 15 minutes ; export conservé 7 jours puis expiré. | QE-API-18
- Question : quel algorithme de signature et quelle fenêtre anti-rejeu pour les webhooks ?
  - NON DÉFINI : Recommandation appliquée : HMAC-SHA256 avec horodatage, fenêtre anti-rejeu de 300 secondes. | QE-API-19
- Question : quel coffre de secrets et quel fournisseur de paiement ?
  - NON DÉFINI : Recommandation appliquée : interface neutre d'adaptateur, aucun fournisseur ni coffre choisi ; secret jamais en base. | QE-API-20
- Question : quelles sont les catégories de notification ?
  - NON DÉFINI : Recommandation appliquée : liste fermée à valider, configurable sans changement de code. | QE-API-21
- Question : quelles garanties de livraison pour chaque flux événementiel ?
  - NON DÉFINI : Recommandation appliquée : au moins une fois avec déduplication sur (subscriber, eventId), par flux. | QE-API-22
- Question : quelle est la durée de coexistence N/N-1 des contrats ?
  - NON DÉFINI : Recommandation appliquée : N et N-1 acceptés jusqu'à décision explicite de retrait. | QE-API-23
- Question : quels montants, prix et taxes figurent dans les contrats ?
  - NON DÉFINI : Recommandation appliquée : aucun montant ni taxe réels dans les contrats tant que la valeur n'est pas validée. | QE-API-24
- Question : quelle est la durée d'essai et la règle de conversion ?
  - NON DÉFINI : Recommandation appliquée : consentement explicite requis, durée d'essai NON DÉFINI. | QE-API-25
- Question : quel modèle d'architecture de déploiement (Q-08) ?
  - NON DÉFINI : Recommandation appliquée : monolithe modulaire comme hypothèse de travail, interfaces séparables ; aucune décision prise. | QE-API-26
- Question : quels codes de permission et quels noms de rôles ?
  - NON DÉFINI : Recommandation appliquée : codes `<domaine>.<action>` stables, déclarés dans un registre unique ; liste à valider. | QE-API-27
- Question : quels noms de tables et de colonnes ?
  - NON DÉFINI : Recommandation appliquée : noms de tables en snake_case et noms de colonnes en camelCase, tels que listés dans les tâches (colonnes conformes au code develop). | QE-API-28
- Question : quelles prorata et périodes d'effet appliquer aux changements de plan ?
  - NON DÉFINI : Recommandation appliquée : aucun prorata en v1 ; aperçu d'upgrade sans formule ; effet selon la date d'échéance. | QE-API-29
- Question : l'administration plateforme suit-elle `/api/v1/admin` ?
  - NON DÉFINI : Recommandation appliquée : les routes d'administration plateforme sont sous `/api/v1/admin/...` ; les routes `/tenants` et `/contracts` restent sous `/api/v1` (lues par les utilisateurs du tenant ou par le catalogue). | QE-API-30
- Question : les champs `retryable` et `retryAfter` doivent-ils figurer dans l'enveloppe d'erreur (BE-180) ?
  - NON DÉFINI : Recommandation appliquée : non ajoutés au corps ; l'enveloppe reste celle de BE-001 (`app/core/errors.py`) ; le 429 porte l'en-tête `Retry-After`. | QE-API-31
- Question : la route `GET /api/v1/auth/me` est-elle déclarée par BE-005 ou par BE-188 ?
  - NON DÉFINI : Recommandation appliquée : BE-005 porte login, me, refresh ; BE-188 porte logout seulement | QE-API-32
- Question : quels noms et quelles colonnes pour `audit_event`, journal unique propriété de BE-007 ?
  - NON DÉFINI : Recommandation appliquée : colonnes listées dans BE-184 (colonnes camelCase, QE-API-28) ; BE-007 confirme ou renomme, et BE-184 suit. | QE-API-33
- Question : quelles colonnes et quelle unicité pour `subscription_entitlement`, propriété de BE-024 ?
  - NON DÉFINI : Recommandation appliquée : colonnes listées dans BE-201 ; BE-024 les porte et prévaut ; BE-201 ne crée aucune colonne. | QE-API-34
- Question : qui porte `request_id` entre BE-001 et BE-181 (et `correlationId`, `operationId`) ?
  - NON DÉFINI : Recommandation appliquée : `request_id` généré par le middleware de BE-001 ; BE-181 ajoute `correlationId` (en-tête client repris) et `operationId`, sans second générateur de `request_id`. | QE-API-35
- Question : la pagination par curseur remplace-t-elle la pagination par décalage existante ?
  - NON DÉFINI : Recommandation appliquée : curseur pour les nouvelles listes ; les listes existantes (`app/shared/pagination.py`) restent en décalage jusqu'à migration explicite. | QE-API-36
- Question : quelle casse retenir pour les noms de tables `audit_event` et `subscription_entitlement` ?
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-DON-01
- Question : quelle casse appliquer aux noms de tables (le CLAUDE.md du backend prévoit des tables camelCase) ?
  - NON DÉFINI : Recommandation appliquée : snake_case pour toutes les tables ; `auditLog` renommé `audit_log` (BE-007) ; colonnes restent en camelCase ; complète QE-DON-01 | QE-DON-02
- Question : BE-215 (compatibilité des contrats) déclare-t-elle des dépendances hors de ce fichier ?
  - NON DÉFINI : Recommandation appliquée : BE-008 (permission `platform.catalog.manage`) et BE-226 (refus 403 par le moteur d'autorisation) déclarés en dépendances externes ; BE-192, BE-193, BE-211 inchangées | QE-DON-03
