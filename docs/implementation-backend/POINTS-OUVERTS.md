# Points ouverts (QE) : chantier ZYLO-OFFICE-BACKEND-PLAN, BE-CONS-A

Statut : recommandation appliquée, réponse différée. Aucune question n'est validée.

Source : sections Points ouverts des 9 fichiers tasks-*.md, copiées mot pour mot, à la date du 2026-11-03 (passe de cohérence).

## Décisions de l'étape A (2026-11-03)

- D1 : enveloppe d'erreur `{"error": {...}}` portée par BE-001 (clés `request_id` et `field_errors` du code).
- D2 : table unique `audit_event`, propriétaire BE-007.
- D3 : table `subscription_entitlement`, propriétaire BE-024, BE-261 fusionnée.
- D4 : dépendances auth, tenant et RBAC explicites (BE-150, BE-180, BE-260).
- D5 : BE-120 hors vague 1.
- D6 : routes `/api/v1` et `/api/v1/admin`, mot `organizations`, doublons /auth/login (BE-005) et portal-summary (BE-109).
- D7 : chemins `app/<capacité>/`.
- D8 : ligne « Code existant (develop) » pour les tâches des vagues 1 et 2.

## Domaine : abonnements-facturation (31 QE)

- Question : Quels chemins d'API (routes) faut-il retenir pour le domaine facturation ?
  - NON DÉFINI : aucun endpoint n'est fixé par les sources. Recommandation appliquée : préfixe `/api/v1/billing/` (routeur réel : `app/main.py` monte `/api/v1` ; `app/api/v1/router.py` monte `/billing`), avec les ressources des tâches BE-076 à BE-099, à valider au contrat PH-14 avant implémentation. | QE-FAC-01

- Question : Quels codes HTTP renvoyer pour chaque code d'erreur, et quel code pour un objet hors scope ?
  - NON DÉFINI : aucun code HTTP n'est fixé. Recommandation appliquée : 401 pour non authentifié ; 403 pour `FORBIDDEN` et `SCOPE_MISMATCH` ; 404 pour tout objet hors scope (réponse identique à l'inexistant) ; 409 pour `INVALID_TRANSITION`, `VERSION_CONFLICT`, `DUPLICATE` ; 422 pour `CONSENT_REQUIRED`, `QUOTE_EXPIRED`, `*_NOT_CONFIGURED` ; 402 pour `PAYMENT_DECLINED` ; 503 pour `PROVIDER_UNAVAILABLE` ; 202 avec statut `unknown` pour `RESULT_UNKNOWN`. | QE-FAC-02

- Question : Quelles permissions nommées (PH-08) protègent chaque route ?
  - NON DÉFINI : la permission détaillée attend PH-08 et la question Q-06. Recommandation appliquée : une permission par couple (ressource, action) nommée `billing.<ressource>.<action>`, rattachée aux rôles ACTF-04 à ACTF-12 ; refus 403 tel que décrit par tâche. | QE-FAC-03

- Question : Quels noms de tables et de colonnes retenir ?
  - NON DÉFINI : aucun schéma n'est fixé. Recommandation appliquée : colonnes en camelCase, conformément au code develop, avec les noms indiqués dans chaque tâche (pluriel évité) et clés étrangères explicites ; les noms de tables gardent la casse décidée (QE-FAC-31) ; la liste définitive est validée par la première migration. | QE-FAC-04

- Question : Quelle durée de période d'essai, quel fuseau, quelles bornes calendaires et quel prorata retenir ?
  - NON DÉFINI : la durée, le fuseau, les dates calendaires et le prorata ne sont pas tranchés. Recommandation appliquée : `trialEnd` obligatoire dans la requête d'essai (BE-080), fuseau UTC stocké, prorata non calculé ; tout changement en cours de période est refusé tant que non décidé. | QE-FAC-05

- Question : Quels prix, devises et taxes appliquer ?
  - NON DÉFINI : aucune valeur n'est fixée (décision finance). Recommandation appliquée : BE-078 renvoie `PRICE_NOT_CONFIGURED`, `TAX_NOT_CONFIGURED` ou `CURRENCY_NOT_CONFIGURED` tant qu'aucune règle n'est saisie ; aucune valeur n'est codée en dur. | QE-FAC-06

