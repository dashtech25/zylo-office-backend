# Tâches back-end : paramètres, intégrations, notifications et audit

- **Domaine** : Socle Zylo Office — paramètres, intégrations, notifications, événements et audit (back-end uniquement)
- **Sources lues** :
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-13-parametres-integrations-notifications-audit.md`
  - `definition-travail/00-pilotage/architecture-fondation/catalogue-evenements-et-contrats-notification.md`
- **Plage d'identifiants** : BE-150 à BE-176 (27 tâches, sans trou, dans l'ordre de dépendance)
- **Convention** : les valeurs absentes des sources sont marquées « NON DÉFINI » suivies de la recommandation appliquée et de l'identifiant QE-PAR-nn de la section « Points ouverts ». Les routes proposées sont des recommandations, non des faits.
- **Statut** : planification uniquement. Aucun code écrit, aucun test lancé, aucun build.

## 1. Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-150 | Enveloppe d'événement commune | 0 | BE-002, BE-005, BE-008, BE-009 |
| BE-151 | Catalogue des codes d'erreur et format de reprise | 0 | BE-001, BE-150 |
| BE-152 | Modèle du journal d'audit append-only | 0 | BE-007, BE-150 |
| BE-153 | Service d'écriture d'audit fail-closed | 0 | BE-007, BE-151, BE-152 |
| BE-154 | Modèle des paramètres par portée et versions | 0 | BE-002, BE-153 |
| BE-155 | Déclaration et validation des paramètres | 0 | BE-154 |
| BE-156 | Résolution d'héritage et de priorité des paramètres | 0 | BE-154, BE-155 |
| BE-157 | Application, défaut, restauration et version atomique | 0 | BE-153, BE-156 |
| BE-158 | Routes API des paramètres | 3 | BE-157 |
| BE-159 | Approbation des changements de paramètres | 2 | BE-158 |
| BE-160 | Registre des connecteurs et de leurs états | 0 | BE-153 |
| BE-161 | Stockage séparé des secrets d'intégration | 0 | BE-160 |
| BE-162 | Routes API des connecteurs | 4 | BE-160, BE-161 |
| BE-163 | Webhook entrant : signature, tenant et idempotence | 1 | BE-162, BE-150, BE-151 |
| BE-164 | Journal des tentatives d'intégration et backoff | 1 | BE-160, BE-153 |
| BE-165 | File de lettres mortes et reprise manuelle tracée | 2 | BE-164 |
| BE-166 | Publication par outbox et consommation idempotente | 0 | BE-150, BE-153 |
| BE-167 | Catégories et audiences de notification | 0 | BE-166 |
| BE-168 | Préférences et consentement par catégorie | 2 | BE-167 |
| BE-169 | Moteur de notification : audience, déduplication, suppression | 0 | BE-167, BE-168, BE-226 |
| BE-170 | Adaptateur de canal et résultat de livraison | 0 | BE-169 |
| BE-171 | Routes API de consultation des notifications | 2 | BE-169, BE-170 |
| BE-172 | Routes API de consultation du journal d'audit | 2 | BE-007, BE-152, BE-153 |
| BE-173 | Export d'audit en job traçable et rétention | 2 | BE-172 |
| BE-174 | Classification et minimisation des données sensibles | 0 | BE-007, BE-150, BE-166, BE-153 |
| BE-175 | Preuve de sauvegarde et de restauration | 0 | BE-007, BE-154, BE-152 |
| BE-176 | Schémas d'événements versionnés et tests transverses d'isolation tenant | 1 | BE-001, BE-008, BE-009, BE-150, BE-151, BE-166, BE-174, BE-175, BE-158 à BE-173 (routes rejouées, CA-4), BE-223, BE-226 |

## 2. Tâches

### BE-150 — Enveloppe d'événement commune
- Domaine : Événements
- Vague : 6
- Routes : aucune
- Tables / migrations : aucune (contrat de schéma partagé ; persistance dans BE-166)
- Droits : aucun droit propre (contrat interne). NON DÉFINI pour la portée de publication : recommandation appliquée = seul un émetteur authentifié publie, refus `403` PERMISSION_DENIED (QE-PAR-01)
- Dépendances : BE-005 (authentification de l'émetteur), BE-002 (organisation racine, `tenantId`), BE-008 (modèle des permissions de publication), BE-009 (garde de contexte : dérivation de `tenantId` et contrôle d'autorisation)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : une enveloppe valide contient `eventId`, `eventType`, `schemaVersion`, `occurredAt` (UTC), `tenantId`, `scope`, `actor`, `subject`, `dataClassification`, `correlationId`, `causationId`, `payload`.
  - CA-2 : une enveloppe sans `tenantId` ou sans `eventId` est rejetée avec le code `SCHEMA_INVALID`.
  - CA-3 : deux publications de même `eventId` produisent un seul événement logique (test de déduplication).
  - CA-4 (isolation tenant) : `tenantId` est dérivé de l'identité authentifiée ; un `tenantId` fourni dans le payload et différent de l'identité renvoie `TENANT_MISMATCH` et n'est pas persisté.
  - CA-5 (refus) : un `payload` contenant une clé marquée secret est rejeté avec `SCHEMA_INVALID` et n'apparaît dans aucune trace.
- Documentation attendue : docstrings de chaque champ de l'enveloppe et de la fonction de validation ; doc de module à `app/evenements/enveloppe.md` (chemin prévu, NON DÉFINI : recommandation QE-PAR-13).
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas ; catalogue-evenements-et-contrats-notification.md#Enveloppe conceptuelle commune
- Code existant (develop) : app/shared/events.py (registre en mémoire `subscribe(event_name, handler)` et `publish(event_name, **payload)`, sans enveloppe, sans validation ni `tenantId` ; utilisé par app/location) ; garder : `subscribe` et `publish` comme transport intra-processus jusqu'à BE-166 ; casser : `publish` qui accepte des arguments libres, remplacé par la publication d'une enveloppe validée

### BE-151 — Catalogue des codes d'erreur et format de reprise
- Domaine : Erreurs et reprise
- Vague : 7
- Routes : aucune
- Tables / migrations : aucune
- Droits : aucun droit propre. Mapping HTTP NON DÉFINI : recommandation appliquée = `403` PERMISSION_DENIED, `404` TENANT_MISMATCH (objet hors tenant non révélé), `409` VERSION_CONFLICT, `422` SCHEMA_INVALID, `429` RATE_LIMITED, `503` CHANNEL_UNAVAILABLE et REMOTE_UNAVAILABLE (QE-PAR-01)
- Enveloppe d'erreur : réutilise celle de BE-001 (`{"error": {...}}`, `request_id`) ; ne la redéfinit pas. Le « format de reprise » de CA-2 est un résultat distinct, non une réponse d'erreur.
- Dépendances : BE-001 (enveloppe d'erreur, propriétaire unique), BE-150
- Critères d'acceptation :
  - CA-1 : les 12 codes `SCHEMA_INVALID`, `TENANT_MISMATCH`, `PERMISSION_DENIED`, `SIGNATURE_INVALID`, `REPLAY_DUPLICATE`, `CONSENT_SUPPRESSED`, `CHANNEL_UNAVAILABLE`, `REMOTE_UNAVAILABLE`, `RATE_LIMITED`, `SECRET_EXPIRED`, `VERSION_CONFLICT`, `AUDIT_WRITE_FAILED` existent et sont stables (test de non-régression sur la liste).
  - CA-2 : un résultat de reprise contient code, classification temporaire ou permanente, corrélation, horodatage, action permise, permission et issue idempotente ; un champ manquant fait échouer le test.
  - CA-3 (refus) : un texte détaillé ou un secret est expurgé de la réponse d'erreur (test sur un message contenant une valeur secrète factice).
  - CA-4 : un code hors liste est rejeté à la construction de l'erreur.
- Documentation attendue : docstring de chaque code avec sa classification ; doc de module `app/core/erreurs/codes.md` (NON DÉFINI, QE-PAR-13).
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas ; catalogue-evenements-et-contrats-notification.md#Erreurs et reprise communes
- Code existant (develop) : app/core/errors.py (classe `AppError(code, message, status_code, details, headers, field_errors)` et enveloppe `{"error": {code, message, field_errors, details}, request_id}`, propriété de BE-001) ; aucun catalogue de codes : `code` est une chaîne libre (ex. `validation_error` dans app/core/errors.py, `webhook_eventId_missing` dans app/billing/router.py) ; garder : `AppError` et l'enveloppe ; casser : codes libres non catalogués, à ramener au catalogue ou rejetés (CA-4)

### BE-152 — Modèle du journal d'audit append-only
- Domaine : Audit
- Vague : 7
- Routes : aucune
- Tables / migrations : aucune table créée ; réutilise la table `audit_event` de BE-007 (migration de `audit_log`) ; colonnes clés attendues : `id`, `eventId` (unique), `tenantId` (nullable pour événements globaux, NON DÉFINI : QE-PAR-19), `actor` (humain, service ou système, identité technique distincte), `targetType`, `targetId`, `action`, `reason` (motif), `occurredAt` (UTC), `result`, `correlationId`, `visibility`, `dataClassification`. Aucune mise à jour ni suppression autorisée (contrainte ou rôle base, NON DÉFINI : QE-PAR-07). Noms des colonnes : ceux de `audit_event` (BE-007) quand ils existent ; colonnes ajoutées seulement si absentes. NON DÉFINI : Recommandation appliquée : noms de BE-007 retenus, sinon les noms listés ici | QE-PAR-26
- Droits : aucun droit d'écriture direct exposé. Lecture gouvernée par BE-172
- Dépendances : BE-007 (table `audit_event`), BE-150
- Critères d'acceptation :
  - CA-1 : la migration ajoute à `audit_event` les colonnes clés absentes et l'unicité de `eventId` ; aucune seconde table d'audit n'est créée.
  - CA-2 : un UPDATE et un DELETE sur `audit_event` échouent (test sur la base de test jetable `zylo_t<NNN>_test`).
  - CA-3 : une ligne sans acteur, cible, action ou corrélation est refusée.
  - CA-4 (isolation tenant) : une ligne d'un tenant A n'est pas visible par une requête scopée au tenant B (test de requête directe).
- Documentation attendue : docstring de la classe modèle et des colonnes ; doc de module `app/audit/modele.md` (NON DÉFINI, QE-PAR-13).
- Source : PH-13-parametres-integrations-notifications-audit.md#Critères d'acceptation ; catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-AUD-01)
- Code existant (develop) : app/audit/models.py, classe `AuditLog`, table `auditLog` (colonnes camelCase `organizationId`, `actorUserId`, `action`, `entityType`, `entityId`, `scopeResourceType`, `scopeResourceId`, `summary`, `changes`, `ipAddress`, `userAgent`, `createdAt`) ; app/audit/service.py `record_audit_event` (flush sans commit, dans la transaction de l'appelant) ; app/operator/audit_models.py `OperatorAuditLog` (table `operatorAuditLog`, hors périmètre de BE-152) ; garder : `record_audit_event` sans commit propre ; casser : table `auditLog` et colonnes camelCase, renommées par BE-007 ; à ajouter : unicité de `eventId` et interdiction de UPDATE/DELETE

### BE-153 — Service d'écriture d'audit fail-closed
- Domaine : Audit
- Vague : 8
- Routes : aucune
- Tables / migrations : aucune nouvelle (écrit dans `audit_event`, BE-152)
- Droits : écriture réservée au service métier émetteur authentifié ; refus `403` PERMISSION_DENIED si l'émetteur n'est pas authentifié (NON DÉFINI, QE-PAR-01)
- Dépendances : BE-007 (table `audit_event`, propriétaire), BE-151, BE-152
- Critères d'acceptation :
  - CA-1 : une mutation sensible et son événement d'audit sont écrits dans la même transaction ; si l'écriture d'audit échoue, la mutation est annulée et le code `AUDIT_WRITE_FAILED` est renvoyé (test par injection d'erreur).
  - CA-2 : une lecture non sensible reste tolérante à l'échec d'audit (décision de tolérance NON DÉFINI, QE-PAR-05 ; test du comportement recommandé).
  - CA-3 (refus) : un appel sans identité authentifiée est refusé `403` et n'écrit aucune ligne.
  - CA-4 (isolation tenant) : l'écriture avec un `tenantId` différent de celui de l'identité est refusée `TENANT_MISMATCH` et n'écrit rien.
- Documentation attendue : docstrings de la fonction d'écriture et de ses paramètres ; doc de module `app/audit/ecriture.md` (NON DÉFINI, QE-PAR-13).
- Source : catalogue-evenements-et-contrats-notification.md#Flux transactionnel recommandé ; #Erreurs et reprise communes (politique fail-closed)

### BE-154 — Modèle des paramètres par portée et versions
- Domaine : Paramètres
- Vague : 9
- Routes : aucune
- Tables / migrations : table `setting_definition` (`key`, `scopeKind` parmi plateforme, organisation, module, utilisateur, `owner`, `valueType`, `defaultValue` NON DÉFINI : QE-PAR-03, `sensitive` booléen NON DÉFINI : QE-PAR-12) ; table `setting_value` (`id`, `definitionKey`, `scopeKind`, `scopeId` (tenant/organisation ou utilisateur), `version` entier, `value`, `applied`, `createdBy`, `createdAt`, `reason`) ; contrainte d'unicité `(definitionKey, scopeKind, scopeId, version)`
- Droits : lecture selon BE-158 ; écriture selon BE-157/BE-159
- Dépendances : BE-153, BE-002
- Critères d'acceptation :
  - CA-1 : la migration crée les deux tables et l'unicité par version.
  - CA-2 : deux écritures concurrentes sur la même version produisent un conflit `VERSION_CONFLICT` pour la seconde.
  - CA-3 : chaque ligne de `setting_value` a un `createdBy` et un `reason` non vides.
  - CA-4 (isolation tenant) : une valeur de l'organisation A n'est jamais lue par une requête de l'organisation B (test sur deux tenants).
- Documentation attendue : docstrings des modèles et des portées ; doc de module `app/parametres/modele.md` (NON DÉFINI, QE-PAR-13).
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étapes 1-2) ; #Recommandations approuvées (inventaire par capacité)

### BE-155 — Déclaration et validation des paramètres
- Domaine : Paramètres
- Vague : 10
- Routes : aucune
- Tables / migrations : aucune nouvelle (règles de validation portées par `setting_definition`, BE-154)
- Droits : aucun droit propre ; appelé par BE-157
- Dépendances : BE-154
- Critères d'acceptation :
  - CA-1 : chaque paramètre déclaré a une règle de validation (type, bornes ou énumération) ; un paramètre sans règle fait échouer le test de cohérence du registre.
  - CA-2 : une valeur hors règle est rejetée `422` SCHEMA_INVALID (code HTTP NON DÉFINI, QE-PAR-01).
  - CA-3 : chaque paramètre déclare son effet (immédiat, au prochain cycle ou redémarrage : NON DÉFINI, QE-PAR-04) ; un paramètre sans effet déclaré fait échouer le test.
  - CA-4 (refus) : un paramètre absent du registre est rejeté `422` SCHEMA_INVALID et n'est pas créé.
- Documentation attendue : docstring de chaque règle de validation ; doc de module `app/parametres/validation.md`.
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 1 : validation et effet)

### BE-156 — Résolution d'héritage et de priorité des paramètres
- Domaine : Paramètres
- Vague : 11
- Routes : aucune
- Tables / migrations : aucune
- Droits : aucun droit propre (service de résolution) ; l'appelant doit avoir la permission de lecture du scope (BE-158)
- Dépendances : BE-154, BE-155
- Critères d'acceptation :
  - CA-1 : la valeur résolue suit l'ordre de priorité recommandé utilisateur > module > organisation > plateforme > défaut (ordre NON DÉFINI, QE-PAR-06) ; test sur quatre niveaux renseignés.
  - CA-2 : sans valeur à aucun niveau, la valeur par défaut déclarée est renvoyée ; sans défaut, la résolution renvoie « absent » (pas d'invention de valeur).
  - CA-3 : un conflit déclaré (deux niveaux incompatibles) est signalé et non résolu silencieusement (test).
  - CA-4 (isolation tenant) : la résolution pour l'organisation A n'utilise jamais une valeur de l'organisation B.
- Documentation attendue : docstring de la fonction de résolution décrivant l'ordre ; doc de module `app/parametres/resolution.md`.
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 2 : héritage, priorité, conflit)

### BE-157 — Application, défaut, restauration et version atomique
- Domaine : Paramètres
- Vague : 12
- Routes : aucune
- Tables / migrations : aucune nouvelle (écriture de `setting_value`, BE-154)
- Droits : application réservée à un rôle d'administration du scope (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED ; hors tenant `404` TENANT_MISMATCH
- Dépendances : BE-153, BE-156
- Critères d'acceptation :
  - CA-1 : une modification crée une nouvelle version et journalise un événement `EVT-SET-01` (clé, version, scope, clés modifiées, diff expurgé) dans la même transaction (BE-153).
  - CA-2 : si l'application échoue, la version précédente reste active et aucune version partielle n'est persistée.
  - CA-3 : restaurer une version antérieure crée une nouvelle version (pas de réécriture) et journalise l'action.
  - CA-4 (refus) : un utilisateur sans permission d'écriture reçoit `403` et aucune version n'est créée.
  - CA-5 (isolation tenant) : une restauration sur le tenant A ne modifie aucune ligne du tenant B.
- Documentation attendue : docstrings des fonctions d'application et de restauration ; doc de module `app/parametres/application.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-SET-01) ; PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 2 : défaut, restauration)

