# Tâches back-end — Administration plateforme et interventions (PH-12)

- Domaine : Administration globale, support et interventions (back-end uniquement)
- Chantier : ZYLO-OFFICE-BACKEND-PLAN
- Agent : BE-ADM (exécutant de planification, Haiku 5.5, effort medium)
- Sources lues :
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-12-administration-plateforme-interventions.md`
  - `definition-travail/00-pilotage/architecture-fondation/contrat-intervention-et-journal-audit.md`
  - Référence croisée en lecture seule : `definition-travail/03-plateforme/administration-plateforme/02-autorites-actions-et-controles.md` (matrice des rôles candidats, fiche d'action sensible, classes d'intervention)
- Plage d'identifiants utilisée : BE-120 à BE-147 (28 tâches, sans trou)
- Rattachement des modules : `app/administration/` n'existe pas dans develop ; les tâches sont rattachées à la capacité réelle `app/operator/` (console opérateur, support et interventions), à `app/rbac/` (affectations et révocations), à `app/audit/` (journal) ou à `app/notifications/` (notifications) ; NON DÉFINI : Recommandation appliquée : aucune nouvelle capacité créée | QE-ADM-26
- Convention : tout ce qui n'est pas fixé par les sources est écrit « NON DÉFINI » suivi d'une recommandation ; aucune valeur n'est inventée. Les routes, noms de tables et codes de permission ci-dessous sont des propositions de conception, à valider (voir Points ouverts).
- Codes HTTP retenus pour la conception : 401 non authentifié ; 403 droit, portée ou autorité insuffisants (y compris accès cross-tenant) ; 409 précondition d'état non remplie (preview expirée, version changée, approbation absente, résultat inconnu) ; 422 charge utile invalide (champ interdit, motif absent).

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-120 | Socle : portée administration globale et organisationnelle | 0 | BE-002, BE-008, BE-009 |
| BE-121 | Affectations de rôle globales et temporaires | 2 | BE-008, BE-120, BE-122 |
| BE-122 | Journal d'audit append-only | 1 | BE-007, BE-120, BE-242 |
| BE-123 | Cas d'intervention (ticket de support) | 4 | BE-002, BE-121, BE-122 |
| BE-124 | Modèle de commande opérateur et idempotence | 2 | BE-121, BE-122, BE-123 |
| BE-125 | Prévisualisation et confirmation des commandes | 2 | BE-005, BE-124 |
| BE-126 | Garde de commande (pipeline d'exécution) | 0 | BE-007, BE-121, BE-122, BE-125 |
| BE-127 | Registre des classes d'action sensible (fiche standard) | 1 | BE-120 |
| BE-128 | Approbation distincte (double validation) | 2 | BE-124, BE-127 |
| BE-129 | Recherche client et organisation | 1 | BE-100, BE-120, BE-122 |
| BE-130 | Vue synthèse des états de compte | 1 | BE-079, BE-129 |
| BE-131 | Listes filtrées des objets de support | 5 | BE-129 |
| BE-132 | Parcours guidé de diagnostic paiement | 2 | BE-122, BE-123 |
| BE-133 | Parcours guidé de diagnostic abonnement | 2 | BE-079, BE-132 |
| BE-134 | Suspension et rétablissement d'un tenant | 2 | BE-125, BE-126, BE-127, BE-128, BE-185 |
| BE-135 | Commande d'entitlement et de module | 1 | BE-125, BE-126, BE-128 |
| BE-136 | Préparation d'opérations financières (sans exécution PSP) | 1 | BE-125, BE-127, BE-128 |
| BE-137 | Export, suppression et restauration (commandes bloquées) | 3 | BE-126, BE-127, BE-128, BE-214, BE-243 |
| BE-138 | Accès exceptionnel au contenu client (BLOCKED Q-06) | 1 | BE-007, BE-121, BE-122, BE-127, BE-128 |
| BE-139 | Rejeu d'événement à effet métier | 1 | BE-125, BE-126, BE-128, BE-234, BE-235 |
| BE-140 | Changement de rôle ou d'adhésion d'un membre | 1 | BE-106, BE-125, BE-126, BE-128 |
| BE-141 | Changement de configuration et gel de credential | 2 | BE-126, BE-127, BE-128, BE-230, BE-237 |
| BE-142 | Escalade et incident | 2 | BE-123, BE-247 |
| BE-143 | Réconciliation des résultats inconnus et vérification post-action | 2 | BE-007, BE-124, BE-126 |
| BE-144 | Notifications d'une action | 1 | BE-122, BE-124, BE-167 |
| BE-145 | Compteurs d'exploitation de la console | 1 | BE-122, BE-124, BE-241 |
| BE-146 | Révocation et fin de fenêtre des droits temporaires | 1 | BE-121 |
| BE-147 | Garde transversale anti cross-tenant | 0 | BE-120, BE-122 |

---

## Tâches

### BE-120 — Socle : portée administration globale et organisationnelle
- Domaine : Autorisation et portée (administration)
- Vague : 6
- Routes : aucune
- Tables / migrations : NON DÉFINI ; recommandation : aucune table propre. Le type de portée (`platform` ou `tenant:<id canonique>`) est un objet de domaine partagé, utilisé par BE-121 et suivants.
- Droits : règle deny-by-default ; une session d'administrateur global sans affectation organisationnelle n'accède à aucun contenu tenant ; refus 403. Portée : plateforme ou tenant explicite. Le contrôle d'accès opérateur existant (liste `OPERATOR_READ_USER_IDS`, `app/operator/permissions.py`) est remplacé par la portée plateforme ; NON DÉFINI : Recommandation appliquée : remplacement complet à la livraison de BE-120 | QE-ADM-21
- Dépendances : BE-002 (identifiant canonique du tenant, organisation racine), BE-008 (rôles et permissions), BE-009 (garde serveur de contexte organisation)
- Critères d'acceptation :
  - CA-1 : test unitaire : les portées `platform` et `tenant:<id>` sont distinctes ; une portée mal formée est rejetée (422).
  - CA-2 (refus de droit) : une requête portant la portée `platform` sur une ressource de contenu tenant renvoie 403.
  - CA-3 (isolation tenant) : un administrateur global sans affectation tenant reçoit 403 sur le contenu du tenant A.
  - CA-4 (refus de droit) : un sujet sans aucune affectation reçoit 403 sur toute route d'administration.
- Documentation attendue : docstrings explicites des fonctions publiques ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/scope.py`.
- Source : PH-12-administration-plateforme-interventions.md#Démarche pas à pas (étape 1) ; 02-autorites-actions-et-controles.md#1 Principes (référence croisée)