- Question : Quelle durée de grâce et quelle politique d'accès pendant un incident de paiement ?
  - NON DÉFINI : décision Q-05. Recommandation appliquée : état `past_due` puis `grace` avec `graceUntil` vide ; aucun changement de droit automatique ; suspension uniquement manuelle (ACTF-09 ou ACTF-07). | QE-FAC-07

- Question : La résiliation par défaut est-elle à échéance, et une résiliation immédiate est-elle permise ?
  - NON DÉFINI : mode non tranché. Recommandation appliquée : mode par défaut `end_of_period` ; mode `immediate` refusé tant que non décidé ; remboursement prorata non calculé. | QE-FAC-08

- Question : Quel seuil de remboursement et quelle règle d'approbation retenir ?
  - NON DÉFINI : aucun seuil ni pouvoir fixé (Q-06). Recommandation appliquée : aucun remboursement ni avoir automatique ; toute action financière irréversible exige une approbation enregistrée (ACTF-08) ; seuil implicite à zéro, donc toute demande est approuvée par un humain. | QE-FAC-09

- Question : Quelle autorité (catalogue ou finance) fait foi pour chaque objet financier ?
  - NON DÉFINI : décision par objet et scénario. Recommandation appliquée : PH-09 fait foi pour l'offre et les droits ; la finance fait foi pour prix, devise, taxe et facture ; une seule source par objet, consignée dans la fiche de chaque tâche. | QE-FAC-10

- Question : Quel fournisseur de paiement et quel ERP utiliser ?
  - NON DÉFINI : aucun PSP ni ERP n'est sélectionné. Recommandation appliquée : adaptateur fournisseur abstrait (décision D-17, option D) avec un adaptateur fictif pour les tests ; aucun nom de fournisseur n'est introduit. | QE-FAC-11

- Question : Comment vérifier la signature des événements fournisseur et tourner les secrets ?
  - NON DÉFINI : PH-13 ne fixe pas la signature ni la rotation. Recommandation appliquée : rejet 401 de tout événement sans signature valide ; rotation des secrets NON DÉFINI, à traiter par PH-13 sans bloquer BE-083. | QE-FAC-12

- Question : Quelles durées de conservation, de purge et de backoff retenir pour l'idempotence, l'audit et les tentatives ?
  - NON DÉFINI : TTL, rétention et backoff non fixés dans les sources. Recommandation appliquée : aucune purge automatique des enregistrements d'idempotence, d'audit et d'outbox jusqu'à décision de PH-13/PH-14. | QE-FAC-13

- Question : Quelle autorité gouverne les dossiers de facturation et d'assistance ?
  - NON DÉFINI : file PH-12 et autorité de workflow à confirmer. Recommandation appliquée : les cas sont gérés par la file PH-12 ; un cas ouvert n'est jamais bloquant (BE-097). | QE-FAC-14

- Question : Quel contenu, numérotation, arrondi et mentions de facture retenir selon la juridiction ?
  - NON DÉFINI : juridiction, devise, arrondis, taxes et mentions non établis (obligations à valider par la partie compétente). Recommandation appliquée : finalisation refusée tant que devise et taxe ne sont pas configurées (BE-086 CA-2) ; aucune mention légale n'est inventée. | QE-FAC-15

- Question : Quel texte et quelle version de consentement retenir, et quelle autorité contractuelle le valide ?
  - NON DÉFINI : texte et autorité non choisis. Recommandation appliquée : chaque consentement référence un identifiant de version de texte ; l'autorité est désignée par la finance et le juridique. | QE-FAC-16

- Question : Faut-il versionner l'enveloppe d'événement et les statuts, et selon quelle règle ?
  - NON DÉFINI : versionnement à définir par PH-14 avant contrat externe. Recommandation appliquée : champ `eventVersion` obligatoire dans l'enveloppe, initialisé à `v1`, sans contrat externe avant validation PH-14. | QE-FAC-17

- Question : Quel code d'erreur renvoyer quand une clé d'idempotence est rejouée avec une commande différente ?
  - NON DÉFINI : aucun code précis dans les sources. Recommandation appliquée : `DUPLICATE` avec statut 409, sans effet de bord. | QE-FAC-19

- Question : Comment fixer la portée et l'expiration des clés d'idempotence ?
  - NON DÉFINI : portée et expiration non choisies. Recommandation appliquée : portée = principal + route + clé, sans expiration automatique jusqu'à décision (voir QE-FAC-13). | QE-FAC-18

