# Tâches back-end : portail client et organisation (PH-11)

- Domaine : portail client et organisation (back-end uniquement)
- Sources lues :
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-11-portail-client-et-organisation.md`
  - `definition-travail/00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md`
- Plage d'identifiants : BE-100 à BE-119 (20 identifiants utilisés, aucun reste, aucune réutilisation)
- Statut : provisoire. Les vagues seront recalculées plus tard. Les valeurs absentes des sources sont marquées NON DÉFINI et renvoient à la section « Points ouverts ».

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---:|---|
| BE-100 | Modèle Organisation, Tenant, Membership, Invitation | 0 | BE-002, BE-003, BE-004, BE-007, BE-188 (QE-POR-26) |
| BE-101 | Garde de portée organisation et autorisation par défaut | 0 | BE-100, BE-005, BE-008, BE-009 (QE-POR-27) |
| BE-102 | Création d'organisation | 1 | BE-100, BE-101 |
| BE-103 | Demande et statut de vérification d'organisation | 2 | BE-101, BE-102 |
| BE-104 | Mise à jour du profil organisation | 1 | BE-101, BE-102 |
| BE-105 | Invitations d'organisation | 2 | BE-100, BE-101 |
| BE-106 | Membres : liste, changement de rôle, retrait | 3 | BE-100, BE-101, BE-105 |
| BE-107 | Lecture des entitlements et modules activés | 1 | BE-101, BE-022, BE-024 |
| BE-108 | Lecture de l'usage (agrégats et limites) | 1 | BE-101 ; EXT non résolu (QE-POR-28) |
| BE-109 | Résumé du portail filtré par permission | 1 | BE-101, BE-106, BE-107, BE-108 |
| BE-110 | Session de paiement : création et lecture d'état | 2 | BE-101, BE-102, BE-103, BE-200, BE-202 (QE-POR-29) |
| BE-111 | Lecture des tentatives de paiement | 1 | BE-110, BE-206 (QE-POR-29) |
| BE-112 | Aperçu, changement et annulation d'abonnement | 2 | BE-101, BE-110, BE-200, BE-023, BE-203 (QE-POR-29) |
| BE-113 | Factures et avoirs : liste et téléchargement | 2 | BE-101, BE-204, BE-205 |
| BE-114 | Reçus : liste et accès | 2 | BE-101, BE-113, BE-207 |
| BE-115 | Paiements : liste et lecture | 1 | BE-101, BE-113, BE-114, BE-206 |
| BE-116 | Moyens de paiement : ajout, remplacement, sélection | 2 | BE-101 ; EXT non résolu (QE-POR-13) |
| BE-117 | Exports de données asynchrones | 3 | BE-101, BE-106, BE-213, BE-243 |
| BE-118 | Demande de support client | 1 | BE-101, BE-123 |
| BE-119 | Demande de fermeture de l'organisation | 1 | BE-101, BE-106, BE-112, BE-113 |

Le nombre de routes compte les routes API proposées dans la matrice de la source. Les chemins complets suivent la recommandation QE-POR-09 (préfixe `/api/v1/organizations/{organization_id}/`).

## Tâches

### BE-100 : Modèle Organisation, Tenant, Membership, Invitation
- Domaine : organisation et tenant
- Vague : 11
- Routes : aucune
- Tables / migrations :
  - `organization` : table de BE-002, non recréée ; BE-100 n'y ajoute aucune colonne.
  - `tenant` (id, organizationId, statut) avec contrainte unique sur `organizationId` : un tenant par organisation.
  - `membership` : table de BE-004 (`organization_user`), non recréée ; BE-100 y ajoute la contrainte unique sur (organizationId, identityId) et le statut d'appartenance.
  - `invitation` (id, organizationId, role, statut parmi `pending`, `accepted`, `expired`, `revoked`, expiresAt, createdBy). Destinataire : NON DÉFINI (QE-POR-24).
  - Aucune colonne `parentId` (QE-POR-05).
- Droits : aucun endpoint. Toute ligne porte `organizationId`. Les règles d'accès sont dans BE-101.
- Dépendances : BE-002 (organisation, tenant racine), BE-003 (identité : `identityId`), BE-004 (appartenance utilisateur–organisation), BE-007 (audit, table `audit_event`), BE-188 (session). Chevauchement des tables `organization` et `membership` avec BE-002 et BE-004 : QE-POR-26.
- Périmètre distinct de BE-002 : BE-002 possède la table `organization` et son identifiant canonique ; BE-100 n'ajoute que la lecture de l'organisation pour le portail, sans colonne (QE-POR-26).
- Périmètre distinct de BE-004 : BE-004 possède l'appartenance utilisateur–organisation ; BE-100 n'ajoute à cette table que la contrainte d'unicité et le statut, sans seconde table d'appartenance (QE-POR-26).
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la migration sur base vide crée `tenant` et `invitation` et ajoute à `membership` les contraintes décrites (test de migration).
  - CA-2 : insérer deux memberships identiques (même organisation, même identité) est refusé par la base (test de contrainte).
  - CA-3 : insérer une invitation avec un statut hors de `pending`, `accepted`, `expired`, `revoked` est refusé (test de contrainte).
  - CA-4 : insérer un second tenant pour une même organisation est refusé (test de contrainte).
- Documentation attendue : docstrings des modèles ; doc de module `docs/portail-organisation/organisation-modele.md` (QE-POR-02).
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` ; `#Machine d'états de l'interface`.