### BE-158 — Routes API des paramètres
- Domaine : Paramètres
- Vague : 13
- Routes :
  - `GET /api/v1/parametres/{scope_kind}/{scope_id}` (NON DÉFINI : recommandation appliquée, QE-PAR-02) : liste des paramètres résolus du scope
  - `PUT /api/v1/parametres/{scope_kind}/{scope_id}/{cle}` (NON DÉFINI, QE-PAR-02) : nouvelle valeur, `reason` obligatoire, en-tête de version attendue
  - `POST /api/v1/parametres/{scope_kind}/{scope_id}/{cle}/restaurations` (NON DÉFINI, QE-PAR-02) : restauration d'une version antérieure
- Tables / migrations : aucune
- Droits : lecture `settings.read` (cité par la source, portée au scope) ; écriture `settings.write` (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED ; scope hors tenant `404` ; version attendue incorrecte `409` VERSION_CONFLICT
- Dépendances : BE-157
- Critères d'acceptation :
  - CA-1 : `GET` renvoie la valeur résolue, sa source de niveau et sa version pour un scope autorisé.
  - CA-2 : `PUT` avec une valeur valide renvoie `200` et la nouvelle version ; `PUT` sans `reason` renvoie `422`.
  - CA-3 : `PUT` avec une version attendue périmée renvoie `409` VERSION_CONFLICT et ne modifie rien.
  - CA-4 (refus) : `PUT` par un utilisateur sans `settings.write` renvoie `403` ; `GET` sans `settings.read` renvoie `403`.
  - CA-5 (isolation tenant) : `GET /api/v1/parametres/organisation/{id}` avec un `id` d'un autre tenant renvoie `404` et ne révèle pas l'existence du scope.
- Documentation attendue : docstring de chaque handler (paramètres, codes de retour) ; doc de route `app/parametres/routes.md` ; contrat OpenAPI à produire (chemin NON DÉFINI, QE-PAR-13).
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-SET-01, permission settings.read) ; PH-13-parametres-integrations-notifications-audit.md#Acteurs