- Question : Quel délai d'expiration applique un devis ?
  - NON DÉFINI : durée d'expiration absente. Recommandation appliquée : `expiresAt` obligatoire à la création du devis ; un devis sans `expiresAt` est refusé. | QE-FAC-21

- Question : Le mesurage d'usage (metering) est-il inclus dans ce plan ?
  - NON DÉFINI : usage non attribué à une capacité existante (PH10-METER, décision D-09 non tranchée). Recommandation appliquée : exclu du périmètre des tâches BE-070 à BE-099 ; à planifier après décision D-09. | QE-FAC-20

- Question : Quel format et quel contenu pour l'export des données de facturation ?
  - NON DÉFINI : format et contenu non fixés. Recommandation appliquée : export limité au scope du demandeur, format structuré lisible, sans secret de paiement ; validation avant implémentation de BE-098. | QE-FAC-25

- Question : Quelle est la frontière exacte entre tenant, organisation et compte payeur ?
  - NON DÉFINI : frontière à décider par PH-07. Recommandation appliquée : payeur, tenant bénéficiaire et administrateur sont trois références distinctes (BE-071) ; aucune équivalence tenant = organisation n'est supposée. | QE-FAC-22

- Question : Quelle est la permission d'un administrateur de tenant distinct de l'acheteur ?
  - NON DÉFINI : rôles effectifs à valider (CAP-FOUND-009). Recommandation appliquée : l'administrateur du tenant peut consulter et résilier ; il ne peut ni finaliser de facture ni rembourser. | QE-FAC-23

- Question : Quel est le chemin du module et la stack technique du back-end pour le domaine billing ?
  - NON DÉFINI : stack et arborescence absentes des sources. Recommandation appliquée : `app/billing/<nom-du-module>` (package existant sur develop, D7), stack observée FastAPI, SQLAlchemy, Alembic ; à aligner avec PH-14 et le socle back-end. | QE-FAC-24

- Question : Quelle est la décision finance sur les prix, taxes et devises (EXT de BE-078) ?
  - NON DÉFINI : décision finance non prise, aucune tâche ne porte cet objet. Recommandation appliquée : BE-078 ne retourne aucune valeur par défaut et renvoie `PRICE_NOT_CONFIGURED`, `TAX_NOT_CONFIGURED` ou `CURRENCY_NOT_CONFIGURED` tant qu'aucune règle n'est saisie ; BE-077 et BE-081 en dépendent. | QE-FAC-26

- Question : Quelle tâche reçoit les événements de paiement fournisseur : BE-029 (socle, webhook de paiement) ou BE-163 (webhook entrant générique) ?
  - NON DÉFINI : deux tâches couvrent le même webhook. Recommandation appliquée : BE-083 est la seule route d'entrée des événements de paiement (`POST /api/v1/billing/provider-events`), avec la vérification de signature, et dépend de BE-029 (table d'idempotence, déduplication, quarantaine) et de BE-163 (tenant) ; BE-029 n'a pas de route propre. | QE-FAC-27

- Question : Qui possède l'enveloppe d'événement et la table d'outbox (BE-074 face à BE-150 et BE-234) ?
  - NON DÉFINI : trois tâches définissent une enveloppe ou une outbox. Recommandation appliquée : BE-150 fixe le schéma d'enveloppe, BE-234 possède la table `outbox_events` ; BE-074 ne crée que `inbox_event`. | QE-FAC-28

- Question : Qui possède la table `subscription` (BE-023, BE-071, BE-079) ?
  - NON DÉFINI : la table est déclarée par trois tâches. Recommandation appliquée : BE-023 crée `subscription` ; BE-071 ajoute `payerId`, `beneficiaryTenantId`, `adminUserId` ; BE-079 ajoute les axes d'état. | QE-FAC-29

- Question : Quelle API de changement de droit utilise BE-085 pour PH-09 ?
  - NON DÉFINI : l'API de changement de droit n'est pas décrite dans les sources de ce domaine. Recommandation appliquée : appel interne à BE-024 (entitlements), sans route publique ; le contrat exact est à fixer avec BE-024. | QE-FAC-30

- Question : Faut-il renommer les tables en camelCase, selon la convention du CLAUDE.md du back-end ?
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-FAC-31

## Domaine : administration-interventions (28 QE)

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
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-ADM-28

