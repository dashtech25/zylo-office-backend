# Tâches back-end — Fondation (recensement)

- **Domaine :** socle Zylo Office, back-end uniquement (audit, droits et entitlements, accès support, profil tenant factuel)
- **Plage d'identifiants :** BE-260 à BE-279 (4 tâches utilisées : BE-260 à BE-263)
- **Sources lues :**
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-00-gouvernance-et-procedure.md` (lecture complète, seules les règles imposant un livrable back-end retenues)
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-01-vision-perimetre-acteurs.md` (lecture ciblée)
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md` (lecture ciblée, capacités back-end)
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-02-audit-socle-zylo-office.md` (lecture ciblée, écarts back-end)
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-06-comparaison-et-decisions.md` (lecture ciblée, décisions back-end)
  - `definition-travail/00-pilotage/architecture-fondation/recommandations-approuvees-2026-11-02.md`
  - `definition-travail/00-pilotage/architecture-fondation/portes-et-criteres-entree-implementation.md`
- **Non lus, par consigne :** PH-03, PH-04, PH-05 (phases de recensement et de références).

**Constat préalable :** les sources sont des documents de cadrage. Elles ne définissent ni routes, ni schéma de données, ni codes de permission, ni codes HTTP. Chaque champ absent est marqué « NON DÉFINI » avec sa recommandation. PH-17 indique « Implémentation NOT AUTHORIZED / NOT READY » ; les tâches ci-dessous sont donc des tâches planifiées et provisoires, à ne pas exécuter avant une instruction humaine distincte (voir QE-FON-01).

## Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-260 | Journal d'audit des actions sensibles | 1 (recommandée) | BE-005, BE-007, BE-008, BE-009 |
| BE-261 | Fusionnée dans BE-024 (ne pas appliquer) | 0 | sans objet |
| BE-262 | Accès support/admin en lecture seule par défaut | 1 (recommandée) | BE-260, BE-008, BE-009 |
| BE-263 | Profil tenant factuel sans score | 1 (recommandée) | BE-024, BE-203, BE-206, BE-262 |

---

### BE-260 — Journal d'audit des actions sensibles
- Domaine : Audit
- Vague : 6
- Routes :
  - `GET /api/v1/organizations/{organization_id}/audit` (NON DÉFINI dans les sources ; recommandation de nommage, lecture seule ; la route existante `/api/v1/audit/organizations/{organization_id}` est conservée et marquée « à retirer après BE-033 » ; QE-FON-16)
  - Écriture : aucune route, écriture par les services lors d'une action sensible
- Tables / migrations : aucune table créée. Consomme `audit_event`, créée et migrée par BE-007 (propriétaire unique, décision D2 ; types SQL NON DÉFINI). Champs attendus de `audit_event`, fournis par BE-007 (QE-FON-15) : `id`, `organizationId` (nul seulement pour une action globale, NON DÉFINI), `acteurId`, `action`, `cibleType`, `cibleId`, `justification` (obligatoire), `portee`, `resultat`, `dateUtc`, `approbationId` (nul possible, NON DÉFINI). Pas de mise à jour ni suppression applicative.
- Droits :
  - Lecture : permission `audit.log.view` (code cité par le routeur existant, convention `module.resource.action` ; NON DÉFINI, QE-FON-04), portée organisation ; refus : 403 (NON DÉFINI ; recommandation 403).
  - Écriture : automatique, à chaque action sensible ; aucune permission utilisateur requise.
- Dépendances : BE-005 (authentification), BE-007 (table `audit_event`), BE-008 (permission `audit.log.view`), BE-009 (contexte et portée organisation)
- Code existant (develop) : app/audit/models.py (classe AuditLog, table `auditLog`, journal métier à migrer vers `audit_event` par BE-007) ; app/audit/service.py (`record_audit_event`, `list_audit_logs`, `_audit_visibility`) ; app/audit/router.py (GET `/api/v1/audit/organizations/{organization_id}`, filtré par `audit.log.view`) ; app/operator/audit_models.py (OperatorAuditLog, table `operatorAuditLog`, journal opérateur distinct) ; garder : `record_audit_event` comme point d'écriture, le filtrage par portée et le journal opérateur (hors `audit_event`) ; casser : la table `auditLog` ; la route `/api/v1/audit/organizations/{organization_id}` est conservée et marquée « à retirer après BE-033 » (QE-FON-16).
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : une action sensible de test crée exactement une ligne `audit_event` dans la même transaction que l'action ; test binaire.
  - CA-2 : une action sensible sans `justification` est refusée (422 recommandé, NON DÉFINI) et ne crée aucune ligne ; test binaire.
  - CA-3 (refus de droit) : `GET .../audit` sans `audit.log.view` renvoie 403 ; test binaire.
  - CA-4 (isolation tenant) : un utilisateur de l'organisation B qui appelle `GET /api/v1/organizations/{A}/audit` reçoit 403 et aucune ligne de A ; test binaire.
  - CA-5 : toute tentative de `UPDATE` ou `DELETE` sur `audit_event` échoue (contrainte ou trigger) ; test binaire.
- Documentation attendue : docstrings explicites de chaque fonction publique du service d'audit ; doc de module à `implementation-backend/` (paquet existant `app/audit/`, D7).
- Source : `00-pilotage/architecture-fondation/recommandations-approuvees-2026-11-02.md#Q-06` ; `00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md#Critères d'acceptation` (audit, notifications et exigence non fonctionnelle par capacité).