### BE-159 — Approbation des changements de paramètres
- Domaine : Paramètres
- Vague : 14
- Routes :
  - `POST /api/v1/approbations/{demande_id}/decisions` (NON DÉFINI, QE-PAR-02) : approuver ou rejeter une demande
  - `GET /api/v1/approbations/{demande_id}` (NON DÉFINI, QE-PAR-02) : lire une demande et son statut
- Tables / migrations : table `approbation_parametre` (`id`, `settingKey`, `scopeKind`, `scopeId`, `valeurProposee`, `demandeur`, `approbateur`, `statut` parmi en_attente, approuvé, rejeté, `motif`, `createdAt`, `decidedAt`) ; décision NON DÉFINI si proposeur et approbateur doivent différer (QE-PAR-06)
- Droits : décision `settings.approve` (NON DÉFINI, QE-PAR-03) ; approbateur distinct du demandeur recommandé, refus `403` PERMISSION_DENIED ; décision sur demande déjà tranchée `409` VERSION_CONFLICT (statut en conflit refusé)
- Dépendances : BE-158
- Critères d'acceptation :
  - CA-1 : un changement marqué sensible crée une demande en attente et ne modifie pas la valeur active.
  - CA-2 : une approbation applique la valeur et journalise `EVT-SET-02` avec demande, approbateur et motif.
  - CA-3 (refus) : une décision par le demandeur lui-même est refusée `403` (règle recommandée, QE-PAR-06) ; une décision sans `settings.approve` est refusée `403`.
  - CA-4 : une seconde décision sur une demande déjà approuvée ou rejetée renvoie `409` et n'écrit rien.
  - CA-5 (isolation tenant) : un approbateur du tenant A ne peut pas décider une demande du tenant B (`404`).