### BE-121 — Affectations de rôle globales et temporaires
- Domaine : Autorisation et portée (administration)
- Vague : 8
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/role-assignments`
  - `GET /api/v1/admin/role-assignments?actor_id=`
- Tables / migrations : `admin_role_assignment` (id, actorId, roleCode, scope, grantedBy, grantedAt, expiresAt NON DÉFINI nullable, revokedAt). Rôles candidats : agent support L1, agent support L2, finance support, opérateur plateforme, sécurité / incident commander, approbateur indépendant, auditeur, administrateur client.
- Droits : permission proposée NON DÉFINI (`admin.roles.assign`) ; seule la portée plateforme peut attribuer un rôle global ; refus 403 ; un rôle temporaire doit porter une échéance (recommandation, QE-ADM-03).
- Dépendances : BE-008 (permission `admin.roles.assign`), BE-120 (portée), BE-122 (événement d'audit de CA-4)
- Critères d'acceptation :
  - CA-1 (refus de droit) : un agent support L1 qui tente d'attribuer un rôle reçoit 403.
  - CA-2 (refus de droit) : une attribution sans échéance pour un rôle marqué temporaire est refusée (422).
  - CA-3 (isolation tenant) : une affectation de scope `tenant:A` n'ouvre aucune ressource du tenant B (403).
  - CA-4 : l'attribution crée un événement d'audit (BE-122) ; test vérifiant la présence de l'événement.
- Documentation attendue : docstrings des fonctions publiques ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/rbac/role_assignments.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'audit fonctionnel (changement de rôle/scope, élévation temporelle) ; PH-12#Démarche pas à pas (étapes 2 et 8)
- Code existant (develop) : `app/rbac/models.py` (`Role`, `UserRole` : rôle attribué à un utilisateur dans une organisation, portée optionnelle `resourceType`/`resourceId`, sans portée plateforme ni échéance) ; garder : `Role`, `UserRole` sans modification ; casser : rien (`admin_role_assignment` est une table distincte) ; à créer : `app/rbac/role_assignments.py`, table `admin_role_assignment`, route `POST /api/v1/admin/role-assignments` et `GET /api/v1/admin/role-assignments`

### BE-122 — Journal d'audit append-only
- Domaine : Audit
- Vague : 7
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/audit-events`
- Tables / migrations : table `audit_event`, propriétaire BE-007 (migration de `audit_log`). BE-122 réutilise les colonnes de BE-007 sans en ajouter : correspondance `occurredAtUtc` = `createdAt`, `actorId` = `actorUserId`, `tenantId` = `organizationId`, `objectType` / `objectId` = `entityType` / `entityId`, `scope` = `scopeResourceType` / `scopeResourceId`, `correlationId` = `request_id`, `action` = `action`, `result` = `result` (`success` | `refused` | `error`). Champs sans colonne dans BE-007 : `actorService`, `authContext`, `category`, `reasonTicket`, `initiatorId`, `approverId`, `stateBeforeRef`, `stateAfterRef`, `notificationStatus`, `windowDuration` ; NON DÉFINI : Recommandation appliquée : BE-122 consomme les colonnes de `audit_event` telles que listées dans BE-007 ; chaque colonne manquante est demandée à BE-007 par la phrase « colonne demandée à BE-007 : <nom> » et n'est pas créée par BE-122 ; `organizationId` reste NULL pour la portée plateforme | QE-ADM-27. Pas de colonne secret, token, PAN, CVV ni charge utile brute.
- Droits : lecture réservée au rôle auditeur, portée plateforme ; refus 403 pour tout autre rôle. Aucune écriture ni suppression exposée ; correction par événement correctif référencé (jamais par UPDATE ou DELETE).
- Dépendances : BE-007 (table `audit_event`, propriétaire), BE-120 (portée), BE-242 (classes de rétention) ; EXT non résolu : PH-13 immutabilité technique et droit de lecture (non décidés, voir QE-ADM-10)
- Critères d'acceptation :
  - CA-1 : une écriture sans `correlationId` ou sans `action` est refusée (422).
  - CA-2 (refus de droit) : un agent support L2 qui appelle `GET /api/v1/admin/audit-events` reçoit 403.
  - CA-3 : tentative de modification ou suppression d'un événement, par API ou par requête de mise à jour, est refusée (test d'intégrité) ; un événement correctif référence l'original.
  - CA-4 (isolation tenant) : un auditeur sans affectation au tenant B ne reçoit aucun événement de B.
  - CA-5 : un champ marqué secret ou PAN/CVV est rejeté (422) et n'apparaît dans aucune réponse.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/audit/admin_audit.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'audit fonctionnel ; PH-12#Démarche pas à pas (étape 7)
- Code existant (develop) : `app/audit/models.py` (`AuditLog`, table `auditLog` : organisation, acteur, action, entité, portée, résumé, changements) ; `app/audit/service.py` (`record_audit_event(...)`, `list_audit_logs`) ; `app/audit/router.py` (`GET /api/v1/audit`, lecture par organisation) ; `app/operator/audit_models.py` (`OperatorAuditLog`, table `operatorAuditLog`) et `app/operator/audit.py` (`record_operator_read`) ; garder : `record_audit_event` (signature à étendre), `list_audit_logs` pour la logique de visibilité ; casser : tables `auditLog` et `operatorAuditLog` ; `audit_event` (BE-007) est la seule table d'audit, `operatorAuditLog` n'est plus écrite ; à créer : colonnes manquantes de `audit_event`, route `GET /api/v1/admin/audit-events`, module `app/audit/admin_audit.py`

### BE-123 — Cas d'intervention (ticket de support)
- Domaine : Interventions
- Vague : 9
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/cases`
  - `GET /api/v1/admin/cases/{case_id}`
  - `POST /api/v1/admin/cases/{case_id}/assign`
  - `POST /api/v1/admin/cases/{case_id}/close`
- Tables / migrations : `intervention_case` (id, tenantId NULL si plateforme, status, priority, qualification, openedBy, assigneeId, consentRef NULL, openedAtUtc, closedAtUtc, closureReason). Priorité : enum fermé `basse | normale | haute` (recommandation, QE-ADM-14).
- Droits : ouverture par agent support L1 ou L2 ; affectation et clôture par responsable d'escalade (NON DÉFINI, permission proposée `admin.cases.manage`) ; lecture limitée au cas affecté ou à la portée du rôle ; refus 403 ; clôture sans vérification enregistrée : 409.
- Dépendances : BE-002 (identifiant de tenant canonique), BE-121, BE-122
- Critères d'acceptation :
  - CA-1 : ouverture d'un cas avec priorité hors enum : 422.
  - CA-2 (refus de droit) : un agent L1 qui affecte un cas reçoit 403.
  - CA-3 (isolation tenant) : un agent limité au tenant A qui lit un cas du tenant B reçoit 403.
  - CA-4 : clôture sans vérification enregistrée : 409 ; avec vérification : 200 et `closedAtUtc` renseigné.
  - CA-5 : chaque transition de statut produit un événement d'audit (test sur la présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/cases.py`.
- Source : PH-12#Démarche pas à pas (étape 4) ; contrat-intervention-et-journal-audit.md#Contrat d'audit fonctionnel (ouverture case)