---

### BE-261 — Table de référence des entitlements
- Statut : fusionnée dans BE-024 : ne pas appliquer le texte ci-dessous
- Domaine : Droits et entitlements
- Vague : sans objet (fusionnée dans BE-024)
- Routes : aucune (table consommée par les services ; NON DÉFINI : route de lecture, recommandation : aucune route publique dans cette tâche)
- Tables / migrations : table `entitlement` (NON DÉFINI : nom et types SQL). Champs logiques issus de la chaîne de la matrice : `offreId`, `capaciteId` (clé étrangère vers le registre de capacités), `quotaLimite` (valeur et unité NON DÉFINI), `niveauApplication` (`organisation` | `utilisateur`), `sourceAttribution` (`offre` | `achat_additionnel` | `essai` | `allocation_admin` | `usage_reel`), `effetAcces` (NON DÉFINI), `organizationId` (portée tenant, nul pour une offre globale, NON DÉFINI).
- Droits :
  - Lecture et écriture par les services : permission `entitlement.manage` (NON DÉFINI ; recommandation de code), portée administration globale pour l'écriture et organisation pour la lecture ; refus : 403 (recommandation).
- Dépendances : sans objet (fusionnée dans BE-024, qui déclare la dépendance BE-021)
- Code existant (develop) : sans objet (fusionnée dans BE-024)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la migration crée la table avec les champs logiques ci-dessus ; test binaire de présence des colonnes.
  - CA-2 : `niveauApplication` et `sourceAttribution` n'acceptent que les valeurs listées ; une autre valeur est refusée ; test binaire.
  - CA-3 : chaque combinaison `sourceAttribution` × `niveauApplication` (5 × 2) est enregistrable ; test binaire de couverture.
  - CA-4 : un `entitlement` pointant vers une `capaciteId` inexistante est refusé ; test binaire.
  - CA-5 (refus de droit) : une écriture sans `entitlement.manage` renvoie 403 et ne modifie rien ; test binaire.
  - CA-6 (isolation tenant) : un entitlement de l'organisation A n'apparaît pas dans la lecture de l'organisation B ; test binaire.