- Documentation attendue : docstrings du cycle de vie de la demande ; doc de module `app/parametres/approbation.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-SET-02) ; PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 2 : approbation)

### BE-160 — Registre des connecteurs et de leurs états
- Domaine : Intégrations
- Vague : 9
- Routes : aucune (exposées par BE-162)
- Tables / migrations : table `connecteur` (`id`, `portee` parmi tenant ou global (NON DÉFINI : QE-PAR-19), `tenantId` nullable, `nom`, `etat` parmi création, activé, suspendu, révoqué, `versionConfiguration`, `createdAt`, `updatedAt`) ; transitions d'état autorisées NON DÉFINI (QE-PAR-08 ou recommandation ci-dessous)
- Droits : aucun droit propre (service) ; l'appel passe par BE-162
- Dépendances : BE-153
- Critères d'acceptation :
  - CA-1 : chaque changement d'état (création, activation, suspension, révocation) écrit une ligne d'audit `EVT-INT-01`.
  - CA-2 : une transition interdite (par exemple révoqué vers activé) est refusée `409` et n'écrit rien (table des transitions recommandée, à valider).
  - CA-3 : une reprise de configuration n'est possible que si la configuration est validée ; sinon la reprise est refusée.
  - CA-4 (isolation tenant) : un connecteur de portée tenant A n'est jamais listé pour le tenant B ; un connecteur global n'est modifiable que par l'administration plateforme (test de refus pour un admin tenant).
- Documentation attendue : docstrings de la machine d'états ; doc de module `app/integrations/registre.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-INT-01) ; PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (contrats neutres)

### BE-161 — Stockage séparé des secrets d'intégration
- Domaine : Intégrations / Sécurité
- Vague : 10
- Routes : aucune
- Tables / migrations : table `secret_integration` (`id`, `connecteurId`, `referenceSecret`, `version`, `expireAt` NON DÉFINI (QE-PAR-09), `createdAt`) ; la valeur n'est jamais dans une colonne lisible hors coffre (mécanisme NON DÉFINI : QE-PAR-10)
- Droits : aucune lecture de valeur par API ; accès technique réservé au service d'intégration ; refus `403` PERMISSION_DENIED
- Dépendances : BE-160
- Critères d'acceptation :
  - CA-1 : un secret n'apparaît dans aucune réponse API, aucun événement, aucun journal (test de recherche de la valeur factice dans toutes les sorties).
  - CA-2 : un secret expiré provoque `SECRET_EXPIRED` et suspend les envois du connecteur concerné.
  - CA-3 (refus) : une tentative de lecture de valeur par un utilisateur, même administrateur, renvoie `403`.
  - CA-4 (isolation tenant) : un secret du connecteur du tenant A n'est jamais résolu pour un appel du tenant B.
- Documentation attendue : docstrings de l'accès au secret ; doc de module `app/integrations/secrets.md`.
- Source : PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 7 : séparation des secrets) ; catalogue-evenements-et-contrats-notification.md#Erreurs et reprise communes (SECRET_EXPIRED)

### BE-162 — Routes API des connecteurs
- Domaine : Intégrations
- Vague : 11
- Routes :
  - `GET /api/v1/connecteurs` (NON DÉFINI, QE-PAR-02) : liste des connecteurs du scope
  - `POST /api/v1/connecteurs` (NON DÉFINI, QE-PAR-02) : création en état création
  - `POST /api/v1/connecteurs/{id}/transitions` (NON DÉFINI, QE-PAR-02) : activer, suspendre, révoquer
  - `PUT /api/v1/connecteurs/{id}/configuration` (NON DÉFINI, QE-PAR-02) : configuration validée
- Tables / migrations : aucune (`connecteur` BE-160)
- Droits : lecture `integrations.read` ; écriture `integrations.manage` (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED ; hors tenant `404`
- Dépendances : BE-160, BE-161
- Critères d'acceptation :
  - CA-1 : `POST` crée un connecteur en état création et renvoie `201`.
  - CA-2 : `POST .../transitions` valide renvoie `200` ; transition interdite renvoie `409`.
  - CA-3 (refus) : `POST` sans `integrations.manage` renvoie `403` et ne crée rien.
  - CA-4 : la réponse `GET` ne contient aucun champ de secret (test sur la forme de réponse).
  - CA-5 (isolation tenant) : `GET /api/v1/connecteurs` pour le tenant A n'expose aucun connecteur du tenant B.
- Documentation attendue : docstrings des handlers ; doc de route `app/integrations/routes.md`.
- Source : PH-13-parametres-integrations-notifications-audit.md#Acteurs ; catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-INT-01)

### BE-163 — Webhook entrant : signature, tenant et idempotence
- Domaine : Intégrations
- Vague : 12
- Routes :
  - `POST /api/v1/integrations/webhooks/{connecteur_id}` (NON DÉFINI, QE-PAR-02) : réception d'un événement externe
- Tables / migrations : table `webhook_recu` (`id`, `connecteurId`, `idExterne` unique par connecteur, `tenantId`, `payloadMinimal`, `recuAt`, `statut`) ; index d'unicité `(connecteurId, idExterne)`
- Droits : credential scopé au connecteur avec permission d'écriture explicite (NON DÉFINI, QE-PAR-11) ; signature invalide `401` SIGNATURE_INVALID (code HTTP NON DÉFINI, QE-PAR-01) ; tenant incohérent `404` TENANT_MISMATCH
- Dépendances : BE-162, BE-150, BE-151
- Critères d'acceptation :
  - CA-1 : un webhook à signature valide et schéma valide renvoie `202` et crée une ligne `webhook_recu`.
  - CA-2 : un doublon d'`idExterne` renvoie `200` avec `REPLAY_DUPLICATE` et ne crée pas de seconde ligne.
  - CA-3 (refus) : une signature invalide renvoie `401` SIGNATURE_INVALID et n'écrit rien ; un schéma invalide renvoie `422` SCHEMA_INVALID.
  - CA-4 : un webhook hors fenêtre anti-rejeu est rejeté `REPLAY_DUPLICATE` (fenêtre NON DÉFINI, QE-PAR-09).
  - CA-5 (isolation tenant) : un webhook signé pour le connecteur du tenant A mais adressant le tenant B est refusé `TENANT_MISMATCH` (`404`).
- Documentation attendue : docstrings de la vérification de signature et de l'idempotence ; doc de route `app/integrations/webhooks.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-INT-02)

### BE-164 — Journal des tentatives d'intégration et backoff
- Domaine : Intégrations / Opérations
- Vague : 10
- Routes : aucune
- Tables / migrations : table `tentative_integration` (`id`, `connecteurId`, `correlationId`, `eventId`, `issue` parmi succes, echec, `codeErreur`, `dureeMs`, `tentativeNo`, `prochaineTentativeAt`, `tenantId`) ; aucune colonne de contenu sensible
- Droits : lecture des métadonnées par l'opérateur (`integrations.read`) ; contenu restreint (NON DÉFINI, QE-PAR-16) ; refus `403` PERMISSION_DENIED
- Dépendances : BE-160, BE-153
- Critères d'acceptation :
  - CA-1 : chaque tentative écrit une ligne avec code, durée mesurée et corrélation, sans payload.
  - CA-2 : un échec transitoire planifie une nouvelle tentative avec backoff croissant ; le délai de base et le plafond sont NON DÉFINI (QE-PAR-09) et lus de la configuration.
  - CA-3 : une même clé d'effet exécutée deux fois produit un seul effet (test d'idempotence).
  - CA-4 (refus) : un opérateur sans `integrations.read` ne voit aucune tentative (`403`).
  - CA-5 (isolation tenant) : les tentatives du tenant A ne sont pas listées pour le tenant B.