### BE-101 : Garde de portée organisation et autorisation par défaut
- Domaine : accès et autorisation
- Vague : 12
- Routes : aucune (garde appliquée à toute route `/api/v1/organizations/{organization_id}/...`) ; la vérification utilise la route de BE-109 (`GET /api/v1/organizations/{organization_id}/portal-summary`), route unique de ce fichier pour le résumé.
- Tables / migrations : aucune (lecture de `membership`, du rôle et des permissions)
- Droits :
  - Authentification obligatoire ; refus par défaut si action, ressource ou organisation n'est pas explicitement autorisée.
  - `OrgScope` résolu depuis le chemin et revalidé à chaque lecture et écriture ; l'identifiant d'organisation présent dans le navigateur (corps, en-tête, requête) est un sélecteur non fiable et ne modifie pas la portée.
  - Code HTTP attendu en refus : NON DÉFINI (QE-POR-01). Recommandation : 401 sans session ; 403 permission absente ; 404 organisation hors portée, avec la même réponse que pour une organisation inexistante.
- Dépendances : BE-100, BE-005 (authentification), BE-008 (permissions), BE-009 (garde de contexte organisation). Chevauchement avec BE-009 : QE-POR-27.
- Périmètre distinct de BE-009 : BE-009 porte la garde générique du contexte d'organisation ; BE-101 ne porte que les règles propres au portail, à savoir la résolution de `OrgScope` pour `/api/v1/organizations/{organization_id}/...`, le 404 anti-énumération et le refus par défaut sur la politique portail (QE-POR-27).
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : requête sans session sur la route de test retourne 401 (test de refus d'authentification).
  - CA-2 : un membre de l'organisation A appelant l'organisation B reçoit 404, avec un corps identique à celui d'une organisation inexistante (test d'isolation tenant et d'anti-énumération).
  - CA-3 : un membre sans la permission requise reçoit 403 ; le test couvre chaque permission listée dans les autres tâches (test de refus de droit).
  - CA-4 : une action absente de la politique est refusée (test de refus par défaut).
  - CA-5 : un identifiant d'organisation B dans le corps ou l'en-tête, avec un chemin de l'organisation A, donne une portée A (test d'isolation tenant).
- Documentation attendue : docstrings de `require_org_scope` et de la fonction d'évaluation de la politique ; doc de module `docs/portail-organisation/garde-portee.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Contrat de protection proposé` ; `#Rôles candidats et séparation de responsabilités`.

### BE-102 : Création d'organisation
- Domaine : organisation et tenant
- Vague : 13
- Routes :
  - `POST /api/v1/organizations`
- Tables / migrations : `organization` (nom, statut), `tenant` (organizationId), `membership` (créateur sans rôle Owner, voir QE-POR-04). Création dans une seule transaction.
- Droits :
  - Identité authentifiée ; permission `org:create` ; pas de portée organisation préexistante.
  - Doublon : même nom normalisé et même créateur refusé (QE-POR-04).
  - Aucun rôle Owner n'est attribué à la création (QE-POR-04).
  - Code HTTP attendu en refus : NON DÉFINI (QE-POR-01). Recommandation : 401 sans session, 403 sans `org:create`, 409 pour doublon.
- Dépendances : BE-100, BE-101
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : création valide retourne 201, crée une organisation et un tenant, et ne crée aucun membership de rôle Owner (test).
  - CA-2 : second appel avec même nom normalisé par le même créateur retourne 409 et ne crée aucune ligne (test de déduplication).
  - CA-3 : requête sans session retourne 401 ; requête d'un utilisateur sans `org:create` retourne 403 (test de refus de droit).
  - CA-4 : un champ `owner` dans le corps ne crée aucun membership Owner (test).
- Documentation attendue : docstring de `create_organization` ; doc de module `docs/portail-organisation/creation-organisation.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/onboarding/organization`) ; `#Rôles candidats et séparation de responsabilités`.

### BE-103 : Demande et statut de vérification d'organisation
- Domaine : organisation et tenant
- Vague : 14
- Routes :
  - `GET /api/v1/organizations/{organization_id}/verification`
  - `POST /api/v1/organizations/{organization_id}/verification`