## Domaine : donnees-api-contrats (37 QE)

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
  - NON DÉFINI : Recommandation appliquée : portée par BE-188 (cycle de session) ; BE-005 doit la renvoyer à BE-188 (à aligner dans BE-005). | QE-API-32
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

## Domaine : exploitation-architecture (31 QE)

- Question : Le fichier CLAUDE.md indique que les phases PH-00 à PH-17 sont validées, alors que les fiches PH-16 et PH-17 et l'architecture intégrée les déclarent DRAFT / BLOCKED.
  - NON DÉFINI : Recommandation appliquée : statut DRAFT / BLOCKED retenu ; tout seuil reste NON DÉFINI jusqu'à décision écrite du décideur | QE-EXP-01
- Question : Quel code HTTP renvoyer pour une ressource hors tenant (403 ou 404) ?
  - NON DÉFINI : Recommandation appliquée : 404 pour une ressource hors portée, 403 pour une permission manquante sur une ressource visible | QE-EXP-02
- Question : Quelle est la durée de rétention du journal d'audit et des journaux opérationnels ?
  - NON DÉFINI : Recommandation appliquée : aucune purge automatique de `audit_event` tant que la durée n'est pas décidée, la durée étant lue de la configuration | QE-EXP-03
- Question : Quels sont les objectifs RPO, RTO et de disponibilité ?
  - NON DÉFINI : Recommandation appliquée : aucune valeur codée ; les tests BE-244 et BE-245 lisent l'objectif depuis la configuration et échouent si elle est vide | QE-EXP-04
- Question : Quels chemins exacts d'API doivent être utilisés, la console opérateur étant nommée `/ops` au registre et `/operator` dans l'implémentation ?
  - NON DÉFINI : Recommandation appliquée : préfixe `/operator` pour l'API conservé (implémentation existante) ; `/ops` reste une route d'interface uniquement | QE-EXP-05
- Question : Quel TTL appliquer aux clés d'idempotence ?
  - NON DÉFINI : Recommandation appliquée : TTL lu de la configuration, aucune constante codée dans le code | QE-EXP-06
- Question : Quels seuils de limite de débit et de détection d'abus appliquer ?
  - NON DÉFINI : Recommandation appliquée : seuils lus de la configuration par environnement ; aucun seuil par défaut codé | QE-EXP-07
- Question : Combien de tentatives de retry avant DLQ et quel intervalle ?
  - NON DÉFINI : Recommandation appliquée : nombre et intervalle lus de la configuration, validés par le test BE-235 | QE-EXP-08
- Question : Quel fournisseur ou mécanisme de secrets, de clés et de sauvegarde retenir ?
  - NON DÉFINI : Recommandation appliquée : interface d'injection de secrets indépendante du fournisseur ; aucun fournisseur choisi dans ce lot | QE-EXP-09
- Question : Quelle topologie d'exécution retenir (monolithe modulaire, services séparés ou hybride) ?
  - NON DÉFINI : Recommandation appliquée : monolithe modulaire à frontières logiques, sans extraction de service dans ce lot ; Q-08 reste ouvert | QE-EXP-10
- Question : Quelle couverture d'astreinte et quels délais d'acquittement ?
  - NON DÉFINI : Recommandation appliquée : chaque alerte routée vers un propriétaire nommé avec runbook (BE-241), sans couverture horaire codée | QE-EXP-11
- Question : Quelles durées de rétention, juridictions et bases légales par classe de donnée ?
  - NON DÉFINI : Recommandation appliquée : inventaire BE-242 sans durée par défaut ; aucune suppression automatique avant décision | QE-EXP-12
- Question : Quels seuils de performance, de capacité et de coût par tenant ?
  - NON DÉFINI : Recommandation appliquée : mesures sans seuil (BE-255) ; aucun budget codé | QE-EXP-13
- Question : Faut-il autoriser l'impersonation ou un accès de bris de glace ?
  - NON DÉFINI : Recommandation appliquée : impersonation interdite ; bris de glace non implémenté ; accès JIT avec approbation distincte uniquement (BE-229) | QE-EXP-14
- Question : Quel mécanisme d'approbation pour les actions sensibles (double contrôle) ?
  - NON DÉFINI : Recommandation appliquée : approbateur distinct du demandeur, journalisé dans `audit_event` ; mécanisme détaillé à décider | QE-EXP-15