### BE-124 — Modèle de commande opérateur et idempotence
- Domaine : Interventions (commandes)
- Vague : 10
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/commands`
  - `GET /api/v1/admin/commands/{command_id}`
- Tables / migrations : `admin_command` (commandId, commandType, commandVersion, actorId, approverId NULL, effectiveRole, effectiveScope, tenantId, targetObjectType, targetObjectId, targetVersionExpected, reasonTicket, idempotencyKey, correlationId, status, result, createdAtUtc, expiresAtUtc). Contrainte d'unicité sur (actorId, idempotencyKey) (recommandation).
- Droits : création d'une intention par rôle habilité à la classe de commande ; refus 403 ; clé d'idempotence réemployée avec un corps différent : 409.
- Dépendances : BE-121, BE-122, BE-123 ; EXT non résolu : domaines propriétaires des mutations (PH-07 à PH-10) qui exécutent l'effet ; NON DÉFINI : Recommandation appliquée : la commande ne porte que l'intention, l'effet est appelé chez le domaine propriétaire désigné par QE-ADM-22 | QE-ADM-22
- Critères d'acceptation :
  - CA-1 : deux envois de la même `idempotencyKey` avec le même corps renvoient la même commande et un seul effet (test de double envoi).
  - CA-2 : même clé avec corps différent : 409.
  - CA-3 (refus de droit) : un rôle non habilité à la classe reçoit 403 et aucune commande n'est créée.
  - CA-4 : absence de `reasonTicket` : 422.
  - CA-5 (isolation tenant) : une commande visant le tenant B, créée par un acteur du tenant A, est refusée (403).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/commands.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur ; 02-autorites-actions-et-controles.md#3 Garde de commande (référence croisée)

### BE-125 — Prévisualisation et confirmation des commandes
- Domaine : Interventions (commandes)
- Vague : 11
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/commands/{command_id}/preview`
  - `POST /api/v1/admin/commands/{command_id}/confirm`
- Tables / migrations : `admin_command_preview` (previewId, commandId, stateSnapshotHash, effects jsonb, limits, expiresAtUtc NOT NULL, invalidatedReason NULL). Durée de preview : NON DÉFINI (QE-ADM-07).
- Droits : preview et confirm réservés au rôle qui a créé la commande ; refus 403 ; preview expirée, invalidée ou version changée : 409.
- Dépendances : BE-005 (session et authentification), BE-124 ; EXT non résolu : PH-08 authentification récente (définie par la politique, non décidée) ; NON DÉFINI : Recommandation appliquée : fraîcheur d'authentification exigée à la confirmation, durée non codée | QE-ADM-23
- Critères d'acceptation :
  - CA-1 : la preview ne modifie aucun état métier (test : état avant = état après).
  - CA-2 : confirmation après `expiresAtUtc` : 409.
  - CA-3 : confirmation après changement de version de l'objet : 409.
  - CA-4 (refus de droit) : confirmation par un autre acteur que l'initiateur : 403.
  - CA-5 (isolation tenant) : la preview affiche l'identifiant canonique du tenant cible ; une preview sans tenant cible est refusée (422).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/preview.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (Prévisualisation, Confirmation) ; 02-autorites-actions-et-controles.md#3 (références croisées)

### BE-126 — Garde de commande (pipeline d'exécution)
- Domaine : Interventions (commandes)
- Vague : 12
- Routes : aucune (pipeline interne, déclenché par `POST /api/v1/admin/commands/{command_id}/confirm` de BE-125)
- Tables / migrations : aucune table propre ; écrit dans `admin_command` (status) et `audit_event`.
- Droits : revalidation au commit : rôle et affectation encore valides, sinon 403 ; tenant re-résolu, sinon arrêt 409 ; intention d'audit durable écrite avant exécution.
- Dépendances : BE-007 (table `audit_event`, intention d'audit), BE-121 (validité de l'affectation revalidée au commit), BE-122, BE-125 ; EXT non résolu : domaine propriétaire de la mutation (appelé de manière idempotente), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 : l'ordre des étapes est : autorisation, tenant, état, preview, motif, approbation, revalidation, intention d'audit, exécution, vérification, notification, clôture. Test d'ordre sur un enregistreur d'étapes.
  - CA-2 (refus de droit) : droit retiré entre preview et confirmation : 403, aucun effet.
  - CA-3 : l'intention d'audit est persistée avant l'appel au domaine propriétaire (test d'ordre).
  - CA-4 (isolation tenant) : identifiant de tenant changé entre preview et commit : arrêt 409, aucun effet.
  - CA-5 : une étape qui reçoit un résultat inconnu arrête le pipeline sans second appel.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/guard.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (Ordre candidat) ; 02-autorites-actions-et-controles.md#3 (référence croisée)

### BE-127 — Registre des classes d'action sensible (fiche standard)
- Domaine : Interventions (actions sensibles)
- Vague : 7
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/sensitive-action-classes`
- Tables / migrations : `sensitive_action_class` (code, requiresDoubleValidation, requiresReauth, approvalWindow NON DÉFINI, reversible, risk_note). Classes : suspension/rétablissement tenant ; activation ou changement d'entitlement/module ; opération facture/paiement/remboursement ; changement de rôle ou d'adhésion ; export, suppression, restauration ; accès exceptionnel au contenu ; replay d'événement à effet métier ; modification de configuration ou credential.
- Droits : lecture par auditeur et administrateur global ; modification du registre NON DÉFINI (recommandation : aucune route d'écriture, changement par migration).
- Dépendances : BE-120
- Critères d'acceptation :
  - CA-1 : chaque classe expose les champs de la fiche standard (autorité, cible, motif, prévisualisation, limite, confirmation, exécution, échec/reprise, notification, audit, revue) ; test de schéma.
  - CA-2 (refus de droit) : lecture par agent L1 : 403.
  - CA-3 : une commande de classe à double validation sans approbateur : 409.
  - CA-4 : aucune classe n'est créée ni modifiée par API (test : écriture refusée, 405).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/sensitive_classes.py`.
- Source : contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; 02-autorites-actions-et-controles.md#4 Action sensible (référence croisée)
- Code existant (develop) : aucun ; à créer : `app/operator/sensitive_classes.py` (registre en lecture seule, sans table existante ; la classe `sensitive_action_class` est un registre code, route `GET /api/v1/admin/sensitive-action-classes`)

### BE-128 — Approbation distincte (double validation)
- Domaine : Interventions (actions sensibles)
- Vague : 11
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/commands/{command_id}/approve`
  - `POST /api/v1/admin/commands/{command_id}/reject`
- Tables / migrations : `admin_command_approval` (commandId, approverId, decision, decidedAtUtc, reasonTicket). Une seule décision par commande.
- Droits : approbateur indépendant uniquement ; l'initiateur ne peut pas approuver sa propre commande : 403 ; refus 403 pour tout autre rôle.
- Dépendances : BE-124, BE-127
- Critères d'acceptation :
  - CA-1 (refus de droit) : auto-approbation par l'initiateur : 403.
  - CA-2 (refus de droit) : approbation par un agent L2 : 403.
  - CA-3 : rejet d'une commande la place en état terminal ; toute confirmation ultérieure : 409.
  - CA-4 : approbation par une seconde identité habilitée : la commande passe à l'état approuvé (test nominal).
  - CA-5 (isolation tenant) : approbateur sans affectation au tenant de la commande : 403.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/approval.py`.