- Tables / migrations : `verification_case` (id, organizationId, statut parmi `verification_pending`, `verification_required`, `verified`, `rejected`, motif interne non exposé, createdAt, updatedAt). Politique de décision : NON DÉFINI (QE-POR-07).
- Droits :
  - Permission de dépôt et de lecture : NON DÉFINI (QE-POR-07). Recommandation : Owner ou Admin de l'organisation.
  - Le motif interne n'est jamais renvoyé.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101, BE-102
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : `POST` par Owner ou Admin crée un cas en `verification_pending` et retourne 201 (test).
  - CA-2 : `GET` par membre sans droit retourne 403 ; `GET` sur une organisation hors portée retourne 404 (test de refus et d'isolation).
  - CA-3 : la réponse d'un cas rejeté ne contient pas le motif interne (test).
  - CA-4 : un `POST` contenant le statut `verified` est refusé et ne modifie rien (test : aucune décision par le client).
- Documentation attendue : docstrings du service de vérification ; doc de module `docs/portail-organisation/verification-organisation.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/onboarding/verification`) ; `#Correspondance candidate CAP/PAR/ACTF` (ligne « Vérification d'organisation »).

### BE-104 : Mise à jour du profil organisation
- Domaine : organisation et tenant
- Vague : 14
- Routes :
  - `PATCH /api/v1/organizations/{organization_id}`
- Tables / migrations : `organization` (champs modifiables : NON DÉFINI, QE-POR-18 ; colonne `version`). Journal d'audit des champs sensibles.
- Droits :
  - Permission `org:profile:manage` ; portée `OrgScope`.
  - Conflit de version : 409 (QE-POR-20).
  - Code HTTP attendu en refus : 401, 403, 404 ; champ non autorisé : 400 (QE-POR-01).
- Dépendances : BE-101, BE-102 ; EXT non résolu : liste des champs du profil définie en PH-07 (absente des sources)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : `PATCH` avec la version courante et un champ autorisé retourne 200 et incrémente `version` (test).
  - CA-2 : `PATCH` avec une version obsolète retourne 409 et ne modifie rien (test de conflit).
  - CA-3 : `PATCH` d'un champ non listé retourne 400 et ne modifie rien (test).
  - CA-4 : sans `org:profile:manage` retourne 403 ; organisation hors portée retourne 404 (test de refus et d'isolation).
  - CA-5 : la modification d'un champ sensible écrit une entrée d'audit (test ; liste des champs sensibles : QE-POR-18).
- Documentation attendue : docstring de `update_organization_profile` ; doc de module `docs/portail-organisation/profil-organisation.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/settings`).

### BE-105 : Invitations d'organisation
- Domaine : membres
- Vague : 13
- Routes :
  - `POST /api/v1/organizations/{organization_id}/invitations`
  - `POST /api/v1/organizations/{organization_id}/invitations/{invitation}/accept` (chemin recommandé, QE-POR-09 et QE-POR-24)
- Tables / migrations : `invitation` (statut, role, expiresAt, createdBy) ; `membership` créé à l'acceptation. Événements `MemberInvited` (création) et acceptation.
- Droits :
  - Création : permission `members:manage` ; portée `OrgScope`.
  - Acceptation : identité authentifiée égale au destinataire (QE-POR-24).
  - Aucun rôle Owner par invitation ; aucun transfert Owner implicite (QE-POR-04).
  - Code HTTP attendu en refus : 401, 403, 404 ; invitation expirée ou révoquée : 409 (QE-POR-01).
- Dépendances : BE-100, BE-101, BE-150
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : création par un utilisateur avec `members:manage` retourne 201, crée une invitation `pending` et émet `MemberInvited` (test avec double d'événements).
  - CA-2 : création par un membre sans `members:manage` retourne 403 et ne crée aucune invitation (test de refus de droit).
  - CA-3 : acceptation par une identité différente du destinataire retourne 403 (test de refus).
  - CA-4 : acceptation d'une invitation `expired` ou `revoked` retourne 409 et laisse le statut inchangé (test).
  - CA-5 : une invitation demandant le rôle Owner est refusée (test ; QE-POR-04).
- Documentation attendue : docstrings de `create_invitation` et `accept_invitation` ; doc de module `docs/portail-organisation/invitations.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/members`) ; `#Rôles candidats et séparation de responsabilités`.

### BE-106 : Membres : liste, changement de rôle, retrait
- Domaine : membres
- Vague : 14
- Routes :
  - `GET /api/v1/organizations/{organization_id}/members`
  - `POST /api/v1/organizations/{organization_id}/role-changes`
  - `DELETE /api/v1/organizations/{organization_id}/members/{membership}`
- Tables / migrations : `membership` (role, statut). Événements `RoleChanged`, `Removed`. Entrées d'audit pour chaque changement.
- Droits :
  - Permission `members:manage` ; portée `OrgScope`.
  - Retrait ou rétrogradation du dernier Owner refusé en 409 ; impact siège : NON DÉFINI (QE-POR-22).
  - Code HTTP attendu en refus : 401, 403, 404 ; violation du dernier Owner : 409 (QE-POR-01).
- Dépendances : BE-100, BE-101, BE-105, BE-150 (enveloppe d'événement), BE-234 (outbox : événements `RoleChanged` et `Removed`, QE-POR-21)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : `GET` ne retourne que les memberships de l'organisation demandée ; un membre de l'organisation B n'apparaît jamais dans la réponse de l'organisation A (test d'isolation tenant).
  - CA-2 : retrait ou rétrogradation du dernier Owner retourne 409 et laisse le membership intact (test).
  - CA-3 : `DELETE` d'un membership appartenant à une autre organisation retourne 404 (test d'isolation).
  - CA-4 : `POST /api/v1/organizations/{organization_id}/role-changes` par un membre sans `members:manage` retourne 403 (test de refus de droit).
  - CA-5 : un changement de rôle écrit `RoleChanged` et une entrée d'audit (test).
- Documentation attendue : docstrings de `list_members`, `change_role`, `remove_member` ; doc de module `docs/portail-organisation/membres.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/members`) ; `#Rôles candidats et séparation de responsabilités` (Membres/rôles).

### BE-107 : Lecture des entitlements et modules activés
- Domaine : entitlements et usage
- Vague : 13
- Routes :
  - `GET /api/v1/organizations/{organization_id}/entitlements`
- Tables / migrations : lecture seule de `subscription_entitlement` (table unique, propriétaire BE-024) et des activations de modules (BE-022) ; colonnes : NON DÉFINI (QE-POR-23). Aucune écriture.
- Droits :
  - Permission `entitlement:read` ; portée `OrgScope`.
  - Les droits inclus et les add-ons sont séparés dans la réponse.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101, BE-022, BE-024
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse sépare les droits inclus et les add-ons dans deux groupes distincts (test de forme).
  - CA-2 : sans `entitlement:read` retourne 403 (test de refus de droit).
  - CA-3 : organisation hors portée retourne 404 et aucune donnée d'entitlement (test d'isolation tenant).
  - CA-4 : `POST`, `PATCH` ou `DELETE` sur cette route sont refusés et ne modifient rien (test ; code NON DÉFINI, QE-POR-01).
- Documentation attendue : docstring de `get_entitlements` ; doc de module `docs/portail-organisation/entitlements.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/access`).

### BE-108 : Lecture de l'usage (agrégats et limites)
- Domaine : entitlements et usage
- Vague : 13
- Routes :
  - `GET /api/v1/organizations/{organization_id}/usage`