- Question : Quel délai de révocation des autorisations après retrait d'une permission ?
  - NON DÉFINI : Recommandation appliquée : revalidation à chaque requête, sans cache d'autorisation, jusqu'à décision de délai | QE-EXP-16
- Question : Quels algorithmes et protocoles cryptographiques imposer ?
  - NON DÉFINI : Recommandation appliquée : aucun algorithme codé dans ce lot ; le référentiel est fixé par la sécurité avant BE-231 | QE-EXP-17
- Question : Quelles garanties de livraison d'événements par flux ?
  - NON DÉFINI : Recommandation appliquée : livraison au moins une fois avec idempotence des consommateurs (Q16-09 candidate), documentée par flux | QE-EXP-18
- Question : Quelles sources de vulnérabilité, criticités, délais de correctif et formats SBOM ?
  - NON DÉFINI : Recommandation appliquée : SBOM produit par révision, délais lus de la configuration, aucun délai codé | QE-EXP-19
- Question : Quel modèle d'isolation (partagé, partitionné ou dédié) ?
  - NON DÉFINI : Recommandation appliquée : aucun modèle choisi ; toute option doit passer les tests BE-225 et BE-248 | QE-EXP-20
- Question : Quels paramètres de canari (durée, cohorte, seuil d'arrêt) ?
  - NON DÉFINI : Recommandation appliquée : paramètres lus de la configuration du flag (BE-251) ; aucune valeur par défaut | QE-EXP-21
- Question : Quel est le dénominateur des parcours critiques pour la matrice de tests (BE-248) ?
  - NON DÉFINI : Recommandation appliquée : dénominateur limité aux parcours listés dans le registre marqués P0 ; extension à décider | QE-EXP-22
- Question : Quelle locale par défaut et quels formats de date et de montant ?
  - NON DÉFINI : Recommandation appliquée : aucune locale codée ; la locale est lue de la configuration (BE-256) | QE-EXP-23
- Question : Le critère P0 de création d'organisation impose-t-il le geste via l'interface ?
  - NON DÉFINI : Recommandation appliquée : le contrat backend se valide par l'API `201` ; le geste interface relève du frontend et reste hors de ce lot | QE-EXP-24
- Question : Les migrations héritées Tanker (`f7a8`, `139b`) bloquent le downgrade jusqu'à base.
  - NON DÉFINI : Recommandation appliquée : hors périmètre socle ; les tests de downgrade visent la tête socle `b7c8d9e0f123` (vérifiée le 2026-11-03) | QE-EXP-25
- Question : Quel identifiant retenir pour le modèle tenant, organisation et adhésions (objet de BE-225, dépendances BE-002 et BE-004) ? Le même objet figure aussi dans BE-100 (portail).
  - NON DÉFINI : Recommandation appliquée : BE-002 (organisation tenant racine) et BE-004 (appartenance) retenus comme socle ; BE-100 à aligner dessus ou à fusionner | QE-EXP-26
- Question : Quel identifiant retenir pour les rôles et permissions (objet de BE-226, dépendance BE-008) ? Le même objet figure aussi dans BE-190 (RBAC serveur).
  - NON DÉFINI : Recommandation appliquée : BE-008 (modèle RBAC) retenu pour BE-226 ; BE-190 à aligner sur BE-008 | QE-EXP-27
- Question : BE-225 (contexte tenant résolu sur toute route) chevauche BE-009 (garde serveur de contexte par route). Faut-il déclarer BE-009 en dépendance de BE-225 ?
  - NON DÉFINI : Recommandation appliquée : pas de dépendance vers BE-009 (sens inverse de la vague) ; la garde BE-009 est réutilisée par route une fois BE-225 livrée | QE-EXP-28
- Question : Le préfixe des routes de la console opérateur est-il `/api/v1/operator` (montage existant) ou `/api/v1/admin` (règle d'administration) ?
  - NON DÉFINI : Recommandation appliquée : `/api/v1/operator` conservé (montage existant de `app/api/v1/router.py`) ; `/api/v1/admin` réservé aux routes d'administration hors console opérateur | QE-EXP-29
- Question : Quelle est la tête Alembic de référence ? Le registre et QE-EXP-25 citent `d8e9f0a1b2c3`, mais `e3c4a8f1b2d6` révise `d8e9f0a1b2c3` sur develop ; la vérification du 2026-11-03 (lecture statique des 80 révisions de develop) donne `b7c8d9e0f123` comme tête unique.
  - NON DÉFINI : Recommandation appliquée : la tête est celle que donne `alembic heads` sur develop (vérification du 2026-11-03, lecture statique : `b7c8d9e0f123`, tête unique) ; BE-223 et les tests de downgrade visent cette tête ; `d8e9f0a1b2c3` ne sert plus que de repère | QE-EXP-30
- Question : quelle casse appliquer aux noms de tables (le CLAUDE.md du backend prévoit des tables camelCase) ?
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-EXP-31

- Note de convention (2026-11-03) : appliqué dans les fichiers exploitation et fondation seulement ; les autres fichiers à aligner (QE-FON-17). Ce fichier ne porte aucune colonne `organizationId`.

## Domaine : fondation-recensement (18 QE)

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

## Domaine : modules-droits (23 QE)

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
  NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-MOD-23

Note : la numérotation QE-MOD-19 dépasse les 18 items de la liste ci-dessus parce que l'incohérence de renvoi est traitée en dernier ; les identifiants QE-MOD-01 à QE-MOD-23 sont utilisés sans trou (QE-MOD-20 à QE-MOD-23 ajoutés lors de la correction des décisions D2 à D4 et de la convention de casse).

## Domaine : parametres-notifications-audit (30 QE)

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

## Domaine : portail-organisation (30 QE)

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

## Domaine : socle-tenant-identite (24 QE)

- Question : la cardinalité entre compte client, payeur et Organization (une ou plusieurs organisations par compte) est-elle tranchée ?
  - NON DÉFINI : Recommandation appliquée : chaque abonnement référence exactement une organisation et chaque organisation a un seul payeur déclaré, vérifié par un test de contrainte. | QE-SOC-01
- Question : la table `passwordResetToken` a-t-elle une classe ORM ou doit-elle rester hors ORM ?
  - NON DÉFINI : Recommandation appliquée : créer la classe ORM dans `app/auth/` et vérifier qu'elle figure dans les métadonnées SQLAlchemy (BE-037, CA-1). | QE-SOC-02
- Question : la table `notificationInboxItem` a-t-elle un modèle ORM et des usages applicatifs ?
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
  - NON DÉFINI : Recommandation appliquée : tables `audit_event` et `subscription_entitlement` gardées telles que décidées ; la convention du CLAUDE.md du backend (tables camelCase) reste à trancher | QE-SOC-24
- Question : quelles colonnes la table `audit_event` doit-elle porter pour le request ID, le résultat et la reprise des tables d'audit opérateur ?
  - NON DÉFINI : Recommandation appliquée : ajouter `request_id` (obligatoire) et `result` (`success` | `refused` | `error`) dans la migration de renommage de BE-007 ; reprendre les lectures de `operatorAuditLog` dans `audit_event` avec une `action` préfixée `operator.`, puis retirer `operatorAuditLog` (BE-030). | QE-SOC-22
- Question : quels sont les valeurs et les rattachements exacts des entitlements (registre de capacités, unité du quota, nullité de l'organisation, effet d'accès) ?
  - NON DÉFINI : Recommandation appliquée : `capaciteId` pointe vers un registre de capacités rattaché au registre de modules (BE-021) ; `quotaLimite` est un entier positif dont l'unité vient du registre ; `organizationId` est nul seulement pour une offre globale (`sourceAttribution` = `offre`) ; `effet_acces` est porté par `status` (`active` | `inactive` | `expired` | `blocked`). | QE-SOC-23

## Anomalies connues à trancher par le relecteur

- (a) Les « EXT » déclarés sont absents de BE-061, BE-176, BE-215 et BE-259 ; les correcteurs ont écrit « Dépendances externes : aucune ».
- (b) BE-176 dépend de tâches de vagues supérieures : sera visible au recalcul.
- (c) Casse des tables `audit_event` et `subscription_entitlement` : convention camelCase du backend, décision de garder les noms.
- (d) Les colonnes camelCase ont été appliquées aux 9 fichiers de tâches, pas au code.

Total : 251 QE distincts ; entrées copiées (lignes « | QE- ») : 252.

Doublons signalés (non corrigés) : QE-PAR-04 (fichier parametres-notifications-audit).