- Source : 02-autorites-actions-et-controles.md#1 et #4 (référence croisée) ; PH-12#Démarche pas à pas (étape 6) ; contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (approbateur distinct)

### BE-129 — Recherche client et organisation
- Domaine : Console de support (lecture)
- Vague : 12
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/search?q=&type=`
- Tables / migrations : aucune table propre ; lecture de la table des organisations (BE-100). Le terme recherché n'est pas stocké en clair dans l'audit (recommandation : empreinte).
- Droits : permission proposée NON DÉFINI (`admin.search.read`) ; agent L1 : vue limitée aux champs normalisés ; refus 403 pour les rôles sans droit.
- Dépendances : BE-100 (organisations), BE-120, BE-122
- Critères d'acceptation :
  - CA-1 : la recherche est écrite dans l'audit avec une empreinte du terme, jamais en clair (test).
  - CA-2 (refus de droit) : rôle sans droit de recherche : 403.
  - CA-3 (isolation tenant) : un agent limité au tenant A ne reçoit aucun résultat du tenant B (test avec jeu de données deux tenants).
  - CA-4 : un champ hors liste L1 n'apparaît pas dans la réponse (test de projection).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/search.py`.
- Source : PH-12#Démarche pas à pas (étape 2) ; PH-12#Critères d'acceptation (critère 1) ; 02-autorites-actions-et-controles.md#2 (référence croisée)

### BE-130 — Vue synthèse des états de compte
- Domaine : Console de support (lecture)
- Vague : 13
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/organizations/{organization_id}/summary`
- Tables / migrations : aucune table propre ; agrège les états offre, abonnement, paiement, factures, droits, incidents et échéances. Champ santé/réputation : NON DÉFINI (PH-01A non arbitré) ; recommandation : absent de la réponse, champ marqué N/A.
- Droits : projection selon le rôle (L1 : facture et paiement masqués ; finance : données financières ; opérateur : pas de contenu client) ; refus 403 hors portée.
- Dépendances : BE-079 (états d'abonnement, PH-07), BE-129 ; EXT non résolu : états offre (PH-07), droits (PH-08), paiement et factures (PH-10), incidents (PH-13/PH-16), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 : la réponse contient les sections offre, abonnement, paiement, factures, droits, incidents, échéances, ou la mention N/A explicite (test de schéma).
  - CA-2 (refus de droit) : agent L1 demandant la section facture non masquée : 403 ou champ masqué (test selon recommandation QE-ADM-02).
  - CA-3 (isolation tenant) : un rôle lié au tenant A demandant la synthèse du tenant B : 403.
  - CA-4 : aucun champ santé/réputation n'est présent tant que PH-01A n'est pas arbitré.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/summary.py`.
- Source : PH-12#Démarche pas à pas (étape 2) ; PH-12#Questions à résoudre et clarification

### BE-131 — Listes filtrées des objets de support
- Domaine : Console de support (lecture)
- Vague : 13
- Routes :
  - NON DÉFINI ; routes proposées :
  - `GET /api/v1/admin/organizations/{organization_id}/subscriptions`
  - `GET /api/v1/admin/organizations/{organization_id}/invoices`
  - `GET /api/v1/admin/organizations/{organization_id}/payments`
  - `GET /api/v1/admin/organizations/{organization_id}/entitlements`
  - `GET /api/v1/admin/organizations/{organization_id}/incidents`
- Tables / migrations : aucune table propre ; lecture des objets de PH-07 à PH-10 et PH-13/PH-16. Filtres : statut, date, identifiant ; champs indisponibles : N/A explicite.
- Droits : projection selon rôle ; refus 403 hors portée ; pagination bornée (taille maximale NON DÉFINI, QE-ADM-16).
- Dépendances : BE-129 ; EXT non résolu : objets abonnement, facture, paiement, droits, incidents (PH-07 à PH-10, PH-13/PH-16), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 : les cinq listes couvrent 100 % des objets de support du périmètre (test de couverture du registre).
  - CA-2 : un filtre sur un champ non autorisé pour le rôle renvoie 422 ou un résultat masqué (test).
  - CA-3 (isolation tenant) : liste du tenant B demandée avec une affectation au tenant A : 403.
  - CA-4 (refus de droit) : rôle sans lecture des incidents : 403 sur `/incidents`.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/support_lists.py`.
- Source : PH-12#Critères d'acceptation (critère 1) ; PH-12#Démarche pas à pas (étape 2)

### BE-132 — Parcours guidé de diagnostic paiement
- Domaine : Interventions (paiement)
- Vague : 10
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/cases/{case_id}/payment-diagnostics`
  - `GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id}`
- Tables / migrations : `payment_diagnostic` (diagnosticId, caseId, qualification, proofConsultedRef, permittedAction, result, verificationStatus, failurePath, escalationId NULL, closedAtUtc).
- Droits : lancement d'un diagnostic en lecture par L1 et L2 ; aucune action financière dans ce parcours ; refus 403.
- Dépendances : BE-122, BE-123 ; EXT non résolu : règles de paiement et d'échec (PH-10, politique non décidée, QE-ADM-08)
- Critères d'acceptation :
  - CA-1 : le parcours enregistre qualification, preuve consultée, action permise, résultat, vérification, échec/reprise, escalade et clôture (test de schéma).
  - CA-2 (refus de droit) : tentative d'action financière depuis ce parcours : 403.
  - CA-3 (isolation tenant) : diagnostic sur un cas du tenant B par un agent du tenant A : 403.
  - CA-4 : échec de diagnostic crée une escalade ou une reprise tracée (test de transition).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/payment_diagnostic.py`.
- Source : PH-12#Démarche pas à pas (étape 5) ; PH-12#Critères d'acceptation (critère 2)

### BE-133 — Parcours guidé de diagnostic abonnement
- Domaine : Interventions (abonnement)
- Vague : 11
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/cases/{case_id}/subscription-diagnostics`
  - `GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id}`