- Documentation attendue : docstrings de chaque fonction publique du module d'entitlements ; doc de module à `implementation-backend/` (chemin NON DÉFINI, recommandation `entitlements/`).
- Source : `00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md#Méthode et représentation` (point 5 : chaîne offre → module/capacité → quota → niveau → entitlements → effet d'accès) ; `00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md#Critères d'acceptation` (matrice offres/droits/quotas/entitlements).

---

### BE-262 — Accès support/admin en lecture seule par défaut
- Domaine : Accès support et administration
- Vague : 7
- Routes :
  - `POST /api/v1/organizations/{organization_id}/acces-support` (NON DÉFINI dans les sources ; recommandation : crée un accès avec `mode` `lecture` par défaut et `justification` obligatoire)
- Tables / migrations : table `acces_support` (NON DÉFINI : nom et types SQL). Champs logiques : `id`, `supportUserId`, `organizationId`, `portee` (NON DÉFINI), `mode` (`lecture` par défaut, `ecriture` NON DÉFINI), `justification` (obligatoire), `debutUtc`, `finUtc` (durée NON DÉFINI), `approbationId` (double approbation NON DÉFINI).
- Droits :
  - Accès en lecture : permission `support.read` (NON DÉFINI ; recommandation de code), portée limitée à l'organisation ciblée.
  - Accès en écriture : permission `support.write_sensible` (NON DÉFINI), refusée si `mode` est `lecture`.
  - Refus de droit : 403 ; ressource hors portée : 403 (recommandation, NON DÉFINI).
- Dépendances : BE-260 (audit, via BE-007), BE-008 (permissions `support.read` et `support.write_sensible`), BE-009 (portée organisation)
- Code existant (develop) : app/rbac/models.py (Role, Permission, table `permission` au format `module.resource.action`, UserPermissionGrant : grants par utilisateur) ; app/operator/ (accès opérateur existant : permissions.py, router.py, audit.py ; voir QE-FON-13) ; garder : app/rbac/ et le modèle de grants pour les permissions support ; casser : aucun ; à créer : app/support/ (modèle `acces_support`, service, routes), aucun paquet support n'existe.
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : un accès créé sans précision de mode est en `lecture` ; test binaire.
  - CA-2 : une action d'écriture avec un accès en `lecture` renvoie 403 et ne modifie rien ; test binaire (refus de droit).
  - CA-3 : une création d'accès sans `justification` renvoie 422 (NON DÉFINI ; recommandation) et ne crée aucune ligne ; test binaire.
  - CA-4 (isolation tenant) : un accès accordé pour l'organisation A ne permet pas de lire l'organisation B ; test binaire qui doit renvoyer 403.
  - CA-5 : chaque accès et chaque action sous accès produit une ligne `audit_event` (BE-260) ; test binaire.
  - CA-6 : un accès dont `finUtc` est dépassé est refusé ; test binaire, à valider après définition de la durée (QE-FON-05).
- Documentation attendue : docstrings de chaque fonction publique du module ; doc de module à `implementation-backend/` (à créer `app/support/` : aucun paquet existant, QE-FON-13).
- Source : `00-pilotage/architecture-fondation/recommandations-approuvees-2026-11-02.md#Q-06` (moindre privilège, lecture seule par défaut, justification, portée limitée, audit, vérification pour actions sensibles) ; `00-pilotage/architecture-fondation/portes-et-criteres-entree-implementation.md#Checklist minimale de preuve de passage` (actions privilégiées : cible, préconditions, permission, motif, approbation, durée, audit, révocation).

---

### BE-263 — Profil tenant factuel sans score
- Domaine : Tenant et profil factuel
- Vague : 20
- Routes :
  - `GET /api/v1/organizations/{organization_id}/profil-factuel` (NON DÉFINI dans les sources ; recommandation de nommage, lecture seule)
- Tables / migrations : aucune table nouvelle (vue calculée à partir des signaux factuels ; NON DÉFINI : liste exacte des signaux).
- Droits :
  - Lecture : permission `support.read` (BE-262) ou permission organisation équivalente (NON DÉFINI), portée limitée à l'organisation ; refus : 403.
- Dépendances : BE-024 (entitlements, `subscription_entitlement`), BE-203 (états d'abonnement), BE-206 (paiements), BE-262 (accès support)
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : la réponse ne contient aucun champ de type score, niveau de risque, réputation ou jugement ; test binaire sur le schéma de réponse.
  - CA-2 : chaque signal renvoyé porte sa source et sa date ; test binaire.
  - CA-3 (refus de droit) : appel sans permission renvoie 403 ; test binaire.
  - CA-4 (isolation tenant) : l'organisation B ne peut pas lire le profil de l'organisation A ; test binaire, 403.
  - CA-5 : l'appel ne modifie aucun `subscription_entitlement` ni aucun accès ; test binaire (aucun effet d'accès sur simple lecture).
- Documentation attendue : docstrings de chaque fonction publique ; doc de module à `implementation-backend/` (chemin NON DÉFINI ; recommandation `app/identity/`, paquet existant, `app/tenant/` n'existe pas : QE-FON-14).
- Source : `00-pilotage/architecture-fondation/recommandations-approuvees-2026-11-02.md#Q-01` (profil factuel explicable, sans score ni jugement, aucune conséquence d'accès fondée sur un score) ; `00-pilotage/architecture-fondation/phases/PH-01A-recensement-exhaustif-capacites.md#Question de clarification` (signaux factuels : états d'abonnement, incidents, activité, paiements).

---

## Points ouverts

- Question : les tâches BE sont-elles autorisées alors que PH-17 indique « Implémentation NOT AUTHORIZED / NOT READY » et que le cadre de travail prévoit une phase back-end ?
  NON DÉFINI : Recommandation appliquée : traiter BE-260 à BE-263 comme planification provisoire ; aucune implémentation avant une instruction humaine écrite nommant le périmètre (gate G8) | QE-FON-01

- Question : quels sont les noms et chemins exacts des routes API (aucun nom de route dans les sources) ?
  NON DÉFINI : Recommandation appliquée : utiliser les routes marquées « recommandation » ci-dessus, en forme `/api/v1/organizations/{organization_id}/...`, à valider avant tout code | QE-FON-02

- Question : quels sont les noms de tables, colonnes, types SQL et clés ?
  NON DÉFINI : Recommandation appliquée : utiliser les champs logiques listés, nommés en camelCase, avec clés étrangères sur `organizationId` et `capaciteId` (convention camelCase, QE-FON-17) | QE-FON-03

- Question : quels codes de permission (`audit.log.view`, `entitlement.manage`, `support.read`, `support.write_sensible`) et quels rôles les portent ?
  NON DÉFINI : Recommandation appliquée : utiliser les codes recommandés, portés par le moindre privilège et le mode lecture par défaut (Q-06) | QE-FON-04

- Question : quelle est la durée maximale d'un accès support, et l'accès temporaire est-il requis ?
  NON DÉFINI : Recommandation appliquée : imposer un `finUtc` obligatoire sur tout accès support, la valeur numérique restant NON DÉFINI et à décider | QE-FON-05

- Question : la double approbation et la procédure d'urgence pour actions support sensibles sont-elles requises, et par qui ?
  NON DÉFINI : Recommandation appliquée : ne pas implémenter de double approbation en BE-262 ; le champ `approbationId` est nul jusqu'à décision | QE-FON-06

- Question : quels codes HTTP sont attendus pour un refus de droit, une ressource hors portée et une justification absente ?
  NON DÉFINI : Recommandation appliquée : 403 pour refus de droit et hors portée tenant, 422 pour justification absente | QE-FON-07

- Question : quelle est la liste exacte des signaux factuels du profil tenant (état d'abonnement, incidents, activité, paiements) et leur finalité ?
  NON DÉFINI : Recommandation appliquée : limiter le profil aux quatre familles citées dans PH-01A, sans score, et ne rien ajouter sans décision | QE-FON-08

- Question : quels sont les valeurs, unités et effets d'accès des quotas et limites des entitlements ?
  NON DÉFINI : Recommandation appliquée : stocker `quotaLimite` et `effetAcces` sans valeur par défaut, et refuser l'écriture d'une ligne `subscription_entitlement` (BE-024) sans ces champs | QE-FON-09

- Question : la distinction tenant / organisation / workspace (PH-17, gate G3) est-elle tranchée, et `organizationId` est-il la portée tenant retenue ?
  NON DÉFINI : Recommandation appliquée : utiliser `organizationId` comme unique portée tenant dans BE-260 à BE-263 | QE-FON-10

- Question : quelle est la durée de conservation du journal d'audit et ses exceptions ?
  NON DÉFINI : Recommandation appliquée : conserver les lignes `audit_event` sans suppression applicative jusqu'à décision de rétention | QE-FON-11

- Question : la lecture de l'audit est-elle réservée à l'administration globale ou ouverte à l'administrateur d'organisation ?
  NON DÉFINI : Recommandation appliquée : réserver `audit.log.view` à l'administration globale, et accorder la lecture organisation seulement après décision | QE-FON-12

- Question : BE-262 (accès support) chevauche BE-229 (accès opérateur JIT et approbation) et BE-123 (cas d'intervention) ; quel module porte l'accès support ?
  NON DÉFINI : Recommandation appliquée : BE-262 porte seul le modèle `acces_support` en lecture seule ; BE-229 et BE-123 ne sont pas des dépendances de BE-262. | QE-FON-13
- Question : quel paquet accueille le profil tenant (BE-263), alors que `app/tenant/` n'existe pas ?
  NON DÉFINI : Recommandation appliquée : `app/identity/` (paquet existant), à confirmer lors de la tâche. | QE-FON-14
- Question : quels sont les types SQL et colonnes exacts de `audit_event` (justification, portée, résultat, approbation) ?
  NON DÉFINI : Recommandation appliquée : BE-007 fournit ces colonnes ; BE-260 et BE-262 n'ajoutent aucune colonne et signalent tout champ manquant à BE-007. | QE-FON-15
- Question : la route de lecture d'audit existante (`/api/v1/audit/organizations/{organization_id}`, app/audit/router.py) coexiste-t-elle avec celle de BE-260 ?
  NON DÉFINI : Recommandation appliquée : la route existante `/api/v1/audit/organizations/{organization_id}` est conservée et marquée « à retirer après BE-033 » ; la route de BE-260 (`/api/v1/organizations/{organization_id}/audit`) s'y ajoute. | QE-FON-16
- Question : quelle convention de nommage des colonnes (snake_case du plan, camelCase du code existant `organizationId`, `actorUserId`) ?
  NON DÉFINI : Recommandation appliquée : camelCase (`organizationId`) pour les colonnes écrites dans les fichiers du plan, conformément à la convention du code existant (`organizationId`) ; appliqué dans les fichiers exploitation et fondation seulement ; les autres fichiers à aligner (QE-FON-17). Les colonnes de BE-260 à BE-263 (QE-FON-03) sont converties en camelCase dans la même décision (2026-11-03). | QE-FON-17

- Question : quelle casse appliquer aux noms de tables (le CLAUDE.md du backend prévoit des tables camelCase) ?
  NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-FON-18

- Question : quelle casse appliquer aux noms de tables (décision du coordinateur du 2026-11-03) ?
  NON DÉFINI : Recommandation appliquée : snake_case partout pour les tables ; aucune table camelCase dans les lignes « Tables / migrations » de ce fichier, donc aucun renommage ; les noms du code existant `auditLog` et `operatorAuditLog` (Code existant, lignes BE-007 et journal opérateur) sont gardés tels quels, leur renommage relevant de BE-007 ; les colonnes restent camelCase ; aucune route de console opérateur ni route interne dans ce fichier, `app/operator/` étant un chemin de code et non une route. | QE-FON-18
