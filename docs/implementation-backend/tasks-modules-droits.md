# Tâches back-end : modules, catalogue, activation et droits

- **Domaine :** Modules, catalogue, activation, entitlements, droits (PH-09)
- **Périmètre :** back-end du socle Zylo Office uniquement (aucun module métier, aucun front-end)
- **Sources lues (dans `definition-travail/`) :**
  - `00-pilotage/architecture-fondation/phases/PH-09-modules-catalogue-activation-droits.md` (intégralité)
  - `00-pilotage/architecture-fondation/matrice-etats-modules-et-droits.md` (intégralité)
  - `00-pilotage/architecture-fondation/matrice-cap-par-ph-vers-composants.md` (lignes CAP-FOUND-001 à 018, CAP-IDENT-001, CAP-COMMERCE-001 à 013, CAP-TRANSVERSE-005, par grep puis lecture ciblée)
- **Plage d'identifiants :** BE-040 à BE-061 (22 tâches, sans trou)
- **Statut :** provisoire. Aucune route, table ni permission n'est définie dans les sources : toute valeur marquée « NON DÉFINI » est une recommandation appliquée, à reprendre si une décision ultérieure la remplace (points ouverts QE-MOD-01 à QE-MOD-25).
- **Convention transverse :** les routes sont préfixées par `/api/v1` et portent le tenant dans le chemin (`/api/v1/organizations/{orgId}/...`) ; le tenant n'est jamais déduit d'un identifiant transmis dans le corps (matrice-etats, invariant 1).

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-040 | Schéma du catalogue de modules et de ses versions | 0 | BE-002 |
| BE-041 | Machine à états générique et journal de transitions | 0 | BE-040 |
| BE-042 | Enregistrement et publication des versions de module | 4 | BE-040, BE-041 |
| BE-043 | Consultation du catalogue avec visibilité | 2 | BE-042 |
| BE-044 | Compatibilité, dépendances et plan de mise à jour | 2 | BE-042 |
| BE-045 | Entitlements organisation (source, période, quota) | 1 | BE-040, BE-023, BE-024 |
| BE-046 | Allocation des entitlements aux utilisateurs (sièges) | 2 | BE-045, BE-024 |
| BE-047 | Installation technique tenant-module | 2 | BE-041, BE-042, BE-044 |
| BE-048 | Disponibilité tenant-module (activation et désactivation) | 3 | BE-045, BE-047 |
| BE-049 | Suspension et reprise d'un module | 2 | BE-048 |
| BE-050 | Désinstallation sans purge des données | 1 | BE-048 |
| BE-051 | Mise à jour de version rN vers rN+1 | 1 | BE-044, BE-047 |
| BE-052 | Réconciliation des états incertains | 2 | BE-045, BE-047 |
| BE-053 | Moteur d'accessibilité effective | 1 | BE-004, BE-005, BE-008, BE-009, BE-045, BE-046, BE-048 |
| BE-054 | Application du moteur aux routes API | 0 | BE-053 |
| BE-055 | Permissions déclarées par module | 1 | BE-005, BE-008, BE-009, BE-042 |
| BE-056 | Événements et audit des transitions de module | 1 | BE-007, BE-041 |
| BE-057 | Notifications de suspension, fin et changement d'état | 0 | BE-049, BE-056 |
| BE-058 | Liaison facturation vers entitlements | 1 | BE-023, BE-024, BE-045, BE-082 |
| BE-059 | Périodes, expiration et effet d'accès | 0 | BE-024, BE-045, BE-053 |
| BE-060 | Suite de tests d'isolation et de refus pour les modules | 0 | BE-046, BE-050, BE-054, BE-059 |
| BE-061 | Documentation des modules et des routes | 0 | BE-060, BE-222 |

## Tâches

### BE-040 — Schéma du catalogue de modules et de ses versions
- Domaine : Modules / catalogue
- Vague : 3
- Routes : aucune
- Tables / migrations : NON DÉFINI (QE-MOD-15, QE-MOD-20). Recommandation appliquée : table `modules` (`id` UUID, `slug` unique, `name`, `description`, `publicationState` enum `draft|review|published|deprecated|withdrawn|quarantined`, `visibility` enum `hidden|visible|restricted`, `createdAt`, `updatedAt`) ; table `module_versions` (`id`, `moduleId` FK, `version` semver, `digest`, `provenance`, `licence`, `compatibility` JSON, `prerequisites` JSON, `stateVersion` entier, `publishedAt` nullable, contrainte unique `(moduleId, version)`). Une version publiée est immuable (matrice-etats, section 2).
- Droits : aucun (schéma seul). Portée plateforme.
- Dépendances : BE-002
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la migration crée les deux tables, les enums et les contraintes d'unicité `slug` et `(moduleId, version)`.
  - CA-2 : une tentative de modifier `digest` ou `compatibility` d'une version `published` est rejetée par la couche service (erreur `MODULE_VERSION_IMMUTABLE`).
  - CA-3 : une version sans `digest` ni `provenance` ne peut pas passer à l'état `published` (test unitaire sur la fonction de transition).
  - CA-4 : la migration est réversible (aller-retour sur base de test jetable `zylo_t040_test`).
- Documentation attendue : docstrings de chaque modèle et enum ; doc de module `implementation-backend/doc/modules/catalogue.md` (chemin prévu).
- Source : PH-09-modules-catalogue-activation-droits.md#Critères d'acceptation ; matrice-etats-modules-et-droits.md#1. Axes orthogonaux