- Documentation attendue : docstrings de la politique de backoff ; doc de module `app/integrations/tentatives.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-INT-03)

### BE-165 — File de lettres mortes et reprise manuelle tracée
- Domaine : Intégrations / Opérations
- Vague : 11
- Routes :
  - `GET /api/v1/integrations/lettres-mortes` (NON DÉFINI, QE-PAR-02) : liste des échecs définitifs
  - `POST /api/v1/integrations/lettres-mortes/{id}/reprises` (NON DÉFINI, QE-PAR-02) : reprise manuelle avec motif
- Tables / migrations : table `lettre_morte` (`id`, `tentativeId`, `originalId`, `motif`, `operateur`, `reprisAt`, `tenantId`) ; durée de rétention NON DÉFINI (QE-PAR-17)
- Droits : lecture `integrations.read` ; reprise `integrations.manage` (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED ; hors tenant `404`
- Dépendances : BE-164
- Critères d'acceptation :
  - CA-1 : un échec définitif après épuisement des tentatives est déplacé en lettre morte.
  - CA-2 : une reprise sans motif renvoie `422` ; avec motif, elle écrit `operateur`, `motif` et `originalId` et journalise l'action.
  - CA-3 (refus) : une reprise sans `integrations.manage` renvoie `403` et ne relance rien.
  - CA-4 : une reprise rejouée sur une lettre déjà reprise ne renvoie pas d'effet en double (`REPLAY_DUPLICATE`).
  - CA-5 (isolation tenant) : un opérateur du tenant A ne peut pas reprendre une lettre du tenant B (`404`).
- Documentation attendue : docstrings de la reprise ; doc de route `app/integrations/lettres-mortes.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Erreurs et reprise communes ; #Matrice candidat (EVT-INT-03 : DLQ, redrive)

### BE-166 — Publication par outbox et consommation idempotente
- Domaine : Événements
- Vague : 9
- Routes : aucune
- Tables / migrations : table `outbox_evenement` (`id`, `eventId` unique, `eventType`, `schemaVersion`, `tenantId`, `payload`, `publieAt`, `statut`) ; table `consommation_evenement` (`consommateur`, `eventId`, unique par couple) ; mécanisme de file NON DÉFINI (QE-PAR-10)
- Droits : publication réservée aux émetteurs authentifiés (BE-150) ; `403` PERMISSION_DENIED sinon
- Dépendances : BE-150, BE-153
- Critères d'acceptation :
  - CA-1 : l'événement n'est visible au consommateur qu'après le commit de la transaction métier (test d'injection d'échec avant commit : aucun événement publié).
  - CA-2 : une livraison répétée au même consommateur ne produit qu'un effet (`REPLAY_DUPLICATE` consigné).
  - CA-3 : la publication sans identité émetteur est refusée `403`.
  - CA-4 (isolation tenant) : un consommateur du tenant A ne reçoit jamais un événement du tenant B (test de livraison croisée).
- Documentation attendue : docstrings du publieur et du consommateur ; doc de module `app/evenements/outbox.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Flux transactionnel recommandé ; #Recommandation technique (outbox, au moins une fois)

### BE-167 — Catégories et audiences de notification
- Domaine : Notifications
- Vague : 10
- Routes : aucune
- Tables / migrations : table `categorie_notification` (`code`, `libelle`, `audienceRegle`, `canalDefaut` NON DÉFINI (QE-PAR-04), `actif`) ; table `regle_notification` (`evenementType`, `categorieCode`, `audience` résolue à l'envoi)
- Droits : configuration réservée à l'administration plateforme (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED
- Dépendances : BE-166
- Critères d'acceptation :
  - CA-1 : chaque catégorie déclarée a une audience et un statut actif ; une catégorie sans audience fait échouer le test de cohérence.
  - CA-2 : une règle référence un type d'événement existant dans le catalogue (BE-176) ; une référence inconnue est refusée `422` SCHEMA_INVALID.
  - CA-3 (refus) : la modification d'une règle par un administrateur de tenant renvoie `403`.
  - CA-4 : aucun canal n'est présumé par défaut ; un canal absent renvoie « NON DÉFINI » au lieu d'une valeur (test de la valeur par défaut nulle).
- Documentation attendue : docstrings des catégories et règles ; doc de module `app/notifications/categories.md`.
- Source : PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (catégories, audiences, aucun canal présumé) ; catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-NOT-01)

### BE-168 — Préférences et consentement par catégorie
- Domaine : Notifications
- Vague : 11
- Routes :
  - `GET /api/v1/notifications/preferences` (NON DÉFINI, QE-PAR-02) : préférences de l'utilisateur courant
  - `PUT /api/v1/notifications/preferences/{categorie_code}` (NON DÉFINI, QE-PAR-02) : modifier la préférence d'une catégorie, désinscription incluse
- Tables / migrations : table `preference_notification` (`utilisateurId`, `categorieCode`, `consentement` booléen, `canal` NON DÉFINI (QE-PAR-04), `horodatageConsentement`, `sourceConsentement`) ; unicité `(utilisateurId, categorieCode)`
- Droits : chaque utilisateur gère uniquement ses préférences ; refus `403` PERMISSION_DENIED pour l'accès aux préférences d'un autre utilisateur ; hors tenant `404`
- Dépendances : BE-167
- Critères d'acceptation :
  - CA-1 : `PUT` modifie la préférence et écrit l'horodatage du consentement.
  - CA-2 : après désinscription, un envoi de la catégorie est supprimé avec `CONSENT_SUPPRESSED` (test de bout en bout de la suppression).
  - CA-3 (refus) : `GET` ou `PUT` sur les préférences d'un autre utilisateur renvoie `403`.
  - CA-4 : la plage de silence et les heures calmes ne sont pas implémentées tant que la décision n'est pas prise (test d'absence de valeur par défaut, QE-PAR-14).
  - CA-5 (isolation tenant) : un utilisateur du tenant A ne lit pas les préférences d'un utilisateur du tenant B (`404`).
- Documentation attendue : docstrings des préférences et du consentement ; doc de route `app/notifications/preferences.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Questions de contrat PH-14 (canaux, désinscription, quiet hours) ; PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 4 : préférence)