- Tables / migrations : `subscription_diagnostic` (diagnosticId, caseId, qualification, proofConsultedRef, permittedAction, result, verificationStatus, failurePath, escalationId NULL, closedAtUtc).
- Droits : diagnostic en lecture par L1 et L2 ; toute correction d'abonnement passe par BE-135 ; refus 403.
- Dépendances : BE-079 (états d'abonnement, PH-07), BE-132 ; EXT non résolu : transitions d'abonnement (PH-09), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 : le parcours couvre les mêmes huit étapes que le parcours paiement (test de schéma).
  - CA-2 (refus de droit) : modification directe d'un entitlement dérivé depuis ce parcours : 403 ou 405.
  - CA-3 (isolation tenant) : diagnostic d'un abonnement du tenant B par un agent du tenant A : 403.
  - CA-4 : rétablissement d'un abonnement sans préconditions remplies : 409.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/subscription_diagnostic.py`.
- Source : PH-12#Démarche pas à pas (étape 5) ; 02-autorites-actions-et-controles.md#5 (référence croisée)

### BE-134 — Suspension et rétablissement d'un tenant
- Domaine : Interventions (commandes sensibles)
- Vague : 13
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/organizations/{organization_id}/suspension`
  - `POST /api/v1/admin/organizations/{organization_id}/reinstatement`
- Tables / migrations : aucune table propre ; utilise `admin_command` et `admin_command_preview`. Statut de suspension écrit par le domaine tenant (PH-07).
- Droits : permission proposée NON DÉFINI (`admin.tenant.suspend`) ; double validation (BE-128) ; refus 403 ; rétablissement seulement si préconditions remplies, sinon 409. Aucune suspension automatique (QE-ADM-06).
- Dépendances : BE-125, BE-126, BE-127, BE-128, BE-185 (cycle de vie du tenant, statut de compte) ; EXT non résolu : préconditions de rétablissement (PH-07, PH-10), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 (refus de droit) : agent L1 demandant la suspension : 403.
  - CA-2 : suspension sans approbation distincte : 409.
  - CA-3 (isolation tenant) : suspension d'un tenant hors portée de l'opérateur : 403.
  - CA-4 : la preview expose l'impact sur connexion, opérations en cours, API, exports et facturation (test de schéma).
  - CA-5 : le rejeu de la même commande (même clé) ne suspend pas deux fois (test d'idempotence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/tenant_status.py`.
- Source : 02-autorites-actions-et-controles.md#5 Suspension (référence croisée) ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; PH-12#Démarche pas à pas (étape 5)

### BE-135 — Commande d'entitlement et de module
- Domaine : Interventions (commandes sensibles)
- Vague : 13
- Routes :
  - NON DÉFINI ; route proposée :
  - `POST /api/v1/admin/organizations/{organization_id}/entitlements/commands`
- Tables / migrations : aucune table propre ; l'entitlement dérivé n'est jamais modifié directement. Recommandation : table d'entitlement appartient au domaine source.
- Droits : permission proposée NON DÉFINI (`admin.entitlement.command`) ; double validation (BE-128) ; toute écriture directe (ex. PATCH sur entitlement) : 405 ; refus 403.
- Dépendances : BE-125, BE-126, BE-128 ; EXT non résolu : entitlements et modules (PH-09, plusieurs objets candidats, voir QE-ADM-22) ; invalidation de cache (PH-14, aucune tâche de cache dans le plan, voir QE-ADM-24)
- Critères d'acceptation :
  - CA-1 : écriture directe d'un entitlement dérivé : 405 (test).
  - CA-2 (refus de droit) : agent L2 demandant un changement de module : 403.
  - CA-3 (isolation tenant) : commande visant le tenant B depuis une affectation au tenant A : 403.
  - CA-4 : la preview liste modules et utilisateurs affectés (test de schéma).
  - CA-5 : la commande produit un événement d'invalidation de cache (test sur la présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/entitlement_commands.py`.
- Source : 02-autorites-actions-et-controles.md#5 Abonnement / entitlement / module (référence croisée) ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer

### BE-136 — Préparation d'opérations financières (sans exécution PSP)
- Domaine : Interventions (facturation et paiement)
- Vague : 12
- Routes :
  - NON DÉFINI ; route proposée :
  - `POST /api/v1/admin/invoices/{invoice_id}/finance-commands`
- Tables / migrations : aucune table propre ; utilise `admin_command`, `admin_command_preview`, `intervention_case`. Aucune donnée de carte n'est acceptée.
- Droits : permission proposée NON DÉFINI (`admin.finance.prepare`) ; seule la finance avec autorité PH-10 peut préparer ; exécution PSP : interdite tant que la politique n'est pas décidée ; refus 403 et ouverture d'une escalade finance.
- Dépendances : BE-125, BE-127, BE-128 ; EXT non résolu : politique financière et PSP (PH-10, non décidées, QE-ADM-08)
- Critères d'acceptation :
  - CA-1 (refus de droit) : agent L1 préparant une opération financière : 403.
  - CA-2 : un champ de carte (numéro, CVV) est rejeté (422) et n'est pas journalisé.
  - CA-3 : aucun appel au PSP n'est émis (test avec client PSP simulé, zéro appel).
  - CA-4 (isolation tenant) : facture du tenant B préparée depuis une affectation au tenant A : 403.
  - CA-5 : refus par absence d'autorité crée un cas d'escalade finance (test de présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/finance_commands.py`.
- Source : 02-autorites-actions-et-controles.md#5 Facturation / paiement (référence croisée) ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer

### BE-137 — Export, suppression et restauration (commandes bloquées)
- Domaine : Interventions (données sensibles)
- Vague : 20
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/organizations/{organization_id}/exports`
  - `POST /api/v1/admin/organizations/{organization_id}/deletions`
  - `POST /api/v1/admin/organizations/{organization_id}/restorations`
- Tables / migrations : aucune table propre ; utilise `admin_command` et `admin_command_preview`. Rétention et sauvegarde : NON DÉFINI (PH-13/PH-16).
- Droits : création d'une preview seulement ; exécution : 409 tant que la politique de rétention n'est pas décidée ; export global depuis L1 : 403 ; double validation (BE-128) ; refus 403.
- Dépendances : BE-126, BE-127, BE-128, BE-214 (rétention et sauvegarde), BE-243 (périmètre d'export) ; EXT non résolu : PH-07 et PH-08 (voir QE-ADM-22)
- Critères d'acceptation :
  - CA-1 (refus de droit) : export global demandé par agent L1 : 403.
  - CA-2 : exécution de suppression sans politique de rétention décidée : 409 (test).
  - CA-3 : la preview de suppression mentionne rétention, sauvegarde, factures et audit (test de schéma).
  - CA-4 (isolation tenant) : export demandé sur le tenant B depuis une affectation au tenant A : 403.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/data_lifecycle.py`.
- Source : 02-autorites-actions-et-controles.md#5 Export / suppression (référence croisée) ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; PH-12#Critères d'acceptation (critère 4)

### BE-138 — Accès exceptionnel au contenu client (BLOCKED Q-06)
- Domaine : Interventions (accès sensible)
- Vague : 12
- Routes :
  - NON DÉFINI ; route proposée (refusée par défaut) :
  - `POST /api/v1/admin/organizations/{organization_id}/exceptional-access`
- Tables / migrations : aucune table propre ; l'événement de refus est écrit dans `audit_event`. Statut : BLOCKED tant que Q-06 n'est pas tranchée.
- Droits : aucun rôle n'obtient l'accès ; toute demande reçoit 403, y compris depuis le rôle sécurité / incident commander ; l'accès cross-tenant reste BLOCKED.
- Dépendances : BE-007 (table `audit_event`, événement de refus), BE-121, BE-122, BE-127, BE-128 ; EXT non résolu : décision Q-06 (support et accès sensible) et exigences PH-16 (voir QE-ADM-06)
- Critères d'acceptation :
  - CA-1 (refus de droit) : tout appelant, y compris sécurité, reçoit 403 (test sur chaque rôle de BE-121).
  - CA-2 : chaque refus produit un événement d'audit avec motif et corrélation (test de présence).
  - CA-3 (isolation tenant) : aucune donnée du tenant B n'est renvoyée à un appelant du tenant A (test à deux tenants).
  - CA-4 : aucune donnée de contenu client n'apparaît dans la réponse de refus (test de projection).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/exceptional_access.py` (contenu vide tant que BLOCKED).
- Source : 02-autorites-actions-et-controles.md#1 (accès au contenu client) ; contrat-intervention-et-journal-audit.md#Questions et état (Q-06, accès cross-tenant BLOCKED) ; PH-12#Critères d'acceptation (critère 4)

### BE-139 — Rejeu d'événement à effet métier
- Domaine : Interventions (commandes sensibles)
- Vague : 13
- Routes :
  - NON DÉFINI ; route proposée :
  - `POST /api/v1/admin/events/{event_id}/replay-commands`
- Tables / migrations : aucune table propre ; utilise `admin_command`. Événement source : PH-14.
- Droits : permission proposée NON DÉFINI (`admin.events.replay`) ; double validation (BE-128) ; refus 403.
- Dépendances : BE-125, BE-126, BE-128, BE-234 (enveloppe d'événement versionnée), BE-235 (replay)
- Critères d'acceptation :
  - CA-1 : rejeu d'un événement déjà appliqué avec la même clé : aucun second effet (test d'idempotence).
  - CA-2 (refus de droit) : rejeu sans approbation distincte : 409 ; rejeu par rôle non habilité : 403.
  - CA-3 (isolation tenant) : rejeu d'un événement du tenant B depuis une affectation au tenant A : 403.
  - CA-4 : rejeu ambigu produit le statut `unknown` et aucun nouvel appel (test).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/event_replay.py`.
- Source : contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (Rejeu sûr)

### BE-140 — Changement de rôle ou d'adhésion d'un membre
- Domaine : Interventions (commandes sensibles)
- Vague : 15
- Routes :
  - NON DÉFINI ; route proposée :
  - `POST /api/v1/admin/organizations/{organization_id}/memberships/{user_id}/role-changes`
- Tables / migrations : aucune table propre ; écrit via le domaine organisation (BE-106) ; utilise `admin_command`.
- Droits : permission proposée NON DÉFINI (`admin.membership.command`) ; double validation (BE-128) ; refus 403 ; l'administrateur client n'agit que dans son tenant (self-service défini par PH-11).
- Dépendances : BE-106 (changement de rôle et retrait de membre), BE-125, BE-126, BE-128
- Critères d'acceptation :
  - CA-1 (refus de droit) : agent L1 demandant un changement de rôle : 403.
  - CA-2 (isolation tenant) : un administrateur client du tenant A tentant de changer un membre du tenant B : 403.
  - CA-3 : changement sans approbation distincte : 409.
  - CA-4 : le changement écrit un événement d'audit avec état avant et après (test de présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/membership_commands.py`.
- Source : contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; 02-autorites-actions-et-controles.md#2 (référence croisée)

### BE-141 — Changement de configuration et gel de credential
- Domaine : Interventions (sécurité et exploitation)
- Vague : 13
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/organizations/{organization_id}/config-changes`
  - `POST /api/v1/admin/credentials/{credential_id}/freeze`
- Tables / migrations : aucune table propre ; utilise `admin_command`. Credentials : valeurs jamais stockées ni renvoyées dans ces tables.
- Droits : permission proposée NON DÉFINI (`admin.config.command`, `admin.credential.freeze`) ; gel réservé au rôle sécurité / incident commander ; double validation (BE-128) ; refus 403.
- Dépendances : BE-126, BE-127, BE-128, BE-230 (credentials : rotation et révocation), BE-237 (réglages et historique) ; EXT non résolu : procédures de sécurité et d'exploitation (PH-16)
- Critères d'acceptation :
  - CA-1 (refus de droit) : gel de credential par agent L2 : 403.
  - CA-2 : aucune réponse ni journal ne contient la valeur du credential (test de projection et de journal).
  - CA-3 (isolation tenant) : changement de configuration du tenant B depuis une affectation au tenant A : 403.
  - CA-4 : gel sans approbation distincte : 409.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/config_security.py`.
- Source : 02-autorites-actions-et-controles.md#2 Sécurité / incident commander ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer ; contrat-intervention-et-journal-audit.md#Contrat d'audit fonctionnel (pas de secret)

### BE-142 — Escalade et incident
- Domaine : Interventions (escalade)
- Vague : 10
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/cases/{case_id}/escalations`
  - `POST /api/v1/admin/escalations/{escalation_id}/close`
- Tables / migrations : `escalation` (id, caseId, level, targetRole, openedAtUtc, closedAtUtc, closureReason). Niveaux : NON DÉFINI (QE-ADM-12).
- Droits : ouverture par L1 et L2 ; clôture par le responsable d'escalade seulement ; refus 403 ; astreinte : NON DÉFINI.
- Dépendances : BE-123, BE-247
- Critères d'acceptation :
  - CA-1 (refus de droit) : clôture d'une escalade par L1 : 403.
  - CA-2 : ouverture d'escalade met le cas en état escaladé (test de transition).
  - CA-3 (isolation tenant) : escalade d'un cas du tenant B par un agent du tenant A : 403.
  - CA-4 : chaque ouverture et clôture produit un événement d'audit (test de présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/escalation.py`.
- Source : PH-12#Démarche pas à pas (étape 8) ; PH-12#Rôles des agents et règle de passage (responsable d'escalade)

### BE-143 — Réconciliation des résultats inconnus et vérification post-action
- Domaine : Interventions (exécution)
- Vague : 13
- Routes :
  - NON DÉFINI ; routes proposées :
  - `POST /api/v1/admin/commands/{command_id}/reconcile`
  - `POST /api/v1/admin/commands/{command_id}/verify`
- Tables / migrations : aucune table propre ; met à jour `admin_command.status` et écrit `audit_event`. Nombre maximal de reprises : NON DÉFINI (QE-ADM-19).
- Droits : réconciliation en lecture seule par L2, opérateur plateforme et sécurité ; vérification par le propriétaire du domaine ; refus 403.
- Dépendances : BE-007 (table `audit_event`), BE-124, BE-126 ; EXT non résolu : vérification de l'état par le domaine propriétaire (PH-07 à PH-10), voir QE-ADM-22
- Critères d'acceptation :
  - CA-1 : une commande en statut `unknown` bloque tout nouvel effet (test).
  - CA-2 : la réconciliation ne modifie aucun état métier (test : état avant = état après).
  - CA-3 (refus de droit) : vérification par agent L1 : 403.
  - CA-4 : une reprise réemploie la clé d'idempotence d'origine (test).
  - CA-5 (isolation tenant) : réconciliation d'une commande du tenant B par un agent du tenant A : 403.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/reconcile.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (Échec, Vérification) ; 02-autorites-actions-et-controles.md#3 (référence croisée)

### BE-144 — Notifications d'une action
- Domaine : Notifications (liées aux interventions)
- Vague : 11
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/commands/{command_id}/notifications`
- Tables / migrations : `admin_notification` (id, commandId, channel NON DÉFINI, recipientRef, status, sentAtUtc NULL, failureReason NULL). Canaux et destinataires : NON DÉFINI (PH-13).
- Droits : lecture par auditeur et rôle ayant la commande ; refus 403.
- Dépendances : BE-122, BE-124, BE-167
- Critères d'acceptation :
  - CA-1 : un échec d'envoi est enregistré et n'annule pas l'action (test).
  - CA-2 (refus de droit) : lecture par agent L1 non initiateur : 403.
  - CA-3 (isolation tenant) : notification d'une commande du tenant B lue par un agent du tenant A : 403.
  - CA-4 : le contenu d'une notification ne contient pas de charge utile brute (test de projection).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/notifications/admin_notifications.py`.
- Source : contrat-intervention-et-journal-audit.md#Contrat d'une commande opérateur (Notification) ; 02-autorites-actions-et-controles.md#4 (référence croisée)

### BE-145 — Compteurs d'exploitation de la console
- Domaine : Exploitation (observabilité)
- Vague : 11
- Routes :
  - NON DÉFINI ; route proposée :
  - `GET /api/v1/admin/ops/metrics`
- Tables / migrations : aucune table propre ; compteurs : commandes, erreurs, résultats inconnus, refus d'autorisation, previews expirées, durée de propagation, échec ou doublon de webhook, intégration dégradée, notification non délivrée. Seuils et alertes : NON DÉFINI (PH-16).
- Droits : lecture par opérateur plateforme et sécurité ; refus 403 pour les autres rôles ; réponse sans charge utile sensible.
- Dépendances : BE-122, BE-124, BE-241
- Critères d'acceptation :
  - CA-1 (refus de droit) : lecture par agent L1 : 403.
  - CA-2 : la réponse ne contient aucune charge utile ni secret (test de projection).
  - CA-3 : aucun seuil ni alerte n'est codé en dur (test : absence de constante de seuil).
  - CA-4 (isolation tenant) : compteurs filtrables par tenant seulement pour un rôle de portée plateforme ; un rôle tenant reçoit 403.
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/ops_metrics.py`.
- Source : 02-autorites-actions-et-controles.md#6 Observabilité (référence croisée) ; PH-12#Critères d'acceptation

### BE-146 — Révocation et fin de fenêtre des droits temporaires
- Domaine : Autorisation et portée (administration)
- Vague : 9
- Routes :
  - NON DÉFINI ; route proposée :
  - `POST /api/v1/admin/role-assignments/{assignment_id}/revoke`
- Tables / migrations : `admin_role_assignment` (revokedAt, revokedBy). Expiration automatique à `expiresAt`.
- Droits : révocation par administrateur global ; expiration sans action humaine ; refus 403 ; compte partagé interdit (recommandation, QE-ADM-15).
- Dépendances : BE-121 ; EXT non résolu : mandat et fenêtre des prestataires de support (PH-08) ; NON DÉFINI : Recommandation appliquée : aucune fenêtre par défaut, l'affectation tierce exige une échéance | QE-ADM-25
- Critères d'acceptation :
  - CA-1 : après `expiresAt` l'accès est refusé (403) sans action humaine (test temporel).
  - CA-2 (refus de droit) : révocation par agent L1 : 403.
  - CA-3 : une affectation sur identité partagée est refusée (422).
  - CA-4 : la révocation crée un événement d'audit et ne supprime pas l'affectation (test de présence et d'intégrité).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/rbac/role_revocation.py`.
- Source : 02-autorites-actions-et-controles.md#2 (support tiers) ; contrat-intervention-et-journal-audit.md#Classes de commande sensibles à arbitrer (élévation temporelle) ; PH-12#Démarche pas à pas (étape 8, révocation)

### BE-147 — Garde transversale anti cross-tenant
- Domaine : Autorisation et portée (transverse)
- Vague : 8
- Routes : aucune (intergiciel appliqué à toutes les routes des tâches BE-121 à BE-146)
- Tables / migrations : aucune.
- Droits : toute ressource d'un tenant est accessible uniquement si la portée de l'appelant le couvre ; accès cross-tenant hors portée plateforme explicite : 403 ; exception : BLOCKED (Q-06, PH-16).
- Dépendances : BE-120, BE-122 ; EXT non résolu : décision BLOCKED sur l'accès cross-tenant (PH-16), voir QE-ADM-06
- Critères d'acceptation :
  - CA-1 (isolation tenant) : jeu de données à deux tenants ; chaque route d'administration testée avec l'affectation du tenant A sur les ressources du tenant B : 403 sur toutes.
  - CA-2 (refus de droit) : route sans affectation : 403 (test de couverture de toutes les routes).
  - CA-3 : toute route d'administration déclare sa portée ; une route sans portée déclarée échoue le test de build.
  - CA-4 : chaque refus cross-tenant produit un événement d'audit (test de présence).
- Documentation attendue : docstrings ; doc de module. Module prévu : NON DÉFINI ; recommandation : `app/operator/tenant_guard.py`.
- Source : contrat-intervention-et-journal-audit.md#Questions et état (accès cross-tenant BLOCKED) ; 02-autorites-actions-et-controles.md#1 (principes)

---

## Points ouverts

- Question : Dans quelles capacités réelles de develop rattacher les modules d'administration, sachant que `app/administration/` n'existe pas ?
  - NON DÉFINI : Recommandation appliquée : `app/operator/` pour la console de support et d'intervention, `app/rbac/` pour les affectations et révocations, `app/audit/` pour le journal, `app/notifications/` pour les notifications ; aucune nouvelle capacité créée | QE-ADM-26
- Question : Les champs de BE-122 (`occurredAtUtc`, `category`, `reasonTicket`, `initiatorId`, `approverId`, `stateBeforeRef`, `stateAfterRef`, `notificationStatus`, `windowDuration`, `actorService`, `authContext`) ne figurent pas dans `audit_event` de BE-007 (`organizationId` NOT NULL, `request_id`, `result` success | refused | error) : faut-il demander ces colonnes à BE-007, et `organizationId` peut-il être NULL pour un événement de portée plateforme ?
  - NON DÉFINI : Recommandation appliquée : BE-122 consomme les colonnes de `audit_event` telles que listées dans BE-007 ; chaque colonne manquante est demandée à BE-007 par la phrase « colonne demandée à BE-007 : <nom> » et n'est pas créée par BE-122 ; `organizationId` NULL accepté pour la seule portée plateforme, à valider par BE-007 | QE-ADM-27
- Question : Quels codes exacts (rôles globaux et permissions) doivent être attribués aux sept rôles candidats ?
  - NON DÉFINI : Recommandation appliquée : utiliser les rôles candidats de la matrice (agent L1, agent L2, finance, opérateur, sécurité, approbateur, auditeur) comme codes provisoires, sans aucune permission accordée par défaut | QE-ADM-01
- Question : Quelles informations sont visibles par défaut pour un agent support L1 ?
  - NON DÉFINI : Recommandation appliquée : L1 voit statuts normalisés, membership et diagnostic non contentieux ; facture et paiement masqués, comme dans la matrice | QE-ADM-02
- Question : Une affectation temporaire doit-elle toujours porter une échéance ?
  - NON DÉFINI : Recommandation appliquée : une échéance `expiresAt` est obligatoire pour tout rôle temporaire, sinon 422 | QE-ADM-03
- Question : Quels niveaux d'astreinte existent ?
  - NON DÉFINI : Recommandation appliquée : aucune astreinte codée ; l'escalade est manuelle via BE-142 | QE-ADM-04
- Question : Quelles actions exigent une double validation ?
  - NON DÉFINI : Recommandation appliquée : double validation pour suspension, changement d'entitlement, action financière, export ou suppression, accès exceptionnel et correction d'événement, selon la matrice | QE-ADM-05
- Question : Quel accès au contenu client est autorisé en cas d'urgence (Q-06) ?
  - NON DÉFINI : Recommandation appliquée : aucun accès ; toute demande reçoit 403 (BE-138, statut BLOCKED) | QE-ADM-06
- Question : Quels délais et durées (SLA, expiration de preview, fenêtre d'approbation) s'appliquent ?
  - NON DÉFINI : Recommandation appliquée : aucune valeur codée ; `expiresAt` de preview et fenêtre d'approbation sont des paramètres sans défaut, et leur absence bloque la création de la preview | QE-ADM-07
- Question : Quelle politique de paiement, d'impayé et de suspension (Q-05) et quel PSP s'appliquent ?
  - NON DÉFINI : Recommandation appliquée : aucune suspension automatique ni appel PSP ; seules des commandes manuelles avec preview et double validation sont créées | QE-ADM-08
- Question : Quelle conception de l'enregistrement de la preview et de son invalidation (expiration ou changement de version) est retenue ?
  - NON DÉFINI : Recommandation appliquée : toute preview porte `expiresAtUtc` NOT NULL et `stateSnapshotHash`, et est invalidée à la première différence de hash (BE-125) | QE-ADM-09
- Question : Quelles règles de rétention, d'immutabilité technique et de lecture du journal d'audit s'appliquent (PH-13/PH-16) ?
  - NON DÉFINI : Recommandation appliquée : append-only applicatif sans route de modification ni suppression ; lecture par le seul rôle auditeur ; durée de rétention non codée | QE-ADM-10
- Question : Le contrat technique (enveloppe d'événement et format des erreurs) est-il approuvé (PH-14) ?
  - NON DÉFINI : Recommandation appliquée : utiliser l'enveloppe de commande de la section « Contrat d'une commande opérateur » et les codes 401, 403, 409, 422 de l'en-tête | QE-ADM-11
- Question : Quels niveaux d'escalade et quelles cibles existent ?
  - NON DÉFINI : Recommandation appliquée : deux niveaux provisoires (L2, responsable d'escalade), dont la fermeture est réservée au responsable | QE-ADM-12
- Question : Un refus cross-tenant doit-il renvoyer 403 ou 404 (masquage d'existence) ?
  - NON DÉFINI : Recommandation appliquée : 403 partout dans ce lot pour rester uniforme avec le reste des refus de droit | QE-ADM-13
- Question : Quelles valeurs de priorité et de qualification de cas sont retenues ?
  - NON DÉFINI : Recommandation appliquée : enum fermé `basse | normale | haute` pour la priorité ; qualification libre normalisée, sans liste fermée | QE-ADM-14
- Question : Un compte partagé peut-il recevoir un droit temporaire de support tiers ?
  - NON DÉFINI : Recommandation appliquée : non ; toute identité partagée est refusée (422) | QE-ADM-15
- Question : Quelle taille maximale de page pour les listes de support ?
  - NON DÉFINI : Recommandation appliquée : pagination obligatoire avec taille par défaut et maximale non codées, paramètre requis | QE-ADM-16
- Question : Les canaux et destinataires de notification (PH-13) sont-ils arbitrés ?
  - NON DÉFINI : Recommandation appliquée : la notification est un enregistrement avec statut ; canal et destinataire restent des valeurs de configuration | QE-ADM-17
- Question : Quels seuils d'alerte et quels SLA d'observabilité (PH-16) s'appliquent ?
  - NON DÉFINI : Recommandation appliquée : aucun seuil ni alerte codé (BE-145 CA-3) | QE-ADM-18
- Question : Combien de reprises sont permises après un résultat inconnu ?
  - NON DÉFINI : Recommandation appliquée : aucune reprise automatique ; une reprise unique manuelle après réconciliation, avec la même clé | QE-ADM-19
- Question : Quel est le statut de la notion de santé ou réputation du tenant (PH-01A) ?
  - NON DÉFINI : Recommandation appliquée : champ absent de toute réponse et marqué N/A dans la synthèse (BE-130 CA-4) | QE-ADM-20
- Question : Le contrôle d'accès opérateur existant (liste d'identifiants `OPERATOR_READ_USER_IDS`, `app/operator/permissions.py`) est-il conservé à côté de la portée plateforme ?
  - NON DÉFINI : Recommandation appliquée : remplacement complet par la portée plateforme de BE-120 à la livraison ; la liste d'environnement n'accorde plus aucun accès | QE-ADM-21
- Question : Quel domaine propriétaire (PH-07 à PH-10, PH-13, PH-14, PH-16) exécute, vérifie ou invalide chaque effet de commande, quand plusieurs objets candidats existent ?
  - NON DÉFINI : Recommandation appliquée : chaque effet est appelé chez le domaine qui possède l'objet (abonnement, paiement, facture, entitlement, tenant) ; tant que le propriétaire n'est pas désigné, la tâche concernée reste EXT non résolu et ne démarre pas | QE-ADM-22
- Question : Quelle fraîcheur d'authentification est exigée pour confirmer une commande sensible (PH-08) ?
  - NON DÉFINI : Recommandation appliquée : une authentification récente est exigée à la confirmation ; durée non codée, à fixer par la politique | QE-ADM-23
- Question : Un cache d'entitlements existe-t-il dans le plan, et quel événement d'invalidation le vide (PH-14) ?
  - NON DÉFINI : Recommandation appliquée : aucun cache n'est introduit par ce lot ; BE-135 émet un événement d'invalidation nommé par le domaine propriétaire des entitlements | QE-ADM-24
- Question : Quelles sont la durée et la fenêtre du mandat d'un prestataire de support tiers (PH-08) ?
  - NON DÉFINI : Recommandation appliquée : pas de fenêtre implicite ; l'affectation tierce exige une échéance `expiresAt` explicite, sinon 422 | QE-ADM-25
- Question : Les noms de tables gardent-ils la casse décidée (`audit_event`, `subscription_entitlement`) ou suivent-ils la convention camelCase du CLAUDE.md du backend ?
  - NON DÉFINI : Recommandation appliquée : snake_case pour tous les noms de tables (décision du coordinateur A) ; `audit_event` et `subscription_entitlement` déjà conformes ; `auditLog` renommé `audit_log` dans les lignes « Tables / migrations » de BE-122 ; les noms existants de develop (`auditLog`, `operatorAuditLog`, lignes « Code existant ») ne sont pas renommés car ils décrivent le code actuel, à trancher lors de la migration | QE-ADM-28