- Tables / migrations : lecture seule d'une projection `usage_snapshot` publiée par PH-09 (champs : agrégats, limites, date de mesure, granularité : NON DÉFINI, QE-POR-23).
- Droits :
  - Permission `usage:read` ; portée `OrgScope`.
  - Aucune donnée individuelle d'utilisateur dans la réponse.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101 ; EXT non résolu : publication de `UsageSnapshot` (PH-09, événement `UsageSnapshotPublished`) ; aucun objet unique trouvé (BE-253 « Limites d'usage » non retenu, QE-POR-28)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse contient la date de mesure et la granularité (test de forme).
  - CA-2 : la réponse ne contient aucun identifiant d'identité individuelle (test).
  - CA-3 : sans `usage:read` retourne 403 ; organisation hors portée retourne 404 (test de refus et d'isolation).
  - CA-4 : le snapshot de l'organisation B n'est jamais retourné sous l'organisation A (test d'isolation tenant).
- Documentation attendue : docstring de `get_usage` ; doc de module `docs/portail-organisation/usage.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/usage`).

### BE-109 : Résumé du portail filtré par permission
- Domaine : portail
- Vague : 15
- Routes :
  - `GET /api/v1/organizations/{organization_id}/portal-summary`
- Tables / migrations : aucune (agrégation des lectures autorisées de BE-106, BE-107, BE-108 et des sections de facturation).
- Droits :
  - Permission `portal:read` requise pour l'appel ; chaque section est incluse seulement si sa permission est accordée (`entitlement:read`, `usage:read`, `members:manage`, `billing:read`).
  - Une section non autorisée est omise, sans erreur globale.
  - Code HTTP attendu en refus : 401, 403 (sans `portal:read`), 404 (hors portée) (QE-POR-01).