### BE-169 — Moteur de notification : audience, déduplication, suppression
- Domaine : Notifications
- Vague : 12
- Routes : aucune
- Tables / migrations : table `notification` (`id`, `eventId`, `categorieCode`, `destinataireId`, `statut` parmi en_attente, supprimee, envoyee, echec, `motifSuppression`, `creeAt`) ; unicité `(eventId, categorieCode, destinataireId)`
- Droits : le moteur agit en identité système ; la règle exige que le producteur ait le droit de consulter le sujet (BE-226, moteur d'autorisation unique ; NON DÉFINI : recommandation appliquée, QE-PAR-27) ; refus de création `403` PERMISSION_DENIED
- Dépendances : BE-167, BE-168, BE-226 (droit de consulter le sujet de l'événement)
- Critères d'acceptation :
  - CA-1 : un événement d'origine déclenche une notification par destinataire éligible résolu à l'envoi.
  - CA-2 : un destinataire non éligible ou sans consentement produit un statut `supprimee` avec `CONSENT_SUPPRESSED`.
  - CA-3 (refus) : un producteur sans droit de consultation du sujet ne produit aucune notification (`403`).
  - CA-4 : un même événement rejoué ne crée pas de doublon (contrainte d'unicité testée).
  - CA-5 (isolation tenant) : l'audience est résolue uniquement dans le tenant de l'événement ; un destinataire d'un autre tenant est exclu.
- Documentation attendue : docstrings de la résolution d'audience et de la suppression ; doc de module `app/notifications/moteur.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-NOT-01) ; PH-13-parametres-integrations-notifications-audit.md#Démarche pas à pas (étape 4)

### BE-170 — Adaptateur de canal et résultat de livraison
- Domaine : Notifications
- Vague : 13
- Routes : aucune
- Tables / migrations : table `livraison` (`notificationId`, `canal` NON DÉFINI (QE-PAR-04), `tentativeNo`, `resultat` parmi accepte, livre, retarde, rebond, plainte, echec, `codeErreur`, `prochaineTentativeAt`) ; aucune donnée destinataire au-delà du minimum
- Droits : aucun droit utilisateur ; l'adaptateur ne reçoit que les données minimales ; refus interne `403` si l'adaptateur appelle sans notification éligible
- Dépendances : BE-169
- Critères d'acceptation :
  - CA-1 : un canal non implémenté ou indisponible renvoie `CHANNEL_UNAVAILABLE` (`503`, QE-PAR-01) et déclenche une nouvelle tentative.
  - CA-2 : un rebond permanent ou une plainte arrête les envois vers ce destinataire sur la catégorie (test).
  - CA-3 : un résultat de livraison reçu d'un canal inconnu est rejeté `SCHEMA_INVALID`.
  - CA-4 : aucune adresse de destinataire n'apparaît dans les journaux (test de recherche d'une valeur factice).
- Documentation attendue : docstring de l'interface d'adaptateur et de chaque résultat ; doc de module `app/notifications/canal.md` (interface seule, aucun fournisseur choisi).
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-NOT-02) ; PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (aucun canal présumé)

### BE-171 — Routes API de consultation des notifications
- Domaine : Notifications
- Vague : 14
- Routes :
  - `GET /api/v1/notifications` (NON DÉFINI, QE-PAR-02) : notifications de l'utilisateur courant, filtrables par statut
  - `GET /api/v1/notifications/{id}/livraisons` (NON DÉFINI, QE-PAR-02) : résultats de livraison d'une notification
- Tables / migrations : aucune (lecture de `notification` et `livraison`)
- Droits : chaque utilisateur voit ses notifications ; l'administration voit les livraisons du scope avec `notifications.read` (NON DÉFINI, QE-PAR-03) ; refus `403` PERMISSION_DENIED ; hors tenant ou hors destinataire `404`
- Dépendances : BE-169, BE-170
- Critères d'acceptation :
  - CA-1 : `GET /api/v1/notifications` renvoie uniquement les notifications du destinataire courant.
  - CA-2 : `GET .../livraisons` renvoie les résultats sans adresse de destinataire.
  - CA-3 (refus) : lire les livraisons sans `notifications.read` renvoie `403`.
  - CA-4 : une notification d'un autre destinataire renvoie `404`.
  - CA-5 (isolation tenant) : la liste ne contient aucune notification du tenant B pour un utilisateur du tenant A.
- Documentation attendue : docstrings des handlers ; doc de route `app/notifications/routes.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-NOT-01, EVT-NOT-02)

### BE-172 — Routes API de consultation du journal d'audit
- Domaine : Audit
- Vague : 9
- Routes :
  - `GET /api/v1/audit/evenements` (NON DÉFINI, QE-PAR-02) : recherche par sujet, période, acteur, action ; filtres obligatoires période et sujet (recommandation)
  - `GET /api/v1/audit/evenements/{event_id}` (NON DÉFINI, QE-PAR-02) : détail d'un événement d'audit
- Tables / migrations : aucune (lecture de `audit_event`, BE-152)
- Droits : `audit.read` (cité par la source, portée tenant) ; refus `403` PERMISSION_DENIED ; hors tenant `404`
- Dépendances : BE-007 (table `audit_event`, propriétaire), BE-152, BE-153
- Critères d'acceptation :
  - CA-1 : une recherche sans période renvoie `422` (recommandation QE-PAR-02 ; filtre obligatoire).
  - CA-2 : une recherche valide renvoie les champs acteur, cible, action, motif, temps, résultat, corrélation et visibilité.
  - CA-3 (refus) : une recherche sans `audit.read` renvoie `403` et ne lit rien.
  - CA-4 : la consultation d'un événement de visibilité restreinte exige la permission de visibilité (NON DÉFINI, QE-PAR-16) ; sans elle, `403`.
  - CA-5 (isolation tenant) : un administrateur du tenant A ne voit aucun événement du tenant B (`404` sur identifiant direct).
- Documentation attendue : docstrings des filtres et des réponses ; doc de route `app/audit/routes.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-AUD-02) ; PH-13-parametres-integrations-notifications-audit.md#Critères d'acceptation (4)

### BE-173 — Export d'audit en job traçable et rétention
- Domaine : Audit
- Vague : 10
- Routes :
  - `POST /api/v1/audit/exports` (NON DÉFINI, QE-PAR-02) : demande d'export (sujet, période, motif obligatoire)
  - `GET /api/v1/audit/exports/{job_id}` (NON DÉFINI, QE-PAR-02) : statut et lien de téléchargement temporaire
- Tables / migrations : table `export_audit` (`id`, `demandeur`, `sujet`, `periode`, `motif`, `statut`, `creeAt`, `expireAt` NON DÉFINI (QE-PAR-07), `tenantId`) ; le fichier d'export n'est pas une table
- Droits : `audit.export` (cité par la source) ; refus `403` PERMISSION_DENIED ; hors tenant `404`
- Dépendances : BE-172
- Critères d'acceptation :
  - CA-1 : une demande sans motif renvoie `422` ; avec motif, un job est créé et l'action est journalisée (`EVT-AUD-02`).
  - CA-2 : le téléchargement d'un export expiré renvoie `410` (code HTTP recommandé, QE-PAR-01) ; la durée d'expiration n'est pas fixée et reste une configuration sans valeur par défaut (QE-PAR-07).
  - CA-3 (refus) : une demande sans `audit.export` renvoie `403` et ne crée aucun job.
  - CA-4 : l'export contient uniquement les champs autorisés (aucun secret, aucune adresse de destinataire) (test de contenu).
  - CA-5 (isolation tenant) : le job d'un tenant A n'est pas lisible par le tenant B (`404`).