### BE-041 — Machine à états générique et journal de transitions
- Domaine : Socle transverse des états (modules)
- Vague : 4
- Routes : aucune
- Tables / migrations : table `module_state_transitions` (`id`, `subjectType`, `subjectId`, `fromState`, `toState`, `actorId`, `organizationId` nullable, `origin` enum `client|commercial|security|support|automation|platform`, `reason`, `operationId` UUID, `idempotencyKey`, `stateVersionBefore`, `stateVersionAfter`, `createdAt`). Index unique `(subjectType, subjectId, idempotencyKey)`.
- Droits : aucun droit propre ; l'appelant fournit l'acteur. Une transition sans acteur identifié est refusée.
- Dépendances : BE-040
- Critères d'acceptation :
  - CA-1 : une transition absente de la table des transitions autorisées (ex. `not_installed -> active`) est refusée avec `MODULE_TRANSITION_NOT_ALLOWED` (HTTP 409) et ne crée aucune ligne.
  - CA-2 : rejouer une commande avec la même `idempotencyKey` renvoie le résultat initial sans second effet (test d'idempotence).
  - CA-3 : une commande dont `stateVersion` attendue diffère de la version courante est refusée (HTTP 409, `MODULE_STATE_VERSION_CONFLICT`).
  - CA-4 : toute transition réussie écrit une ligne de journal avec acteur, origine, `operationId`.
  - CA-5 : une commande sans acteur authentifié est refusée (HTTP 401).
- Documentation attendue : docstrings de la fonction de transition et de la table des transitions ; doc `implementation-backend/doc/modules/machine-etats.md`.
- Source : matrice-etats-modules-et-droits.md#2. Transitions candidates et défauts connus ; #Pré/postconditions communes ; #Invariants sécurité 7

### BE-042 — Enregistrement et publication des versions de module
- Domaine : Modules / catalogue plateforme (CAP-FOUND-013)
- Vague : 5
- Routes :
  - NON DÉFINI (QE-MOD-01 : console plateforme rattachée à /api/v1/admin) — recommandation appliquée :
  - `POST /api/v1/admin/modules` (crée une fiche en `draft`)
  - `POST /api/v1/admin/modules/{moduleId}/versions` (crée une version en `draft`)
  - `POST /api/v1/admin/modules/{moduleId}/versions/{versionId}/publish` (passe `review` puis `published`, corps : `stateVersion`)
  - `GET /api/v1/admin/modules/{moduleId}` (lecture plateforme)
- Tables / migrations : aucune nouvelle table (utilise BE-040, BE-041).
- Droits : permission NON DÉFINI (QE-MOD-16). Recommandation : `platform.module.publish` pour la publication, `platform.module.write` pour la création. Portée plateforme, sans tenant. Refus : HTTP 403 `PERMISSION_DENIED`. Acteur non authentifié : HTTP 401.
- Dépendances : BE-040, BE-041
- Critères d'acceptation :
  - CA-1 : un acteur sans `platform.module.publish` reçoit 403 sur la publication, et la version reste `review`.
  - CA-2 : publier une version sans `digest` ou sans provenance renvoie HTTP 422 `MODULE_VERSION_INCOMPLETE`.
  - CA-3 : publier une version déjà `published` renvoie HTTP 409 (idempotence : même résultat si même `idempotencyKey`).
  - CA-4 : la publication écrit un événement `ModuleVersionPublished` avec acteur et `correlationId` (test sur la sortie de BE-056).
  - CA-5 : une version non conforme passe à `draft` avec motif conservé (transition de rejet).
- Documentation attendue : docstrings des fonctions de service et des handlers de route ; doc `implementation-backend/doc/modules/catalogue.md`.
- Source : PH-09-modules-catalogue-activation-droits.md#Objectif ; matrice-etats-modules-et-droits.md#2 (ligne « Fiche → visible/publiée » ; « Non conforme → rejet/retour review »)

### BE-043 — Consultation du catalogue avec visibilité
- Domaine : Catalogue (CAP-FOUND-011, CAP-FOUND-016)
- Vague : 6
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `GET /api/v1/catalog/modules` (liste des modules `published` et `visible`)
  - `GET /api/v1/catalog/modules/{slug}` (fiche)
- Tables / migrations : aucune (lecture de `modules`, `module_versions`).
- Droits : lecture publique pour `visibility = visible` ; `restricted` exige une règle d'audience NON DÉFINIE (QE-MOD-12), donc refusée par défaut. Un module `hidden` ou inconnu renvoie HTTP 404 (non révélateur). Pas de tenant dans ces routes.
- Dépendances : BE-042
- Critères d'acceptation :
  - CA-1 : un visiteur anonyme obtient uniquement les modules `published` et `visible` (test sur jeu de données mixte).
  - CA-2 : une fiche `hidden` renvoie 404 identique à une fiche inexistante (même corps, même code).
  - CA-3 : une fiche `restricted` renvoie 403 `MODULE_AUDIENCE_RESTRICTED` pour un visiteur sans audience (QE-MOD-12).
  - CA-4 : la fiche n'expose aucune donnée de version `draft`, `review` ou `quarantined` (test de non-fuite).
- Documentation attendue : docstrings publiques ; doc `implementation-backend/doc/modules/catalogue.md`.
- Source : PH-09-modules-catalogue-activation-droits.md#Démarche pas à pas (étape 2, catégories et fiches) ; matrice-etats-modules-et-droits.md#1 (axe « Visibilité de fiche »)

### BE-044 — Compatibilité, dépendances et plan de mise à jour
- Domaine : Modules / compatibilité (CAP-FOUND-015)
- Vague : 6
- Routes :
  - NON DÉFINI (QE-MOD-01 : console plateforme rattachée à /api/v1/admin) — recommandation appliquée :
  - `POST /api/v1/admin/modules/{moduleId}/versions/{versionId}/compatibility-evaluations` (évalue compatibilité et graphe de dépendances, renvoie `compatible|incompatible|unknown` avec motifs)
  - `POST /api/v1/admin/modules/{moduleId}/upgrade-plans` (corps : `fromVersion`, `toVersion` ; renvoie le plan, sans l'exécuter)
- Tables / migrations : table `module_compatibility_evaluations` (`id`, `moduleVersionId`, `result`, `reasons` JSON, `evaluatedAt`) et `module_upgrade_plans` (`id`, `moduleId`, `fromVersion`, `toVersion`, `steps` JSON, `rollbackPossible` boolean, `forwardOnly` boolean).
- Droits : `platform.module.publish` pour évaluer ; même portée plateforme. Refus : 403 `PERMISSION_DENIED`.
- Dépendances : BE-042
- Critères d'acceptation :
  - CA-1 : un cycle dans le graphe de dépendances produit `incompatible` avec motif `DEPENDENCY_CYCLE` (test unitaire).
  - CA-2 : une dépendance absente produit `incompatible` avec motif `PREREQUISITE_MISSING`.
  - CA-3 : une version sans information de compatibilité produit `unknown`, jamais `compatible` (règle « ne pas inventer un état positif »).
  - CA-4 : un acteur sans permission reçoit 403 et aucune évaluation n'est créée.
  - CA-5 : un plan avec `rollbackPossible = false` est marqué `forwardOnly` ; aucun rollback n'est proposé automatiquement.
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/compatibilite.md`.
- Source : matrice-cap-par-ph-vers-composants.md (CAP-FOUND-015, critère canonique « versions source/cible, compatibilité, échec de migration et retour arrière ») ; matrice-etats-modules-et-droits.md#2 (« Installed rN -> rN+1 »)

### BE-045 — Entitlements organisation (source, période, quota)
- Domaine : Entitlements / droits (CAP-COMMERCE-008)
- Vague : 5
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `GET /api/v1/organizations/{orgId}/entitlements` (liste des entitlements de l'organisation, avec état, source, période, limite)
- Tables / migrations : aucune table `entitlements` (D3). La table unique `subscription_entitlement` appartient à BE-024 ; BE-045 y ajoute les colonnes suivantes : `organizationId` FK, `moduleId` FK, `capability` NON DÉFINI, `scope` enum `organization|user`, `source` enum `plan|paid_option|trial|authorized_allocation` (QE-MOD-13), `state` enum `none|granted|limited|suspended|expired|reconciliation_required`, `quotaLimit` entier nullable, `quotaUnit` NON DÉFINI (QE-MOD-04), `periodStart`, `periodEnd` nullable, `stateVersion`, `createdAt`. Index sur `(organizationId, moduleId)`.
- Droits : `organization.entitlement.read` (NON DÉFINI, QE-MOD-16), portée organisation `{orgId}` ; membre actif requis (BE-053). Refus : 403 ; organisation d'un autre tenant : 404.
- Dépendances : BE-040, BE-023, BE-024 (BE-024 possède la table `subscription_entitlement`)
- Critères d'acceptation :
  - CA-1 : la migration ajoute à `subscription_entitlement` les colonnes, enums et l'index décrits ci-dessus.
  - CA-2 : un membre sans `organization.entitlement.read` reçoit 403 ; l'absence de lecture ne révèle pas l'existence de l'organisation.
  - CA-3 : test d'isolation : un utilisateur membre de l'organisation A appelant `/api/v1/organizations/B/entitlements` reçoit 404 et aucune donnée de B.
  - CA-4 : un entitlement sans `source` ou sans `scope` ne peut pas être créé (422).
  - CA-5 : une valeur de `quotaUnit` absente renvoie `quotaUnit: null` et ne déclenche pas de valeur par défaut inventée.
- Documentation attendue : docstrings du modèle et de la route ; doc `implementation-backend/doc/modules/entitlements.md`.
- Source : matrice-etats-modules-et-droits.md#1 (état « Entitlement », source/propriétaire) ; PH-09-modules-catalogue-activation-droits.md#Démarche pas à pas (étape 4, matrice offre → quota → niveau org/user)

### BE-046 — Allocation des entitlements aux utilisateurs (sièges)
- Domaine : Entitlements / allocation
- Vague : 6
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/organizations/{orgId}/entitlements/{entitlementId}/allocations` (corps : `userId`, `stateVersion`)
  - `DELETE /api/v1/organizations/{orgId}/entitlements/{entitlementId}/allocations/{userId}` (révocation)
- Tables / migrations : table `entitlement_allocations` (`id`, `entitlementId` FK vers `subscription_entitlement`, `organizationId`, `userId`, `grantedBy`, `grantedAt`, `revokedAt` nullable, contrainte unique `(entitlementId, userId)` sur les lignes actives). Dénormalisation interdite : `organizationId` est vérifié contre `entitlements.organizationId`.
- Droits : `organization.entitlement.allocate` (NON DÉFINI, QE-MOD-16) ; attribution et révocation ont des permissions distinctes. Acteur de l'organisation uniquement. Refus : 403 `PERMISSION_DENIED`. Dépassement de siège : 409 `ENTITLEMENT_SEAT_LIMIT_REACHED` (QE-MOD-04 : règle de dépassement NON DÉFINIE, refus par défaut).
- Dépendances : BE-045, BE-024 (propriétaire de `subscription_entitlement`, cible de la FK)
- Critères d'acceptation :
  - CA-1 : allouer au-delà de `quotaLimit` renvoie 409 et ne crée aucune ligne.
  - CA-2 : un acteur sans `organization.entitlement.allocate` reçoit 403.
  - CA-3 : test d'isolation : allouer un entitlement de l'organisation A en passant `orgId = B` renvoie 404 ; un `userId` non membre de A renvoie 422.
  - CA-4 : révoquer une allocation la rend inactive sans supprimer la ligne (`revokedAt` renseigné) et déclenche l'événement de changement (BE-056).
  - CA-5 : deux allocations simultanées sur le dernier siège : une seule réussit (test de concurrence, verrou sur l'entitlement).
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/entitlements.md`.
- Source : PH-09-modules-catalogue-activation-droits.md#Démarche pas à pas (étape 5, attribution/révocation, sièges, dépassement) ; matrice-etats-modules-et-droits.md#1 (« Entitlement » : scope)

### BE-047 — Installation technique tenant-module
- Domaine : Modules / installation
- Vague : 7
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/installations` (en-tête `Idempotency-Key` obligatoire ; corps : `moduleVersionId`, `stateVersion`)
  - `GET /api/v1/organizations/{orgId}/modules/{moduleId}/installations/{operationId}` (relecture d'une opération, pour un résultat incertain)
- Tables / migrations : table `module_installations` (`id`, `organizationId`, `moduleId`, `moduleVersionId`, `state` enum `not_installed|preflight|provisioning|installed|failed|removing|removed`, `stateVersion`, `operationId` UUID, `lastErrorCode` nullable, `updatedAt`). Contrainte : une seule installation non `removed` par `(organizationId, moduleId)`.
- Droits : `organization.module.install` (NON DÉFINI, QE-MOD-16), portée organisation `{orgId}`. Vérifications préalables : version `published` (BE-042), compatibilité `compatible` (BE-044), prérequis installés. Refus : 403 ; version non publiée : 422 `MODULE_VERSION_NOT_PUBLISHED` ; prérequis absent : 409 `MODULE_PREREQUISITE_MISSING`.
- Dépendances : BE-041, BE-042, BE-044
- Critères d'acceptation :
  - CA-1 : la séquence `not_installed -> preflight -> provisioning -> installed` est produite par un test de bout en bout du service avec un fournisseur d'exécution simulé.
  - CA-2 : un échec pendant `provisioning` place l'installation en `failed` avec `lastErrorCode` ; aucun passage à `active` (BE-048) n'est possible (test).
  - CA-3 : rejouer le même `Idempotency-Key` ne crée pas une seconde opération et renvoie le même `operationId`.
  - CA-4 : un acteur sans `organization.module.install` reçoit 403 et aucune ligne n'est créée.
  - CA-5 : test d'isolation : installer dans `orgId = B` avec un acteur de A renvoie 404 ; une installation de A n'apparaît pas dans la lecture de B.
  - CA-6 : une version incompatible (BE-044 `incompatible`) renvoie 409 et aucune étape de preflight n'est exécutée.
- Documentation attendue : docstrings du service et des handlers ; doc `implementation-backend/doc/modules/installation.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Eligible → install request », « Not installed → preflight → provisioning », « Provisioning → installed ») ; matrice-etats-modules-et-droits.md#1 (« Installation technique ») ; #Pré/postconditions communes

### BE-048 — Disponibilité tenant-module (activation et désactivation)
- Domaine : Modules / disponibilité (CAP-FOUND-014)
- Vague : 8
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/activation` (corps : `stateVersion`, `confirm: true`)
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/deactivation` (corps : `stateVersion`, `confirm: true`)
  - `GET /api/v1/organizations/{orgId}/modules/{moduleId}` (état de disponibilité et explication)
- Tables / migrations : colonnes `availabilityState` enum `inactive|activation_pending|active|suspending|suspended|deactivation_pending|inactive_error` et `availabilityStateVersion` ajoutées à `module_installations` (ou table `tenant_module_availability` si QE-MOD-03 la sépare).
- Droits : `organization.module.activate` (NON DÉFINI, QE-MOD-16). Gardes avant activation : installation `installed`, entitlement valide si la capacité l'exige (BE-045, BE-053), dépendances actives, confirmation explicite. Refus : 403 ; garde en échec : 409 `MODULE_ACTIVATION_GUARD_FAILED` avec le nom de la garde ; l'état reste `inactive`.
- Dépendances : BE-045, BE-047
- Critères d'acceptation :
  - CA-1 : activer une installation non `installed` renvoie 409 et l'état reste inchangé.
  - CA-2 : activer sans entitlement valide (capacité exigeant un entitlement) renvoie 409 `ENTITLEMENT_REQUIRED` et l'état reste `inactive` (aucun accès implicite).
  - CA-3 : un acteur sans `organization.module.activate` reçoit 403.
  - CA-4 : désactiver un module dont un module dépendant est `active` renvoie 409 `MODULE_HAS_ACTIVE_DEPENDANTS` (liste des dépendants dans le corps).
  - CA-5 : une panne pendant `activation_pending` place l'état en `inactive_error` et la relecture renvoie l'état exact, jamais `active` par défaut.
  - CA-6 : test d'isolation : activer dans `orgId = B` avec un acteur de A renvoie 404.
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/disponibilite.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Installed/inactive -> active », « Active -> inactive ») ; #1 (« Disponibilité technique tenant-module ») ; #3 (formule d'accès)

### BE-049 — Suspension et reprise d'un module
- Domaine : Modules / suspension
- Vague : 9
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/suspensions` (corps : `origin` parmi `client|commercial|security`, `reason`, `stateVersion`)
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/reactivations` (corps : `stateVersion`, `resolutionReference`)
- Tables / migrations : colonnes `suspensionOrigin`, `suspensionReason`, `suspendedBy` sur la ligne de disponibilité ; aucune nouvelle table.
- Droits : `organization.module.suspend` pour `client` ; `platform.module.suspend` pour `commercial` et `security` (NON DÉFINI, QE-MOD-07/16). Refus : 403. La reprise revalide la release, l'entitlement et la permission (matrice-etats, section 2).
- Dépendances : BE-048
- Critères d'acceptation :
  - CA-1 : une suspension sans `origin` ou sans `reason` renvoie 422.
  - CA-2 : un acteur client ne peut pas poser une suspension `security` (403).
  - CA-3 : pendant `suspending` ou `suspended`, une mutation sensible du module est refusée (409 `MODULE_SUSPENDED`) ; la lecture reste disponible (règle de lecture NON DÉFINIE, QE-MOD-06, lecture autorisée par défaut).
  - CA-4 : la reprise échoue (409) si l'entitlement n'est plus `granted` (BE-045) ; l'état reste `suspended`.
  - CA-5 : une reprise avec `stateVersion` obsolète renvoie 409 (BE-041).
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/disponibilite.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Active -> suspended », « Suspended -> active ») ; #3 (effets des suspensions BLOCKED Q-04/05)

### BE-050 — Désinstallation sans purge des données
- Domaine : Modules / désinstallation
- Vague : 9
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `DELETE /api/v1/organizations/{orgId}/modules/{moduleId}/installation` (en-tête `Idempotency-Key` ; corps : `stateVersion`, `confirm: true`)
- Tables / migrations : aucune nouvelle table ; passage `installed|inactive -> removing -> removed` dans `module_installations`.
- Droits : `organization.module.uninstall` (NON DÉFINI, QE-MOD-16), distinct de l'activation. Refus : 403. Module `active` : 409 `MODULE_MUST_BE_INACTIVE` (désactivation d'abord, BE-048).
- Dépendances : BE-048
- Critères d'acceptation :
  - CA-1 : désinstaller un module `active` renvoie 409 et ne change aucun état.
  - CA-2 : après `removed`, les lignes de données du module restent présentes (test : compte des lignes identique) ; aucune purge n'est exécutée (QE-MOD-11).
  - CA-3 : un acteur sans `organization.module.uninstall` reçoit 403 même s'il peut désactiver.
  - CA-4 : rejouer la même `Idempotency-Key` ne déclenche pas de second passage en `removing`.
  - CA-5 : test d'isolation : désinstaller dans `orgId = B` avec un acteur de A renvoie 404.
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/installation.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Installed/inactive -> removing -> removed » ; « Retention PH-13/14/16 ») ; #4 invariant 8

### BE-051 — Mise à jour de version rN vers rN+1
- Domaine : Modules / mise à jour
- Vague : 8
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/organizations/{orgId}/modules/{moduleId}/upgrades` (en-tête `Idempotency-Key` ; corps : `targetModuleVersionId`, `stateVersion`)
- Tables / migrations : colonnes `upgradeTargetVersionId` et `upgradeState` sur `module_installations` ; le plan est lu depuis `module_upgrade_plans` (BE-044).
- Droits : `organization.module.upgrade` (NON DÉFINI, QE-MOD-16). Refus : 403 ; plan absent ou `incompatible` : 409 `MODULE_UPGRADE_NOT_ALLOWED` ; plan `forwardOnly` sans confirmation explicite : 409 `MODULE_UPGRADE_FORWARD_ONLY`.
- Dépendances : BE-044, BE-047
- Critères d'acceptation :
  - CA-1 : une mise à jour vers une version non publiée renvoie 422.
  - CA-2 : une mise à jour incompatible renvoie 409 et l'installation reste sur la version source.
  - CA-3 : un échec de migration laisse la version source active de façon cohérente et pose `failed` ; aucun rollback automatique hors plan prouvé.
  - CA-4 : un acteur sans `organization.module.upgrade` reçoit 403.
  - CA-5 : test d'isolation : mettre à jour dans `orgId = B` avec un acteur de A renvoie 404.
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/installation.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Installed rN -> rN+1 ») ; PH-09-modules-catalogue-activation-droits.md#Démarche pas à pas (étape 5, changement d'offre)

### BE-052 — Réconciliation des états incertains
- Domaine : Modules / réconciliation
- Vague : 8
- Routes :
  - NON DÉFINI (QE-MOD-01 : console plateforme rattachée à /api/v1/admin) — recommandation appliquée :
  - `GET /api/v1/admin/reconciliations?state=open` (liste des cas `reconciliation_required` et `unknown`)
  - `POST /api/v1/admin/reconciliations/{reconciliationId}/resolve` (corps : `resolution` parmi `confirm_granted|confirm_removed|escalate`, `evidenceReference`)
- Tables / migrations : table `module_reconciliations` (`id`, `subjectType`, `subjectId`, `organizationId`, `state` enum `open|resolved|escalated`, `sourceA`, `sourceB`, `openedAt`, `resolvedBy`, `resolvedAt`, `evidenceReference`).
- Droits : `platform.reconciliation.resolve` (NON DÉFINI, QE-MOD-07/16) ; accès support soumis à QE-MOD-07. Refus : 403. La réconciliation compare les sources d'autorité et n'invente jamais un état positif.
- Dépendances : BE-045, BE-047
- Critères d'acceptation :
  - CA-1 : une source contradictoire ouvre un cas `open` et ne modifie pas l'état du module.
  - CA-2 : un doublon d'événement (même `idempotencyKey`) ne crée pas de second cas.
  - CA-3 : un acteur sans `platform.reconciliation.resolve` reçoit 403.
  - CA-4 : résoudre sans `evidenceReference` renvoie 422.
  - CA-5 : tant qu'un cas est `open`, l'accessibilité effective (BE-053) du couple est refusée (`RECONCILIATION_PENDING`).
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/reconciliation.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Any -> unknown / reconciliation_required ») ; #1 (état entitlement `reconciliation_required`)

### BE-053 — Moteur d'accessibilité effective
- Domaine : Droits / accès (CAP-FOUND-011, CAP-IDENT-001)
- Vague : 9
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `GET /api/v1/organizations/{orgId}/modules/{moduleId}/access-evaluation?action={action}` (diagnostic : `allow|deny` et motif ; réservé aux administrateurs de l'organisation)
- Tables / migrations : aucune. Valeur dérivée à chaque évaluation, jamais persistée (matrice-etats, section 1).
- Droits : formule `Access(p, a, r, t)` de la section 3 : session admissible ; membre actif de `t` ; permission `a` sur `scope(r,t)` ; état tenant-module compatible ; entitlement valide si la capacité l'exige ; quota conforme. Refus : 403 `ACCESS_DENIED` avec motif stable (`NOT_MEMBER`, `PERMISSION_MISSING`, `MODULE_NOT_ACTIVE`, `ENTITLEMENT_REQUIRED`, `QUOTA_EXCEEDED`, `RECONCILIATION_PENDING`). Tenant absent ou hors périmètre : 404.
- Dépendances : BE-004 (appartenance, membre actif), BE-005 (session admissible), BE-008 (permissions et grants), BE-009 (garde de contexte et d'autorisation, tenant), BE-045, BE-046, BE-048 ; EXT résolu (CAP-FOUND-008, CAP-FOUND-009, CAP-IDENT-001) : BE-004, BE-008, BE-005
- Critères d'acceptation :
  - CA-1 : un membre sans la permission `a` reçoit `deny / PERMISSION_MISSING` (test unitaire de la fonction pure).
  - CA-2 : un module `inactive` ou `suspended` donne `deny / MODULE_NOT_ACTIVE` même si la permission existe.
  - CA-3 : une capacité exigeant un entitlement absent donne `deny / ENTITLEMENT_REQUIRED` ; l'absence d'entitlement pour une capacité qui ne l'exige pas ne produit pas de refus (flag par capacité, QE-MOD-14).
  - CA-4 : la valeur n'est jamais écrite en base (test : aucune nouvelle ligne après évaluation).
  - CA-5 : test d'isolation : évaluer `orgId = B` avec un utilisateur membre de A renvoie 404 et aucun motif révélant l'existence de B.
  - CA-6 : refus par défaut (fail closed) quand une politique d'action mutante est absente (QE-MOD-06).
- Documentation attendue : docstrings de la fonction d'évaluation et de chaque motif ; doc `implementation-backend/doc/modules/acces-effectif.md`.
- Source : matrice-etats-modules-et-droits.md#3. Règle de combinaison à arbitrer ; #4 invariants 1, 3, 4 ; PH-09-modules-catalogue-activation-droits.md#Critères d'acceptation (étape d'accessibilité)

### BE-054 — Application du moteur aux routes API
- Domaine : Droits / transverse API
- Vague : 10
- Routes : aucune nouvelle route ; applique le moteur (BE-053) à toutes les routes des tâches BE-042 à BE-052 et BE-055 à BE-059.
- Tables / migrations : aucune.
- Droits : une dépendance de route unique `require_module_action(action)` appelle le moteur ; le tenant est lu uniquement dans le chemin, jamais dans le corps ni un en-tête client (invariant 1). Refus : 403 `ACCESS_DENIED`, tenant absent : 404.
- Dépendances : BE-053
- Critères d'acceptation :
  - CA-1 : une route de module sans la dépendance d'accès est détectée par un test d'inventaire qui échoue (liste des routes de module vérifiée).
  - CA-2 : un identifiant de tenant injecté dans le corps ou un en-tête est ignoré et ne modifie pas le périmètre (test).
  - CA-3 : une route de module appelée sans session renvoie 401 avant tout accès aux données.
  - CA-4 : une route appelée par un membre sans permission renvoie 403 sans effet de bord (aucune ligne modifiée).
- Documentation attendue : docstring de la dépendance ; doc `implementation-backend/doc/modules/acces-effectif.md`.
- Source : matrice-etats-modules-et-droits.md#4. Invariants sécurité recommandés (1, 2, 4)

### BE-055 — Permissions déclarées par module
- Domaine : Droits / permissions de module
- Vague : 6
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `GET /api/v1/organizations/{orgId}/modules/{moduleId}/permissions` (liste des permissions déclarées par la version installée)
- Tables / migrations : table `module_permissions` (`id`, `moduleVersionId` FK, `code` unique par version, `description`, `scope` enum `organization|tenant|platform`). Recommandation de nommage : `<module-slug>.<ressource>.<action>` (QE-MOD-16).
- Droits : `organization.module.read` (NON DÉFINI, QE-MOD-16) ; lecture seule. Refus : 403 ; hors tenant : 404.
- Dépendances : BE-042, BE-005 (session), BE-008 (permissions et grants), BE-009 (contexte organisation, tenant) ; EXT résolu (CAP-FOUND-009, CAP-IDENT-001) : BE-008 et BE-005
- Critères d'acceptation :
  - CA-1 : deux versions du même module déclarent des permissions distinctes sans collision (contrainte par version).
  - CA-2 : un code de permission non déclaré ne peut pas être accordé (422).
  - CA-3 : un membre sans `organization.module.read` reçoit 403.
  - CA-4 : test d'isolation : lire les permissions de `orgId = B` avec un membre de A renvoie 404.
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/permissions.md`.
- Source : matrice-cap-par-ph-vers-composants.md (CAP-FOUND-009 « rôles & grants », CAP-IDENT-001) ; matrice-etats-modules-et-droits.md#1 (« Permission : action précise … pas accès au module entier »)

### BE-056 — Événements et audit des transitions de module
- Domaine : Événements / audit (CAP-AUDIT-001)
- Vague : 5
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `GET /api/v1/organizations/{orgId}/module-audit?from=&to=&moduleId=` (journal filtré du tenant)
- Tables / migrations : aucune table propre (D2). Les événements sont écrits dans `audit_event` (propriétaire BE-007). Champs requis par cette tâche : `organizationId` nullable pour les événements plateforme, `subjectType`, `subjectId`, `eventName`, `actorId`, `origin`, `correlationId`, `payloadMinimal` JSON sans secret ni contenu métier, `createdAt`. Index `(organizationId, createdAt)` demandé à BE-007 ; si un champ manque, BE-007 l'ajoute à `audit_event` (QE-MOD-21). Événements : `ModuleVersionPublished`, `TenantModuleAvailabilityChanged`, `ModuleInstallationStateChanged`, `EntitlementAllocationChanged`, `ModuleSuspended`, `ModuleReactivated`, `ModuleUninstalled`.
- Droits : `organization.audit.read` (NON DÉFINI, QE-MOD-16) ; partition tenant stricte. Refus : 403 ; hors tenant : 404. Un journal plateforme n'est lisible que par un rôle plateforme (QE-MOD-07).
- Dépendances : BE-007, BE-041
- Critères d'acceptation :
  - CA-1 : chaque transition réussie produit exactement un événement avec scope, acteur, `correlationId`.
  - CA-2 : un payload contenant un champ marqué secret est rejeté avant écriture (test).
  - CA-3 : un membre sans `organization.audit.read` reçoit 403.
  - CA-4 : test d'isolation : le journal de B n'est jamais retourné à un acteur de A (404 sur `orgId = B`).
  - CA-5 : le filtre `moduleId` ne renvoie que les événements du module demandé dans le tenant.
- Documentation attendue : docstrings du publieur d'événements ; doc `implementation-backend/doc/modules/audit-evenements.md`.
- Source : matrice-etats-modules-et-droits.md#4 (invariants 6, 7) ; matrice-cap-par-ph-vers-composants.md (CAP-AUDIT-001) ; PH-09-modules-catalogue-activation-droits.md#Dépendances (PH-14 contrats/événements)

### BE-057 — Notifications de suspension, fin et changement d'état
- Domaine : Notifications
- Vague : 10
- Routes : aucune (sortie vers le service de notification, consommée par les événements de BE-056).
- Tables / migrations : aucune ; file de notifications NON DÉFINIE (QE-MOD-17). Recommandation : table `module_notifications` (`id`, `eventId`, `recipientRole`, `organizationId`, `status` enum `pending|sent|failed`, `attempts`), unique sur `(eventId, recipientRole)`.
- Droits : la notification ne contourne aucun droit : seuls les destinataires ayant `organization.module.read` (NON DÉFINI, QE-MOD-16) reçoivent le contenu.
- Dépendances : BE-049, BE-056
- Critères d'acceptation :
  - CA-1 : une suspension produit une notification par destinataire autorisé, une seule fois (test de doublon).
  - CA-2 : un destinataire sans permission ne reçoit aucune notification (test de refus).
  - CA-3 : une notification ne contient ni secret ni contenu métier (test sur le gabarit).
  - CA-4 : une notification d'une organisation n'est jamais adressée à un destinataire d'une autre organisation (test d'isolation).
- Documentation attendue : docstrings ; doc `implementation-backend/doc/modules/notifications.md`.
- Source : matrice-etats-modules-et-droits.md#2 (« Active -> suspended : notification approuvée ») ; PH-09-modules-catalogue-activation-droits.md#Dépendances

### BE-058 — Liaison facturation vers entitlements
- Domaine : Facturation (CAP-COMMERCE-003, CAP-COMMERCE-008, CAP-COMMERCE-011)
- Vague : 10
- Routes :
  - NON DÉFINI (QE-MOD-01) — recommandation appliquée :
  - `POST /api/v1/internal/billing/entitlement-events` (réservé au service de facturation ; authentification de service NON DÉFINIE, QE-MOD-18)
- Tables / migrations : aucune nouvelle table ; met à jour `subscription_entitlement` (BE-024, colonnes de BE-045) avec `source` et `stateVersion`. Idempotence par `eventId` (table `entitlement_source_events`, unique sur `eventId`).
- Droits : identité de service uniquement ; un appelant utilisateur reçoit 403. Changement d'offre et fin d'abonnement traduits en transitions de BE-041.
- Dépendances : BE-023 (plans et abonnement), BE-024 (table `subscription_entitlement`), BE-045, BE-082 (PaymentAttempt, volet paiement ; QE-MOD-22)
- Dépendances externes : aucune
- Critères d'acceptation :
  - CA-1 : un événement `granted` crée ou met à jour l'entitlement avec la source reçue.
  - CA-2 : un événement dupliqué (même `eventId`) ne produit aucun second effet.
  - CA-3 : un appelant sans identité de service reçoit 403 ; aucun entitlement modifié.
  - CA-4 : un événement de fin d'abonnement passe l'entitlement à `expired` (ou `suspended` si la règle d'impayé le prévoit, QE-MOD-06) ; le cas impayé n'est pas décidé et renvoie `reconciliation_required` par défaut.
  - CA-5 : un événement pour une organisation inconnue renvoie 404 et est journalisé.
- Documentation attendue : docstrings du consommateur d'événements ; doc `implementation-backend/doc/modules/entitlements.md`.
- Source : matrice-cap-par-ph-vers-composants.md (CAP-COMMERCE-003, 008, 011) ; matrice-etats-modules-et-droits.md#3 (suspension, grace, Q-04/05 BLOCKED)

### BE-059 — Périodes, expiration et effet d'accès
- Domaine : Entitlements / périodes
- Vague : 10
- Routes : aucune (tâche planifiée).
- Tables / migrations : aucune nouvelle table ; met à jour `subscription_entitlement.state` et `stateVersion`. Journal via BE-041.
- Droits : tâche système ; aucun droit utilisateur. Effet d'accès évalué par BE-053 à chaque requête, jamais stocké.
- Dépendances : BE-024 (propriétaire de `subscription_entitlement`), BE-045, BE-053
- Critères d'acceptation :
  - CA-1 : un entitlement dont `periodEnd` est dépassé passe à `expired` à l'exécution de la tâche, et une seconde exécution ne change rien (idempotence).
  - CA-2 : un entitlement `expired` donne `deny / ENTITLEMENT_REQUIRED` au moteur (BE-053).
  - CA-3 : un entitlement sans `periodEnd` (valeur absente) n'expire pas et n'est pas remplacé par une date inventée.
  - CA-4 : un entitlement `reconciliation_required` n'est jamais passé à `granted` par la tâche.
- Documentation attendue : docstrings de la tâche ; doc `implementation-backend/doc/modules/entitlements.md`.
- Source : matrice-etats-modules-et-droits.md#1 (états entitlement) ; PH-09-modules-catalogue-activation-droits.md#Démarche pas à pas (étape 5, fin)

### BE-060 — Suite de tests d'isolation et de refus pour les modules
- Domaine : Tests transverses (droits, isolation tenant)
- Vague : 11
- Routes : aucune.
- Tables / migrations : aucune ; base de test jetable `zylo_t060_test` uniquement.
- Droits : vérifie les refus `403`, `401`, `404` de toutes les routes des tâches BE-042 à BE-059.
- Dépendances : BE-046, BE-050, BE-054, BE-059
- Critères d'acceptation :
  - CA-1 : pour chaque route de module, un test de refus de permission (403) existe et passe.
  - CA-2 : pour chaque route portant `{orgId}`, un test d'isolation tenant (acteur de A sur B = 404) existe et passe.
  - CA-3 : pour chaque route de mutation, un test de non-authentification (401) existe et passe.
  - CA-4 : le lancement de la suite se fait en un seul run lourd, sur base jetable ; le rapport liste le décompte exact par catégorie.
- Documentation attendue : docstring de module de test ; doc `implementation-backend/doc/modules/tests-modules.md`.
- Source : matrice-etats-modules-et-droits.md#4 (invariants 1, 2, 4) ; PH-09-modules-catalogue-activation-droits.md#Critères d'acceptation (matrice complète à 100 %)

### BE-061 — Documentation des modules et des routes
- Domaine : Documentation
- Vague : 12
- Routes : aucune.
- Tables / migrations : aucune.
- Droits : aucun.
- Dépendances : BE-060, BE-222 (QE-MOD-25)
- Dépendances externes : BE-222 (gate statique : contrôle de docstrings de CA-2, QE-MOD-25)
- Critères d'acceptation :
  - CA-1 : chaque route du domaine modules figure dans une table `implementation-backend/doc/modules/routes.md` avec méthode, chemin, permission, codes HTTP.
  - CA-2 : chaque fonction publique du domaine possède une docstring (contrôle par outil d'analyse statique, sortie 0).
  - CA-3 : aucune valeur marquée NON DÉFINI n'apparaît dans le code sans renvoi à son QE-MOD-nn.
  - CA-4 : la doc de chaque module cité ici existe (liste vérifiée).
- Documentation attendue : la présente doc elle-même et les doc de module listées ci-dessus.
- Source : CLAUDE.md du projet, section Documentation ; PH-09-modules-catalogue-activation-droits.md#Livrables exacts

## Points ouverts

Les sources ne définissent ni routes, ni tables, ni permissions, ni valeurs de quota. Chaque point ci-dessous est traité par une recommandation appliquée.

- Question : Quel est le préfixe, la convention et la forme des routes API du socle ?
  NON DÉFINI : Recommandation appliquée : toutes les routes commencent par `/api/v1`, portent le tenant dans le chemin `/api/v1/organizations/{orgId}/...` ou `/api/v1/admin/...` (console plateforme rattachée à `/api/v1/admin`), et les actions d'état sont des sous-ressources `POST`. | QE-MOD-01

- Question : Quels codes d'erreur et codes HTTP sont stables pour les refus ?
  NON DÉFINI : Recommandation appliquée : 401 pour session absente, 403 `PERMISSION_DENIED` ou `ACCESS_DENIED` pour un refus de droit, 404 pour tenant ou ressource hors périmètre (réponse identique à l'inexistant), 409 pour garde d'état ou conflit de version, 422 pour donnée invalide. | QE-MOD-02

- Question : Que signifie « installé » par rapport à « activé » dans ZyloOffice ?
  NON DÉFINI : Recommandation appliquée : « installé » signifie release exacte présente, vérifiée et cohérente ; « activé » est un état distinct (`active`) qui exige en plus entitlement et garde d'activation. | QE-MOD-03

- Question : Quelles unités de quota, de siège et d'usage s'appliquent ?
  NON DÉFINI : Recommandation appliquée : le quota est un entier positif ou nul par entitlement, l'unité par défaut est le siège utilisateur, et une valeur absente est exposée `null` sans valeur par défaut. | QE-MOD-04

- Question : Qui peut acheter, activer et attribuer un module ?
  NON DÉFINI : Recommandation appliquée : l'activation et l'attribution relèvent de permissions d'organisation distinctes (`organization.module.activate`, `organization.entitlement.allocate`) ; l'achat relève du rôle finance de l'organisation (PH-10). | QE-MOD-05

- Question : Quels effets d'accès s'appliquent en impayé, en grâce, en suspension et en fin de période ?
  NON DÉFINI : Recommandation appliquée : mutations refusées (fail closed) pendant suspension et expiration ; lectures autorisées ; aucune période de grâce n'est créée ; le cas impayé est `reconciliation_required` par défaut. | QE-MOD-06

- Question : Quels rôles support et administrateur global existent, avec quelle portée, durée et double contrôle ?
  NON DÉFINI : Recommandation appliquée : aucun accès au contenu d'organisation par un rôle plateforme ; les actions plateforme sont tracées et refusées sans permission explicite `platform.*` ; le double contrôle est NON DÉFINI et ne bloque pas la conception. | QE-MOD-07

- Question : Quelle stratégie de segmentation runtime et de cache s'applique à l'accessibilité effective ?
  NON DÉFINI : Recommandation appliquée : aucune valeur d'accessibilité n'est persistée ni mise en cache ; l'évaluation est refaite à chaque requête par le moteur BE-053. | QE-MOD-08

- Question : Quels critères définissent la réussite d'une installation ?
  NON DÉFINI : Recommandation appliquée : `installed` n'est posé que si toutes les ressources sont présentes et la release exacte vérifiée ; tout succès partiel est `failed` avec `lastErrorCode`. | QE-MOD-09

- Question : Que devient un module `withdrawn` ou `quarantined` déjà installé chez un tenant ?
  NON DÉFINI : Recommandation appliquée : aucune suppression automatique ; le module reste dans son état, un événement est émis et un cas de réconciliation est ouvert. | QE-MOD-10

- Question : Quelle est la politique de rétention des données à la désinstallation ?
  NON DÉFINI : Recommandation appliquée : les données sont conservées à la désinstallation, aucune purge n'est exécutée par le socle. | QE-MOD-11

- Question : Quelle audience et quelles régions s'appliquent à la visibilité des fiches `restricted` ?
  NON DÉFINI : Recommandation appliquée : fiches `hidden` par défaut ; une fiche `restricted` est refusée à tout visiteur sans règle d'audience explicite. | QE-MOD-12

- Question : Quelles sont les sources d'entitlement et leur matrice de référence partagée (OBJ-07) ?
  NON DÉFINI : Recommandation appliquée : l'énumération de source est `plan|paid_option|trial|authorized_allocation`, stockée sur chaque entitlement ; la matrice partagée `03-plateforme/matrice-offres-droits-quotas-entitlements.md` n'existe pas encore et est à produire. | QE-MOD-13

- Question : Comment une capacité déclare-t-elle qu'un entitlement lui est applicable ?
  NON DÉFINI : Recommandation appliquée : chaque capacité porte un indicateur `requiresEntitlement` ; à défaut de déclaration, l'accès est refusé (fail closed). | QE-MOD-14

- Question : Quel est le format des identifiants de module et de version ?
  NON DÉFINI : Recommandation appliquée : `slug` en minuscules séparées par tiret, version au format semver, identifiant interne UUID. | QE-MOD-15

- Question : Quels noms de permissions et de rôles sont définis pour les modules ?
  NON DÉFINI : Recommandation appliquée : permissions nommées `<domaine>.<ressource>.<action>` (`organization.module.install`, `platform.module.publish`, etc.) ; les rôles sont NON DÉFINIS et ne sont pas créés par le socle. | QE-MOD-16

- Question : Quel est le mécanisme de notification et sa file de sortie ?
  NON DÉFINI : Recommandation appliquée : une ligne par événement et par destinataire autorisé, table `module_notifications` avec statut `pending|sent|failed`. | QE-MOD-17

- Question : Comment les appels de service (facturation) sont-ils authentifiés ?
  NON DÉFINI : Recommandation appliquée : identité de service distincte des sessions utilisateur, refusée à tout appelant sans identité de service. | QE-MOD-18

- Incohérence : le renvoi « PH-09 » vers les IDs CAP-FOUND-013 à 015 et la ligne 142 de la matrice partagée sont signalés comme à corriger par leur propriétaire.
  Question : Quel renvoi CAP fait foi pour l'activation, la disponibilité et la compatibilité des modules ?
  NON DÉFINI : Recommandation appliquée : l'index canonique `03-plateforme/index-capacites-fondation.md` lignes 24 à 26 fait foi (CAP-FOUND-013 enregistrement, 014 disponibilité tenant-module, 015 compatibilité). | QE-MOD-19

- Question : Le catalogue de modules (BE-040, table `modules`) et le registre existant (BE-021, table `module`) désignent-ils le même objet ?
  NON DÉFINI : Recommandation appliquée : BE-040 est le seul propriétaire du catalogue (`modules`, `module_versions`) ; BE-021 réutilise `modules` au lieu de créer `module`, à confirmer par le propriétaire de BE-021. | QE-MOD-20

- Question : Quelles colonnes porte `audit_event` pour les transitions de module (BE-056) ?
  NON DÉFINI : Recommandation appliquée : les champs listés en BE-056 sont fournis par `audit_event` (BE-007) ; aucune table dédiée au module ; un champ manquant est ajouté à `audit_event` par BE-007. | QE-MOD-21

- Question : Comment BE-058 se rattache-t-il au volet paiement (PH-10) ?
  NON DÉFINI : Recommandation appliquée : BE-058 dépend de BE-082 (PaymentAttempt, tâche de paiement existante) ; BE-027, BE-028 et BE-029 ne sont pas des dépendances directes ; il applique les événements du service de facturation avec sa propre idempotence par `eventId`. | QE-MOD-22

- Question : Quelle casse appliquer aux noms de tables ?
  NON DÉFINI : Recommandation appliquée : snake_case partout pour les noms de tables (décision du coordinateur, appliquée) ; aucun nom de table de ce fichier n'était en camelCase, donc aucun renommage ; les colonnes restent en camelCase | QE-MOD-23

- Question : Les routes de la console opérateur doivent-elles être préfixées `/api/v1/operator` ?
  NON DÉFINI : Recommandation appliquée : toute route de la console opérateur est sous `/api/v1/admin/...` (décision du coordinateur, appliquée) ; aucune route `/api/v1/operator` n'existe dans ce fichier (vérifié par recherche). Les routes `/api/v1/internal/...` ne sont pas des routes opérateur : `POST /api/v1/internal/billing/entitlement-events` (BE-058) est conservée. | QE-MOD-24

- Question : BE-061 déclare-t-elle des dépendances externes (marqueur « EXT ») ?
  NON DÉFINI : Recommandation appliquée : oui, BE-222 (gates qualité serveur, outil d'analyse statique qui contrôle les docstrings, CA-2) ; BE-060 est la dépendance du domaine, déjà listée. Le contrôle vérifié (grep sur les tâches-*.md) ne trouve pas d'autre prérequis hors domaine. Décision à reporter par le propriétaire dans DEPENDANCES.md et PLAN-BACKEND.md, qui indiquent encore « aucun » pour BE-061. | QE-MOD-25

Note : la numérotation QE-MOD-19 dépasse les 18 items de la liste ci-dessus parce que l'incohérence de renvoi est traitée en dernier ; les identifiants QE-MOD-01 à QE-MOD-25 sont utilisés sans trou (QE-MOD-20 à QE-MOD-23 ajoutés lors de la correction des décisions D2 à D4 et de la convention de casse ; QE-MOD-24 et QE-MOD-25 ajoutés par les décisions du coordinateur sur les routes opérateur et les dépendances de BE-061).