- Dépendances : BE-101, BE-106, BE-107, BE-108
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : utilisateur avec `portal:read` seul reçoit une réponse sans sections billing, usage ni entitlements (test de filtrage).
  - CA-2 : sans `portal:read` retourne 403 (test de refus de droit).
  - CA-3 : organisation hors portée retourne 404 (test d'isolation tenant).
  - CA-4 : aucune donnée d'une autre organisation n'apparaît dans la réponse (test d'isolation tenant).
- Documentation attendue : docstring de `build_portal_summary` ; doc de module `docs/portail-organisation/resume-portail.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/home`).

### BE-110 : Session de paiement : création et lecture d'état
- Domaine : facturation
- Vague : 16
- Routes :
  - `POST /api/v1/organizations/{organization_id}/checkout-sessions`
  - `GET /api/v1/organizations/{organization_id}/checkout-sessions/{session}`
- Tables / migrations : `checkout_session` propriétaire BE-202 (QE-POR-29), champs attendus (id, organizationId, offre et cadence figées en snapshot, version de consentement, clé d'idempotence, statut) ; `order` ; lien vers `payment_attempt` (BE-111). Événement `CheckoutSessionCreated`.
- Droits :
  - `POST` : permission `billing:purchase` ; `GET` : permission `billing:read` ; portée `OrgScope`.
  - Consentement versionné obligatoire ; idempotence obligatoire (QE-POR-20).
  - Le succès n'est jamais déduit de la query string du retour navigateur ; l'état vient de l'état durable.
  - Code HTTP attendu en refus : 401, 403, 404 ; consentement absent : 400 (QE-POR-01).
- Dépendances : BE-101, BE-102, BE-103, BE-200 (catalogue, PlanVersion), BE-202 (checkout et consentement) ; tables `checkout_session` et `order` : propriétaire à confirmer (QE-POR-29)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : rejeu de `POST` avec la même clé retourne la même session sans doublon (test d'idempotence).
  - CA-2 : `POST` sans consentement versionné retourne 400 et ne crée rien (test).
  - CA-3 : `GET` avec `?status=succeeded` dans l'URL, sans état durable, retourne l'état durable (test anti-query string).
  - CA-4 : `POST` par un membre sans `billing:purchase` retourne 403 ; `GET` sans `billing:read` retourne 403 (tests de refus de droit).
  - CA-5 : session de l'organisation B demandée sous l'organisation A retourne 404 (test d'isolation tenant).
  - CA-6 : une modification du catalogue après création ne modifie pas l'offre figée de la session (test).
- Documentation attendue : docstrings de `create_checkout_session` et `get_checkout_session` ; doc de module `docs/portail-organisation/checkout.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (lignes `/checkout` et `/checkout/return`) ; `#Séquence nominale et frontières d'état`.

### BE-111 : Lecture des tentatives de paiement
- Domaine : facturation
- Vague : 20
- Routes :
  - `GET /api/v1/organizations/{organization_id}/billing/payment-attempts`
- Tables / migrations : `payment_attempt` propriétaire BE-206 (QE-POR-29), champs attendus (id, organizationId, checkoutSessionId, invoiceId optionnel, montant, devise, statut source, action requise, moyen masqué, référence de corrélation partielle, date). Aucune colonne PAN, CVV, token complet ni payload webhook.
- Droits :
  - Permission candidate `billing:payment-attempts:read` (QE-POR-11) ; payeur ou acheteur, ou finance, selon attribution ; Member refusé par défaut.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-110, BE-206 (états de paiement) ; registre de corrélation : NON DÉFINI, à rattacher à BE-206 (QE-POR-29)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse ne contient ni PAN, ni CVV, ni token complet, ni payload webhook (test sur fixture contenant ces valeurs).
  - CA-2 : les statuts `unknown` et `pending` sont renvoyés tels quels, sans transition vers `succeeded` (test).
  - CA-3 : Member sans la permission retourne 403 (test de refus de droit).
  - CA-4 : tentative de l'organisation B sous l'organisation A retourne 404 (test d'isolation tenant).
- Documentation attendue : docstring de `list_payment_attempts` ; doc de module `docs/portail-organisation/tentatives-paiement.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/payment-attempts`).

### BE-112 : Aperçu, changement et annulation d'abonnement
- Domaine : facturation
- Vague : 18
- Routes :
  - `POST /api/v1/organizations/{organization_id}/billing/subscription/change-previews`
  - `POST /api/v1/organizations/{organization_id}/billing/subscription/changes`
- Tables / migrations : `subscription` : utilise la table `subscription` de BE-023 (QE-POR-29), non recréée ; champs attendus (statut dont `past_due`, `suspended`, `canceled`, cadence, version d'offre) ; `change_preview` (id, organizationId, version d'offre cible, createdAt). Événement `SubscriptionStatusChanged`.
- Droits :
  - Permission `billing:manage` ; portée `OrgScope`.
  - Réauthentification requise pour le changement (QE-POR-16).
  - Aucun montant de prorata calculé ou affiché (QE-POR-08).
  - Downgrade appliqué à l'échéance ; upgrade affiché en aperçu.
  - Code HTTP attendu en refus : 401, 403, 404 ; aperçu absent ou expiré : 400 (QE-POR-01).
- Dépendances : BE-101, BE-110, BE-200, BE-023 (table `subscription`), BE-203 (cycle de vie Subscription) ; EXT non résolu : règles de période, fuseau, dates et prorata (valeurs NON DÉFINIES, QE-POR-08, QE-POR-29)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse de l'aperçu ne contient aucun champ de montant de prorata (test de forme).
  - CA-2 : un changement sans `previewId` valide est refusé et ne modifie rien (test).
  - CA-3 : un changement sans réauthentification récente retourne 403 (test de refus, QE-POR-16).
  - CA-4 : un downgrade demandé est enregistré en attente d'échéance et ne modifie pas l'abonnement immédiatement (test).
  - CA-5 : `billing:manage` absent retourne 403 ; organisation hors portée retourne 404 (tests de refus et d'isolation).
  - CA-6 : un changement rejoué avec la même clé produit une seule modification (test d'idempotence).
- Documentation attendue : docstrings de `preview_subscription_change` et `apply_subscription_change` ; doc de module `docs/portail-organisation/abonnement.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/subscription`) ; `#Recommandations approuvées le 2026-11-02` (dans `phases/PH-11-portail-client-et-organisation.md`).

### BE-113 : Factures et avoirs : liste et téléchargement
- Domaine : facturation
- Vague : 20
- Routes :
  - `GET /api/v1/organizations/{organization_id}/billing/invoices`
  - `GET /api/v1/organizations/{organization_id}/billing/credit-notes`
- Tables / migrations : aucune table propre ; lecture de la source finance/document (PH-10). Champs autorisés : référence, dates, total et devise, solde et état émis, lignes autorisées, compte facturé minimal, document lié.
- Droits :
  - Permission `billing:documents:read` sur le compte payeur et le document ; Owner seulement avec délégation approuvée (QE-POR-06).
  - Expurgation des données fiscales et de l'adresse selon le rôle (QE-POR-19).
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101, BE-204 (Facture), BE-205 (Avoir) ; système maître : QE-POR-12
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : sans permission de données fiscales, la réponse ne contient ni adresse ni identifiant fiscal (test d'expurgation).
  - CA-2 : sans `billing:documents:read` retourne 403 ; Owner sans délégation approuvée retourne 403 (tests de refus de droit).
  - CA-3 : une facture de l'organisation B n'apparaît pas sous l'organisation A ; organisation B hors portée retourne 404 (test d'isolation tenant).
  - CA-4 : chaque lecture et téléchargement écrit une entrée d'audit avec acteur, organisation, objet, résultat, corrélation et horodatage (test).
- Documentation attendue : docstrings de `list_invoices` et `list_credit_notes` ; doc de module `docs/portail-organisation/factures.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/documents`).

### BE-114 : Reçus : liste et accès
- Domaine : facturation
- Vague : 21
- Routes :
  - `GET /api/v1/organizations/{organization_id}/billing/receipts`
  - `GET /api/v1/organizations/{organization_id}/billing/receipts/{receipt}/file` (accès fichier par référence, chemin recommandé, QE-POR-09)
- Tables / migrations : aucune table propre ; lecture de la source Receipt (PH-10, système maître : QE-POR-12). Champs : référence reçue, date d'émission, montant et devise, état de disponibilité, référence Payment et Invoice liée si permise, payeur minimal.
- Droits :
  - Permission candidate `billing:receipts:read` (QE-POR-11) ; non accordée par défaut à Member.
  - Un Receipt n'est jamais présenté comme une Invoice.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101, BE-113, BE-207
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse d'un reçu n'expose ni type ni statut de facture (test de forme).
  - CA-2 : Member sans permission retourne 403 (test de refus de droit).
  - CA-3 : reçu de l'organisation B demandé sous l'organisation A retourne 404 (test d'isolation tenant).
  - CA-4 : chaque téléchargement écrit une entrée d'audit (test).
- Documentation attendue : docstrings de `list_receipts` et `get_receipt_file` ; doc de module `docs/portail-organisation/recus.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/receipts`).

### BE-115 : Paiements : liste et lecture
- Domaine : facturation
- Vague : 22
- Routes :
  - `GET /api/v1/organizations/{organization_id}/billing/payments`
- Tables / migrations : lecture de la source Payment (PH-10/PSP/ERP, système maître : QE-POR-12). Champs : référence, date, montant et devise, statut source, liens vers reçu et facture si permis. Identifiants PSP et payloads masqués.
- Droits :
  - Permission candidate `billing:payments:read` (QE-POR-11) ; ACTF-04 ou ACTF-05 avec permission financière.
  - Lecture journalisée.
  - Code HTTP attendu en refus : 401, 403, 404 (QE-POR-01).
- Dépendances : BE-101, BE-113, BE-114, BE-206 (Payment) ; système maître : QE-POR-12
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : une valeur de statut inconnue de la source est renvoyée telle quelle, sans enum inventé (test).
  - CA-2 : identifiants PSP et payloads sont absents de la réponse (test).
  - CA-3 : sans permission retourne 403 ; organisation B sous l'organisation A retourne 404 (tests de refus et d'isolation).
  - CA-4 : la lecture écrit une entrée d'audit (test).
- Documentation attendue : docstring de `list_payments` ; doc de module `docs/portail-organisation/paiements.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/payments`).

### BE-116 : Moyens de paiement : ajout, remplacement, sélection
- Domaine : facturation
- Vague : 13
- Routes :
  - `POST /api/v1/organizations/{organization_id}/billing/payment-methods` (ajout ou remplacement)
  - `POST /api/v1/organizations/{organization_id}/billing/payment-methods/{method}/select` (chemin recommandé, QE-POR-09)
- Tables / migrations : `payment_method_reference` (id, organizationId, référence de token, sélection, createdAt). Événement `PaymentMethodChanged`. Aucune colonne PAN ni CVV.
- Droits :
  - Permission `billing:payment-method:manage` ; portée `OrgScope` ; réauthentification (QE-POR-16).
  - Token seulement ; données carte refusées (QE-POR-13).
  - Code HTTP attendu en refus : 401, 403, 404 ; données carte : 400 (QE-POR-01).
- Dépendances : BE-101 ; EXT non résolu : choix du flux hébergé PSP (NON DÉFINI, QE-POR-13)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : une requête contenant PAN ou CVV retourne 400 et rien n'est stocké (test).
  - CA-2 : un ajout avec token seulement retourne 201 ; la réponse n'expose pas la valeur complète du token (test).
  - CA-3 : sans `billing:payment-method:manage` retourne 403 ; organisation B sous l'organisation A retourne 404 (tests de refus et d'isolation).
  - CA-4 : sans réauthentification, la requête retourne 403 (test).
  - CA-5 : chaque changement émet `PaymentMethodChanged` (test avec double d'événements).
- Documentation attendue : docstrings de `add_payment_method` et `select_payment_method` ; doc de module `docs/portail-organisation/moyens-paiement.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/billing/payment-methods`) ; `#Contrat de protection proposé` (point 5).

### BE-117 : Exports de données asynchrones
- Domaine : export
- Vague : 15
- Routes :
  - `POST /api/v1/organizations/{organization_id}/exports`
  - `GET /api/v1/organizations/{organization_id}/exports/{export}`
  - `GET /api/v1/organizations/{organization_id}/exports/{export}/download` (chemin recommandé, QE-POR-09)
- Tables / migrations : `export_job` (id, organizationId, périmètre, contenu, statut parmi `export_requested`, `ready`, `expired`, requestedBy, expiresAt). Événements `ExportRequested`, `ExportReady`, `ExportExpired`. Durée et rétention : NON DÉFINI (QE-POR-15).
- Droits :
  - Permission `data:export` ; Owner ou permission dédiée ; portée `OrgScope`.
  - Lien de téléchargement privé, éphémère et journalisé.
  - Code HTTP attendu en refus : 401, 403, 404 ; lien expiré : 410 recommandé (QE-POR-01).
- Dépendances : BE-101, BE-106, BE-213 (jobs d'export), BE-243 (export par sujet ou tenant)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : `POST` retourne 202 avec le statut `export_requested` ; le traitement s'exécute hors de la requête (test).
  - CA-2 : aucun lien de téléchargement n'est renvoyé tant que le statut n'est pas `ready` (test).
  - CA-3 : après `expiresAt`, le téléchargement est refusé (test avec horloge figée).
  - CA-4 : sans `data:export` retourne 403 ; export de l'organisation B sous l'organisation A retourne 404 (tests de refus et d'isolation).
  - CA-5 : aucune durée de validité n'est codée en dur ; sans valeur de configuration, aucun lien n'est émis (test ; QE-POR-15).
- Documentation attendue : docstrings de `request_export`, `get_export`, `download_export` ; doc de module `docs/portail-organisation/exports.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/exports`) ; `#Contrat de protection proposé` (point 6).

### BE-118 : Demande de support client
- Domaine : support
- Vague : 13
- Routes :
  - `POST /api/v1/organizations/{organization_id}/support-requests`
- Tables / migrations : `support_request` (id, organizationId, statut parmi `open`, `in_progress`, `resolved`, contexte non secret, createdBy, createdAt). Pièces jointes expurgées. Événement `SupportRequestCreated`.
- Droits :
  - Permission `support:create` ; portée `OrgScope`.
  - Aucune action au nom d'une autre identité (`createdBy` = identité authentifiée).
  - Code HTTP attendu en refus : 401, 403, 404 ; contexte secret : 400 (QE-POR-01).
- Dépendances : BE-101, BE-123
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : création valide retourne 201, statut `open`, et émet `SupportRequestCreated` (test).
  - CA-2 : un contexte contenant un mot de passe ou un token est refusé ou expurgé (test).
  - CA-3 : sans `support:create` retourne 403 (test de refus de droit).
  - CA-4 : requête vers l'organisation B sous l'organisation A retourne 404 (test d'isolation tenant).
  - CA-5 : `createdBy` est toujours l'identité authentifiée, quelle que soit la valeur du corps (test).
- Documentation attendue : docstring de `create_support_request` ; doc de module `docs/portail-organisation/support.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/help`).

### BE-119 : Demande de fermeture de l'organisation
- Domaine : fermeture
- Vague : 21
- Routes :
  - `POST /api/v1/organizations/{organization_id}/closure-requests`
- Tables / migrations : `closure_request` (id, organizationId, statut, requestedBy, confirmedAt). Événement `ClosureRequested`. Durée de conservation : NON DÉFINI (QE-POR-17).
- Droits :
  - Permission `org:close` ; Owner ou signataire autorisé (signataire : QE-POR-17) ; portée `OrgScope`.
  - Confirmation forte et réauthentification (QE-POR-16).
  - Refus si abonnement actif ou facture ouverte (QE-POR-17).
  - Code HTTP attendu en refus : 401, 403, 404 ; dépendance financière : 409 (QE-POR-01).
- Dépendances : BE-101, BE-106, BE-112, BE-113
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : demande sans confirmation forte est refusée (test).
  - CA-2 : organisation avec abonnement actif ou facture ouverte retourne 409 et ne crée aucune demande (test).
  - CA-3 : Admin sans `org:close` retourne 403 (test de refus de droit).
  - CA-4 : demande pour l'organisation B sous l'organisation A retourne 404 (test d'isolation tenant).
  - CA-5 : une demande valide émet `ClosureRequested` et écrit une entrée d'audit renforcée (test).
- Documentation attendue : docstring de `request_closure` ; doc de module `docs/portail-organisation/fermeture.md`.
- Source : `00-pilotage/architecture-fondation/parcours-et-autorisations-portail-organisation.md#Matrice écran → acteur → action → objet/API/événement → permission/audit` (ligne `/org/:id/closure`).

## Points ouverts

Chaque point reprend une incohérence ou une donnée absente des sources. La recommandation est appliquée ; aucune réponse n'est attendue pour avancer.

- Question : quels codes HTTP renvoyer pour non-authentification, permission absente, ressource hors portée, conflit et donnée invalide ?
  - NON DÉFINI : Recommandation appliquée : 401 sans session, 403 permission absente, 404 pour toute ressource hors portée avec corps identique à « inexistant », 409 pour conflit, 400 pour donnée invalide, testés par les CA. | QE-POR-01
- Question : dans quel module et sous quelle doc les tâches back-end sont-elles rangées (stack et arborescence non fournies) ?
  - NON DÉFINI : Recommandation appliquée : un module par domaine du tableau récapitulatif, doc de module sous `docs/portail-organisation/<module>.md`. | QE-POR-02
- Question : une identité peut-elle appartenir à plusieurs organisations ?
  - NON DÉFINI : Recommandation appliquée : une identité peut avoir plusieurs memberships ; chaque requête porte une seule organisation dans son chemin. | QE-POR-03
- Question : qui est propriétaire à la création, et quelle règle de déduplication s'applique ?
  - NON DÉFINI : Recommandation appliquée : POST /api/v1/organizations n'attribue aucun rôle Owner ; un doublon (même nom normalisé, même créateur) retourne 409 ; un transfert de propriété n'a aucun endpoint dans cette plage. | QE-POR-04
- Question : des sous-organisations existent-elles ?
  - NON DÉFINI : Recommandation appliquée : aucune ; le modèle est plat, sans colonne parent. | QE-POR-05
- Question : qui achète, consulte les factures, invite ou transfère ?
  - NON DÉFINI : Recommandation appliquée : la matrice « rôles candidats » s'applique ; une permission n'est accordée que par attribution explicite ; Member reçoit 403 sur les routes billing et members. | QE-POR-06
- Question : quel acteur décide de la vérification d'organisation, et selon quelle politique ?
  - NON DÉFINI : Recommandation appliquée : BE-103 limite le dépôt et la lecture à Owner ou Admin, sans décision côté client ni motif exposé ; la politique reste hors tâche. | QE-POR-07
- Question : quelles sont les règles de période, fuseau, dates et prorata d'un changement d'abonnement ?
  - NON DÉFINI : Recommandation appliquée : aucun montant de prorata n'est calculé ni affiché ; le downgrade s'applique à l'échéance ; l'upgrade est affiché en aperçu sans formule. | QE-POR-08
- Question : quels sont les chemins exacts des routes (les sources donnent « invitations », « role-changes », « member », « change-previews » sans préfixe) ?
  - NON DÉFINI : Recommandation appliquée : préfixe `/api/v1/organizations/{organization_id}/` pour toutes les routes ; acceptation d'invitation sous `/api/v1/organizations/{organization_id}/invitations/{invitation}/accept`. | QE-POR-09
- Question : la vue `/org/:id` et l'API `/api/v1/organizations/{organization_id}` sont-elles des chemins distincts ?
  - NON DÉFINI : Recommandation appliquée : `/org/:id` est une vue front uniquement ; l'API utilise exclusivement `/api/v1/organizations/{organization_id}`. | QE-POR-10
- Question : les permissions `billing:receipts:read`, `billing:payments:read`, `billing:payment-attempts:read` et `billing:payment-method:manage` sont-elles enregistrées dans le catalogue ?
  - NON DÉFINI : Recommandation appliquée : les enregistrer comme candidates au catalogue PH-08 ; tant qu'elles ne sont pas accordées, la route répond 403. | QE-POR-11
- Question : quel système est maître des factures, reçus, paiements et tentatives de paiement ?
  - NON DÉFINI : Recommandation appliquée : PH-10 est lu seul par le portail ; aucune écriture de ces objets depuis les routes du portail. | QE-POR-12
- Question : quel flux PSP hébergé est retenu, et comment traiter des données carte envoyées au backend ?
  - NON DÉFINI : Recommandation appliquée : seul un token de référence est stocké ; une requête contenant PAN ou CVV retourne 400 sans rien stocker. | QE-POR-13
- Question : les webhooks de paiement font-ils partie de ces tâches ?
  - NON DÉFINI : Recommandation appliquée : non ; signature, anti-rejeu et réconciliation restent à PH-10 et ne sont pas dans BE-100 à BE-119. | QE-POR-14
- Question : quelle est la durée de validité et la rétention des exports et liens ?
  - NON DÉFINI : Recommandation appliquée : la durée est lue dans une configuration explicite ; sans valeur, aucun lien n'est émis. | QE-POR-15
- Question : quelles actions exigent une réauthentification, et dans quel délai ?
  - NON DÉFINI : Recommandation appliquée : réauthentification exigée pour changement d'abonnement, moyen de paiement et fermeture ; le délai est lu dans la configuration PH-08. | QE-POR-16
- Question : quelles sont les conditions et la conservation d'une fermeture, et qui signe ?
  - NON DÉFINI : Recommandation appliquée : refus de fermeture si abonnement actif ou facture ouverte (409) ; signataire = Owner ; durée de conservation absente, aucune valeur inventée. | QE-POR-17
- Question : quels champs du profil organisation sont modifiables ?
  - NON DÉFINI : Recommandation appliquée : PATCH n'accepte que les champs listés par PH-07 ; à défaut, tout champ est refusé en 400. | QE-POR-18
- Question : quels champs des documents financiers sont visibles, et quelle expurgation par rôle ?
  - NON DÉFINI : Recommandation appliquée : seuls les champs listés dans la matrice (référence, dates, total et devise, état, document lié) sont renvoyés ; adresse et identifiant fiscal sont expurgés sans permission dédiée. | QE-POR-19
- Question : quel en-tête d'idempotence et quels codes de conflit de version ?
  - NON DÉFINI : Recommandation appliquée : en-tête `Idempotency-Key` ; rejeu identique retourne le résultat initial ; même clé avec corps différent retourne 409 ; conflit de version retourne 409. | QE-POR-20
- Question : quel est le schéma des événements et des entrées d'audit (PH-13) ?
  - NON DÉFINI : Recommandation appliquée : émettre les noms d'événements listés dans la matrice, via outbox, sans secret ; le schéma est figé en PH-13 avant livraison. | QE-POR-21
- Question : que se passe-t-il pour le dernier Owner et pour l'impact sur les sièges ?
  - NON DÉFINI : Recommandation appliquée : retrait ou rétrogradation du dernier Owner retourne 409 ; l'impact sur les sièges est renvoyé avant/après sans blocage. | QE-POR-22
- Question : quels sont les noms de champs et les statuts des entitlements, des abonnements et des factures (inclus/add-on) ?
  - NON DÉFINI : Recommandation appliquée : lire les valeurs telles que fournies par PH-09/10 sans enum inventé ; les statuts absents sont renvoyés tels quels. | QE-POR-23
- Question : quel est le destinataire d'une invitation et quelle identité peut l'accepter ?
  - NON DÉFINI : Recommandation appliquée : le destinataire est l'identifiant de l'identité invitée ; seule cette identité accepte, sinon 403. | QE-POR-24
- Question : les notifications (canal, période de grâce, préférences) relèvent-elles de ces tâches ?
  - NON DÉFINI : Recommandation appliquée : aucune notification n'est envoyée par BE-100 à BE-119 ; seuls les événements listés sont émis. | QE-POR-25
- Question : BE-100 crée les tables `organization` et `membership`, déjà prévues par BE-002 (organisation) et BE-004 (appartenance, table `organizationUser` dans le code) ; qui en est propriétaire ?
  - NON DÉFINI : Recommandation appliquée : BE-100 dépend de BE-002 et BE-004 et ne crée que `tenant` et `invitation` ; les tables `organization` et `membership` restent celles de BE-002 et BE-004, leurs contraintes y étant ajoutées. | QE-POR-26
- Question : BE-101 et BE-009 traitent toutes deux la garde de portée organisation ; laquelle porte la règle générique ?
  - NON DÉFINI : Recommandation appliquée : BE-009 porte la garde générique ; BE-101 dépend de BE-009 et ne garde que les règles propres au portail (404 anti-énumération, refus par défaut sur la politique portail). | QE-POR-27
- Question : quel objet porte les snapshots d'usage (`UsageSnapshot`, PH-09) ? Aucune tâche de la liste ne porte ce nom.
  - NON DÉFINI : Recommandation appliquée : BE-108 garde l'événement `UsageSnapshotPublished` en dépendance externe non résolue ; BE-253 (limites d'usage) n'est pas retenue sans décision. | QE-POR-28
- Question : les tables `checkout_session`, `order`, `payment_attempt` et `subscription` citées par BE-110, BE-111 et BE-112 sont aussi prévues par BE-202, BE-206 et BE-023 (`subscription`) ; qui les crée ?
  - NON DÉFINI : Recommandation appliquée : les tables de facturation sont créées par leur propriétaire (BE-202, BE-206 ; table `subscription` de BE-023) ; le portail ne fait que les lire et n'ajoute aucune migration sur ces tables. | QE-POR-29
- Question : la casse des noms de tables suit-elle la convention camelCase du CLAUDE.md du backend ?
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-POR-30
- Question : quelle casse appliquer aux noms de tables (décision du coordinateur du 2026-11-03) ?
  - NON DÉFINI : Recommandation appliquée : snake_case partout pour les tables ; `organizationUser` renommé `organization_user` dans BE-100 (ligne « Tables / migrations » de la table `membership`) ; les autres tables sont déjà en snake_case ; les colonnes restent camelCase ; aucune route de console opérateur dans ce fichier, donc aucun renommage de route. Le nom `organizationUser` gardé dans la question ci-dessus décrit le code existant et n'est pas renommé. | QE-POR-30