- Documentation attendue : docstrings du job et de la politique de rétention ; doc de route `app/audit/exports.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Matrice candidat (EVT-AUD-02) ; PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (accès, export, rétention)

### BE-174 — Classification et minimisation des données sensibles
- Domaine : Sécurité des données / Événements
- Vague : 10
- Routes : aucune
- Tables / migrations : colonne `dataClassification` sur `audit_event` (BE-152) et `outbox_evenement` (BE-166) ; table `classification_champ` (`typeEvenement`, `champ`, `classification`, `consommablePar` NON DÉFINI (QE-PAR-16))
- Droits : aucun droit propre ; la classification bloque la sortie vers un consommateur sans droit (`403`)
- Dépendances : BE-007 (table `audit_event`, propriétaire), BE-150, BE-166, BE-153
- Critères d'acceptation :
  - CA-1 : tout champ de payload sans classification déclarée fait échouer la validation (`SCHEMA_INVALID`).
  - CA-2 : les données de paiement sont absentes des payloads et des traces (test de recherche de valeurs factices de numéro de carte).
  - CA-3 (refus) : un consommateur sans droit sur un champ classé ne reçoit pas le champ (`403` ou champ expurgé selon la règle, NON DÉFINI QE-PAR-01).
  - CA-4 (isolation tenant) : la classification n'autorise pas la sortie d'un champ du tenant A vers le tenant B (test croisé).
- Documentation attendue : docstrings de chaque classification ; doc de module `app/securite/classification.md` (NON DÉFINI, QE-PAR-13).
- Source : catalogue-evenements-et-contrats-notification.md#Enveloppe conceptuelle commune (dataClassification, payload) ; PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (minimiser données sensibles, paiement)

### BE-175 — Preuve de sauvegarde et de restauration
- Domaine : Exploitation / Données
- Vague : 10
- Routes : aucune
- Tables / migrations : aucune nouvelle ; la preuve est un jeu de tests de restauration sur les tables `setting_value`, `audit_event` (BE-152, BE-154)
- Droits : aucun droit utilisateur ; l'exécution de la restauration est réservée à l'opérateur plateforme (NON DÉFINI, QE-PAR-03)
- Dépendances : BE-007 (table `audit_event`, propriétaire), BE-154, BE-152
- Critères d'acceptation :
  - CA-1 : une sauvegarde puis une restauration sur base de test jetable reproduisent les paramètres résolus et les versions à l'identique.
  - CA-2 : après restauration, le journal d'audit reste append-only (BE-152 CA-2 rejoué).
  - CA-3 (refus) : une restauration déclenchée sans droit opérateur plateforme est refusée `403`.
  - CA-4 (isolation tenant) : une restauration d'un tenant ne modifie aucune ligne d'un autre tenant (comparaison avant et après).
- Documentation attendue : docstrings de la procédure de test ; doc de module `app/exploitation/restauration.md` (NON DÉFINI, QE-PAR-13). Mécanisme de sauvegarde agnostique (QE-PAR-18).
- Source : PH-13-parametres-integrations-notifications-audit.md#Recommandations approuvées (backup/restore agnostique, preuve de restauration)

### BE-176 — Schémas d'événements versionnés et tests transverses d'isolation tenant
- Domaine : Événements / Qualité transverse
- Vague : 14
- Routes : `GET /api/v1/admin/evenements/types` (NON DÉFINI, QE-PAR-02, QE-PAR-31) : catalogue des types et de leurs versions, pour l'administration plateforme
- Tables / migrations : table `schema_evenement` (`eventType`, `schemaVersion`, `schemaJson`, `compatibleDepuis`, `actif`) ; unicité `(eventType, schemaVersion)`
- Droits : `evenements.read` (NON DÉFINI, QE-PAR-03) limité à l'administration plateforme ; refus `403` PERMISSION_DENIED
- Dépendances : BE-001 (enveloppe d'erreur `{"error": ...}` pour `403` et `422`), BE-008 (permission `evenements.read` au modèle RBAC), BE-009 (garde serveur de la route d'administration plateforme), BE-223 (migration de `schema_evenement`), BE-226 (contrôle de `evenements.read` par le moteur unique), BE-150 (champs `eventType` et `schemaVersion` de l'enveloppe), BE-151 (codes `PERMISSION_DENIED` et `SCHEMA_INVALID`), BE-166, BE-174, BE-175, BE-158 à BE-173 (routes rejouées, CA-4)
- Dépendances externes : BE-001, BE-008, BE-009, BE-223, BE-226 (tâches hors de ce fichier, vérifiées par titre dans `tasks-socle-tenant-identite.md` et `tasks-exploitation-architecture.md`) | QE-PAR-32
- Critères d'acceptation :
  - CA-1 : chaque type d'événement du catalogue a au moins une version de schéma ; un type sans schéma fait échouer le test.
  - CA-2 : une version incompatible (champ requis retiré sans nouvelle version) est refusée à l'enregistrement (règle de compatibilité NON DÉFINI, QE-PAR-08).
  - CA-3 (refus) : `GET /api/v1/admin/evenements/types` sans droit plateforme renvoie `403`.
  - CA-4 (isolation tenant, transverse) : une suite de tests rejoue, sur toutes les routes de BE-158 à BE-173, une requête d'un tenant sur les données d'un autre tenant et exige `404` ou `403` sans fuite d'existence.
- Documentation attendue : docstrings du registre des schémas et de la suite de tests ; doc de module `app/evenements/schemas.md`.
- Source : catalogue-evenements-et-contrats-notification.md#Enveloppe conceptuelle commune (schemaVersion) ; #Questions de contrat PH-14 (versioning)

## Points ouverts

- Question : Quels codes HTTP renvoyer pour refus de droit, objet hors tenant, conflit de version, schéma invalide, limitation de débit et indisponibilité de canal ?
  - NON DÉFINI : Recommandation appliquée : `403` PERMISSION_DENIED, `404` pour objet hors tenant, `409` VERSION_CONFLICT, `422` SCHEMA_INVALID, `429` RATE_LIMITED, `503` CHANNEL_UNAVAILABLE | QE-PAR-01
- Question : Quels chemins et version d'API retenir pour les routes des domaines paramètres, connecteurs, webhooks, notifications, audit et événements ?
  - NON DÉFINI : Recommandation appliquée : préfixe `/api/v1/` (routeur réel : app/main.py) et une ressource par domaine comme indiqué dans chaque tâche | QE-PAR-02
- Question : Quels noms exacts de permissions retenir au-delà de `settings.read` et `audit.read`/`audit.export` cités par la source ?
  - NON DÉFINI : Recommandation appliquée : `settings.write`, `settings.approve`, `integrations.read`, `integrations.manage`, `notifications.read`, `evenements.read`, toutes à portée tenant sauf plateforme explicite | QE-PAR-03
- Question : Quelle est la politique d'approbation (approbateur distinct du demandeur, liste des paramètres sensibles) ?
  - NON DÉFINI : Recommandation appliquée : approbateur distinct du demandeur ; seuls les paramètres marqués `sensitive` passent par approbation | QE-PAR-06
- Question : Quelle est la durée de rétention du journal d'audit et des exports, et quel mécanisme la garantit ?
  - NON DÉFINI : Recommandation appliquée : aucune valeur par défaut dans le code ; la durée est une configuration obligatoire au démarrage, et l'absence de valeur empêche le démarrage (test) | QE-PAR-07
- Question : Quels seuils de retry, de backoff, de fenêtre anti-rejeu et d'expiration de secret retenir ?
  - NON DÉFINI : Recommandation appliquée : toutes les valeurs sont lues de la configuration sans défaut codé ; un test vérifie leur présence | QE-PAR-09
- Question : Quel mécanisme de file ou d'outbox et quel stockage de secret retenir ?
  - NON DÉFINI : Recommandation appliquée : outbox dans la base transactionnelle et secrets dans un coffre désigné par référence, sans technologie imposée | QE-PAR-10
- Question : Quel format de signature des webhooks et quels credentials scopés retenir ?
  - NON DÉFINI : Recommandation appliquée : signature HMAC sur le corps brut avec horodatage, clé par connecteur ; à valider avant implémentation | QE-PAR-11
- Question : Quelle est la liste des paramètres marqués sensibles ?
  - NON DÉFINI : Recommandation appliquée : liste vide au démarrage ; chaque paramètre déclare son drapeau `sensitive` explicitement | QE-PAR-12
- Question : Où placer les modules back-end et leur documentation, la source ne définissant aucun chemin de code ?
  - NON DÉFINI : Recommandation appliquée : un dossier par capacité sous `app/<capacité>/` avec un fichier de documentation de module nommé dans chaque tâche : evenements → `app/evenements/` (à créer) ; erreurs → `app/core/erreurs/` (à créer) ; audit → `app/audit/` ; parametres → `app/parametres/` (à créer) ; integrations → `app/integrations/` ; notifications → `app/notifications/` ; securite → `app/securite/` (à créer) ; exploitation → `app/exploitation/` (à créer) | QE-PAR-13
- Question : Les références croisées de PH-13 (fichiers de plateforme, sources, contrôles, CAP-53) existent-elles et doivent-elles être lues ici ?
  - NON DÉFINI : Recommandation appliquée : les cinq fichiers cités par PH-13 existent dans `definition-travail/` (vérifié en lecture) ; ils ne sont pas lus dans ce lot, qui s'appuie sur les deux sources uniquement | QE-PAR-14
- Question : Le catalogue d'événements est-il marqué BLOCKED ; quels producteurs et événements sont obligatoires ?
  - NON DÉFINI : Recommandation appliquée : seuls les événements EVT-SET-01/02, EVT-INT-01/02/03, EVT-NOT-01/02, EVT-AUD-01/02 sont implémentés ; aucun producteur métier n'est supposé existant | QE-PAR-15
- Question : Quels canaux de notification, locales, plages de silence et règles de désinscription retenir ?
  - NON DÉFINI : Recommandation appliquée : aucun canal ni plage de silence par défaut ; le canal est une configuration de catégorie sans valeur initiale | QE-PAR-04
- Question : Quel est l'effet de chaque paramètre (immédiat, prochain cycle, redémarrage) ?
  - NON DÉFINI : Recommandation appliquée : chaque paramètre déclare son effet à l'enregistrement (BE-155 CA-3) ; aucun effet n'est supposé par défaut | QE-PAR-04 (rattaché)
- Question : Les connecteurs peuvent-ils être globaux ou seulement par tenant ?
  - NON DÉFINI : Recommandation appliquée : portée `tenant` ou `global` explicite ; les connecteurs globaux sont gérés uniquement par l'administration plateforme | QE-PAR-19
- Question : Les tentatives d'intégration et les lettres mortes ont-elles une rétention et un contenu consultable ?
  - NON DÉFINI : Recommandation appliquée : métadonnées seules conservées ; rétention sans valeur initiale, à configurer | QE-PAR-17
- Question : Qui consulte les payloads restreints et selon quelles règles de visibilité par champ ?
  - NON DÉFINI : Recommandation appliquée : aucun consommateur ne voit un champ classé sans permission explicite ; la liste des permissions est à fixer | QE-PAR-16
- Question : Quelle est la politique de tolérance à l'échec d'audit pour les opérations non sensibles ?
  - NON DÉFINI : Recommandation appliquée : fail-closed pour toute mutation sensible, tolérance pour les lectures uniquement | QE-PAR-05
- Question : Quels événements, canaux et garanties de livraison (ordre, rejeu, au moins une fois) sont retenus par événement ?
  - NON DÉFINI : Recommandation appliquée : livraison au moins une fois, consommation idempotente, aucun ordre global ; ordre par entité à décider | QE-PAR-08
- Question : Quel est le format de clé d'idempotence et de `eventType` ?
  - NON DÉFINI : Recommandation appliquée : `eventId` unique généré à la publication ; `eventType` au format `domaine.action` versionné | QE-PAR-20
- Question : Quels champs de la classification de données s'appliquent et quelles valeurs ?
  - NON DÉFINI : Recommandation appliquée : trois niveaux (public, interne, sensible) et une règle par champ de payload ; données de paiement exclues | QE-PAR-21
- Question : Les événements de notification EVT-NOT-01 ont-ils un événement d'origine précis ?
  - NON DÉFINI : Recommandation appliquée : la liste des événements déclencheurs est vide au démarrage et alimentée par les producteurs validés en PH-14 | QE-PAR-22
- Question : Quel est le contenu et la structure des notifications (gabarits, langues) ?
  - NON DÉFINI : Recommandation appliquée : aucun gabarit livré ; la tâche livre le moteur sans contenu rédactionnel | QE-PAR-23
- Question : Quelles exigences de traçabilité du parcours administrateur (lecture de paramètres sensibles) sont à journaliser ?
  - NON DÉFINI : Recommandation appliquée : toute lecture d'un paramètre sensible est journalisée comme action d'audit | QE-PAR-24
- Question : Quels sont les délais et les limites de taille des payloads et des exports ?
  - NON DÉFINI : Recommandation appliquée : limites lues de la configuration sans valeur codée ; test de présence | QE-PAR-25
- Question : Quel est le mécanisme et la fréquence de sauvegarde, et qui en est responsable ?
  - NON DÉFINI : Recommandation appliquée : mécanisme agnostique ; la preuve est un test de restauration sur base jetable (BE-175) ; responsable NON DÉFINI | QE-PAR-18
- Question : Les colonnes de la table `audit_event` (BE-007) portent-elles les noms de BE-152 (`eventId`, `actor`, `targetType`, `targetId`, `reason`, `result`, `correlationId`, `visibility`, `dataClassification`) ou ceux de BE-007 ?
  - NON DÉFINI : Recommandation appliquée : noms de BE-007 quand ils existent, sinon les noms de BE-152 ajoutés par migration ; aucune seconde table | QE-PAR-26
- Question : Le contrôle d'accès au sujet métier exigé par BE-169 est-il porté par un objet unique ?
  - NON DÉFINI : Recommandation appliquée : oui, le moteur d'autorisation unique de BE-226 ; BE-169 ne réimplémente aucune règle d'accès et déclare la dépendance | QE-PAR-27
- Question : Les codes d'erreur libres déjà présents dans le code (ex. `validation_error`, `webhook_eventId_missing`) sont-ils retenus ?
  - NON DÉFINI : Recommandation appliquée : non, tout code hors catalogue de BE-151 est rejeté à la construction (CA-4) et ramené au catalogue | QE-PAR-28
- Question : La casse des noms de tables doit-elle suivre la convention du CLAUDE.md du backend (tables camelCase) pour `audit_event` et `subscription_entitlement` ?
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-PAR-29
- Question : Quelle casse retenir pour les noms de tables (camelCase ou snake_case) ?
  - NON DÉFINI : Recommandation appliquée : snake_case pour toutes les tables, colonnes en camelCase ; `auditLog` renommé `audit_log` dans la ligne Tables de BE-152 ; la ligne « Code existant » de BE-152 (`auditLog`, `operatorAuditLog`) décrit le code actuel et reste inchangée | QE-PAR-30
- Question : Quel préfixe retenir pour les routes de la console opérateur, et existe-t-il des routes internes (préfixe `internal`) ?
  - NON DÉFINI : Recommandation appliquée : préfixe `admin` (`/api/v1/admin/...`) ; seule route concernée, `GET /api/v1/admin/evenements/types` (BE-176) ; aucune route interne dans ce fichier | QE-PAR-31
- Question : Quels prérequis hors de sa capacité BE-176 doit-il déclarer, et son ordre de vague est-il valide ?
  - NON DÉFINI : Recommandation appliquée : BE-176 déclare BE-001, BE-008, BE-009, BE-223, BE-226 (hors fichier) et BE-150, BE-151 (dans le fichier) ; à recalculer par le coordinateur : BE-176 (vague 14) dépend de BE-171 (vague 14) et doit passer en vague 15 ; lignes « Vague » non modifiées | QE-PAR-32
