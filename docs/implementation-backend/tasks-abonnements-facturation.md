# Tâches back-end — Abonnements, facturation et paiements (PH-10)

- **Domaine :** abonnements-facturation (PH-10), back-end uniquement
- **Date de rédaction :** 2026-11-03
- **Agent :** BE-FAC (exécutant de planification, ZYLO-OFFICE-BACKEND-PLAN)
- **Sources lues :**
  - `definition-travail/00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md`
  - `definition-travail/00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md`
  - `definition-travail/03-plateforme/matrice-offres-droits-quotas-entitlements.md` (lecture ciblée : D-01 à D-20, section 4, section 5)
  - Recommandations approuvées le 2026-11-02 (renvoi Q18–31 dans les sources ci-dessus)
- **Plage d'identifiants utilisée :** BE-070 à BE-099 (30 tâches, aucun blocage de plage)
- **Convention de module :** `app/billing/<nom-du-module>` dans le back-end (package existant sur develop, voir D7). Stack observée sur develop : FastAPI, SQLAlchemy, Alembic. Recommandation appliquée : NON DÉFINI, voir QE-FAC-24.
- **Règles transverses appliquées à toutes les tâches :**
  - Le paiement ne vaut jamais droit d'accès ni permission. Chaque droit reste évalué par PH-08 (identité) et PH-09 (entitlements).
  - Aucun montant, prix, devise, taxe, durée, délai ni règle d'accès n'est codé en dur. Les valeurs absentes des sources sont marquées NON DÉFINI et renvoient à un QE-FAC.
  - Chaque endpoint documenté ci-dessous est une recommandation de routage : les sources ne fixent aucun endpoint (voir QE-FAC-01).

## 1. Tableau récapitulatif

| Identifiant | Titre | Nombre de routes | Dépendances |
|---|---|---|---|
| BE-070 | Codes d'erreur normalisés du domaine facturation | 0 | BE-001 |
| BE-071 | Séparation payeur, bénéficiaire (tenant) et administrateur | 0 | BE-070, BE-002, BE-023 |
| BE-072 | Socle d'idempotence et de version optimiste | 0 | BE-070 |
| BE-073 | Journal d'audit append-only des gestes financiers et sensibles | 0 | BE-007, BE-071 |
| BE-074 | Enveloppe d'événement, outbox et inbox | 0 | BE-072, BE-150, BE-234 |
| BE-075 | Capture de la version d'offre au devis et au contrat | 0 | BE-071, BE-023 |
| BE-076 | Consentements versionnés | 1 | BE-071, BE-073 |
| BE-077 | Devis (Quote) : création, lecture, acceptation | 3 | BE-072, BE-075, BE-078 |
| BE-078 | Résolution de prix, devise et taxe (blocage si non configurés) | 0 | BE-075 ; décision finance non prise (EXT non résolu, QE-FAC-26) |
| BE-079 | Agrégat Subscription et états indépendants | 1 | BE-023, BE-071, BE-072 |
| BE-080 | Démarrage d'essai | 1 | BE-076, BE-079 |
| BE-081 | Achat par checkout | 2 | BE-076, BE-077, BE-078, BE-079 |
| BE-082 | Tentatives de paiement (PaymentAttempt) et soumission | 1 | BE-072, BE-081, BE-028 ; PSP définitif non choisi (QE-FAC-11) |
| BE-083 | Ingestion des événements fournisseur (route d'entrée et signature) | 1 | BE-029, BE-163 |
| BE-084 | Confirmation d'abonnement à partir d'un paiement confirmé | 0 | BE-079, BE-081, BE-083 |
| BE-085 | Demande et suivi de changement de droits (entitlement sync) | 0 | BE-074, BE-084, BE-024 |
| BE-086 | Facture (Invoice) : brouillon et finalisation | 2 | BE-072, BE-073, BE-078 |
| BE-087 | Avoir et correction d'une facture finalisée | 1 | BE-086 |
| BE-088 | Changement de plan : aperçu et application | 2 | BE-075, BE-078, BE-079 |
| BE-089 | Renouvellement d'abonnement (job rejouable) | 0 | BE-072, BE-084, BE-086 |
| BE-090 | Résiliation d'abonnement (à échéance ou immédiate) | 1 | BE-073, BE-079 |
| BE-091 | Échec de paiement, grâce et suspension | 0 | BE-079, BE-082, BE-083, BE-085, BE-089 |
| BE-092 | Réactivation après incident ou résiliation | 1 | BE-090, BE-091 |
| BE-093 | Remboursement (RequestRefund) avec approbation humaine | 1 | BE-072, BE-073, BE-082 |
| BE-094 | Litiges (dispute) : ouverture et clôture | 1 | BE-083, BE-093 |
| BE-095 | Réconciliation des paiements et résultats incertains | 1 | BE-082, BE-083, BE-086 |
| BE-096 | Cas de facturation et d'assistance (billing case) | 2 | BE-073, BE-091, BE-093 |
| BE-097 | Clôture d'abonnement (close operation) | 1 | BE-085, BE-090, BE-095 |
| BE-098 | Demande d'export des données de facturation | 1 | BE-073, BE-079, BE-086 |
| BE-099 | Historique commercial consultable par portée | 1 | BE-073, BE-082, BE-086 |

## 2. Tâches

### BE-070 — Codes d'erreur normalisés du domaine facturation
- Domaine : socle transverse (erreurs)
- Vague : 2
- Routes : aucune
- Tables / migrations : aucune
- Droits : aucune permission propre. Règle : un objet hors scope est répondu comme inexistant (même code, même corps), NON DÉFINI pour le code HTTP exact, voir QE-FAC-02.
- Dépendances : BE-001 (enveloppe d'erreur : propriétaire unique du format `{"error": {...}}`, cette tâche ne le redéfinit pas)
- Code existant (develop) : `app/core/errors.py` fournit `AppError(code, message, status_code)` et l'enveloppe `{"error": {code, message, field_errors, details}, "request_id"}` ; garder : `AppError` et l'enveloppe telle quelle (propriété de BE-001) ; casser : les codes existants en minuscules snake_case du billing (`plan_conflict`, `subscription_not_found`, `idempotency_key_conflict`, `provider_not_configured`, etc.), remplacés par le catalogue MAJUSCULES de cette tâche.
- Critères d'acceptation (tests à écrire d'abord) :
  - CA-1 : chacun des 17 codes du catalogue (`FORBIDDEN`, `SCOPE_MISMATCH`, `INVALID_TRANSITION`, `QUOTE_EXPIRED`, `CONSENT_REQUIRED`, `PRICE_NOT_CONFIGURED`, `TAX_NOT_CONFIGURED`, `CURRENCY_NOT_CONFIGURED`, `PAYMENT_DECLINED`, `RESULT_UNKNOWN`, `PROVIDER_UNAVAILABLE`, `DUPLICATE`, `VERSION_CONFLICT`, `REFUND_LIMIT_EXCEEDED`, `ENTITLEMENT_SYNC_PENDING`, `RECONCILIATION_REQUIRED`, `APPROVAL_REQUIRED`) est rendu dans l'enveloppe de BE-001 (`error.code`, `error.message`, `request_id`), sans fuite de détail interne.
  - CA-2 : test de refus de droit : `FORBIDDEN` est renvoyé pour tout appelant sans permission, quel que soit l'objet.
  - CA-3 : test d'isolation tenant : une lecture d'un objet d'un autre tenant renvoie la même réponse qu'un identifiant inexistant (comparaison octet à octet du corps et du code).
  - CA-4 : `RESULT_UNKNOWN` ne se mappe jamais sur un échec (`failed`) dans l'enveloppe.
- Documentation attendue : docstrings de chaque code, doc de module `app/billing/errors` (catalogue lisible d'un seul tenant).
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Erreurs et permissions de contrat`

### BE-071 — Séparation payeur, bénéficiaire (tenant) et administrateur
- Domaine : modèle de données et rattachement
- Vague : 4
- Routes : aucune
- Tables / migrations :
  - `billing_payer` : `id`, `payerKind`, `accountRef`, `createdAt`. Nom et colonnes NON DÉFINI, voir QE-FAC-04.
  - `subscription` : utilise la table `subscription` de BE-023 (non redéfinie ici) ; cette tâche ajoute `payerId`, `beneficiaryTenantId`, `adminUserId` ; états en BE-079 ; propriétaire : QE-FAC-29.
- Droits : aucune route. Règle : aucun droit d'accès n'est déduit du lien payeur. Chaque écriture exige le scope du payeur ou du tenant bénéficiaire (ACTF-04, ACTF-05), refus `SCOPE_MISMATCH`.
- Dépendances : BE-070, BE-002, BE-023 ; compte payeur : frontière tenant/organisation non décidée (QE-FAC-22)
- Code existant (develop) : `app/billing/models.py` porte `Subscription` (table `subscription`, `organizationId` obligatoire, `planId`, `status`) : un abonnement appartient à une seule organisation, pas de payeur distinct ; garder : table `subscription` et ses clés (créée par BE-023) ; casser : `organizationId` comme unique propriétaire, remplacé par `payerId`, `beneficiaryTenantId`, `adminUserId`.
- Critères d'acceptation :
  - CA-1 : un abonnement peut référencer un payeur différent du tenant bénéficiaire, et les deux identifiants sont persistés séparément.
  - CA-2 : test de refus de droit : un payeur qui n'est pas administrateur du tenant ne peut pas changer `adminUserId` (`FORBIDDEN`).
  - CA-3 : test d'isolation tenant : un abonnement du tenant A n'est jamais listé ni lu depuis le scope du tenant B.
  - CA-4 : le paiement enregistré pour un payeur n'accorde aucun droit : test avec paiement réussi et aucune allocation de droit, l'accès résultant reste inchangé.
- Documentation attendue : docstrings des modèles, doc de module `app/billing/payers` expliquant la séparation payeur / bénéficiaire / administrateur.
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé`

### BE-072 — Socle d'idempotence et de version optimiste
- Domaine : socle transverse (idempotence, concurrence)
- Vague : 3
- Routes : aucune (mécanisme appliqué à toutes les commandes mutantes)
- Tables / migrations :
  - `idempotency_record` : `scopeKey` (principal + route + clé), `idempotencyKey`, `commandHash`, `status`, `resultRef`, `createdAt`. Nom et colonnes NON DÉFINI, voir QE-FAC-04.
  - Colonne `version` (entier, verrou optimiste) sur les agrégats `subscription`, `invoice`, `quote`.
- Droits : aucune permission propre. Clé d'idempotence liée au principal appelant ; une clé d'un autre principal ne révèle rien (renvoie comme inconnue).
- Dépendances : BE-070
- Code existant (develop) : `app/billing/service.py` (`create_invoice`, `start_payment_attempt`) traite une clé `idempotencyKey` unique sur `invoice` et `payment_attempt` (`app/billing/models.py`) et renvoie 409 `idempotency_key_conflict` ; aucune colonne `version` sur les agrégats, aucun `commandHash` ; garder : la clé unique par facture et par tentative, jusqu'à migration ; casser : la portée sans principal (clé globale), et les codes snake_case remplacés par `DUPLICATE` et `VERSION_CONFLICT`.
- Critères d'acceptation :
  - CA-1 : même clé + même commande rejoue le résultat initial sans effet de bord supplémentaire.
  - CA-2 : même clé + `commandHash` différent renvoie `DUPLICATE` et ne modifie rien (code HTTP NON DÉFINI, voir QE-FAC-19).
  - CA-3 : écriture avec `expectedVersion` obsolète renvoie `VERSION_CONFLICT` sans modification.
  - CA-4 : test de refus de droit : une clé créée par le principal A n'est pas rejouable par le principal B (réponse identique à une clé inconnue).
- Documentation attendue : docstrings de `IdempotencyService` et du décorateur de commande ; doc de module `app/billing/idempotency`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Idempotence, concurrence, reprise`

### BE-073 — Journal d'audit append-only des gestes financiers et sensibles
- Domaine : audit
- Vague : 5
- Routes : aucune (service interne ; consultation via BE-099)
- Tables / migrations :
  - Aucune table propre (D2) : écrit dans `audit_event`, table unique dont le propriétaire est BE-007 (migration de `audit_log`). Champs requis par cette tâche, à porter par `audit_event` : `actorId`, `scope` (payeur / tenant / bénéficiaire), `action`, `targetType`, `targetId`, `beforeJson`, `afterJson`, `reason`, `approverId`, `result`, `occurredAt`. Correspondance exacte avec les colonnes de `audit_event` : NON DÉFINI, voir QE-FAC-04 et QE-FAC-13.
- Droits : écriture par le service uniquement ; aucune route d'écriture publique. Lecture via BE-099 avec permission d'audit (PH-08, NON DÉFINI, voir QE-FAC-03).
- Dépendances : BE-007, BE-071
- Critères d'acceptation :
  - CA-1 : chaque geste sensible (approbation de remboursement, changement de plan, résiliation, finalisation de facture) écrit exactement une entrée avant/après dans `audit_event`.
  - CA-2 : test de refus : un `UPDATE` ou `DELETE` sur `audit_event` pour une entrée financière est refusé par la base (ou le service) ; la trace originelle est intacte.
  - CA-3 : test d'isolation tenant : une entrée du tenant A n'apparaît pas dans une lecture de scope tenant B.
  - CA-4 : une entrée sans `reason` pour un geste marqué sensible est refusée (`APPROVAL_REQUIRED` ou erreur de validation, NON DÉFINI, voir QE-FAC-02).
- Documentation attendue : docstrings de `record_audit_entry` ; doc de module `app/billing/audit`.
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Démarche pas à pas` (étape 6, audit) ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-19)

### BE-074 — Enveloppe d'événement, outbox et inbox
- Domaine : événements
- Vague : 8
- Routes : aucune
- Tables / migrations :
  - Outbox : aucune table propre (QE-FAC-28) ; écrit dans `outbox_events` de BE-234. Champs que l'enveloppe facturation doit fournir : `eventId`, `eventType`, `eventVersion`, `aggregateId`, `aggregateVersion`, `tenantScope`, `payerScope`, `operationId`, `correlationId`, `causationId`, `occurredAt`, `payloadJson`.
  - `inbox_event` (créée ici) : `provider`, `providerEventId` (clé unique), `receivedAt`, `status`, `quarantineFlag`.
  - Schéma d'enveloppe : celui de BE-150 ; liste et noms NON DÉFINI, voir QE-FAC-04 ; enveloppe versionnée, voir QE-FAC-17.
- Droits : aucune route. Les événements ne transportent aucun PAN, CVV ni secret.
- Dépendances : BE-072, BE-150, BE-234 (publication, ordre, rétention et rejeu : PH-14 ; décisions portées par BE-234)
- Critères d'acceptation :
  - CA-1 : écrire une commande et son événement dans la même transaction locale ; un échec d'écriture de l'événement annule la commande.
  - CA-2 : un événement reçu deux fois (même `providerEventId`) est ignoré à la seconde réception.
  - CA-3 : un événement hors ordre ne fait pas régresser un état confirmé.
  - CA-4 : test de refus / sécurité : un payload contenant un champ de type PAN ou CVV est rejeté avant persistance.
- Documentation attendue : docstrings des modèles d'enveloppe ; doc de module `app/billing/events`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Événements et commandes conceptuels` ; `#Idempotence, concurrence, reprise`

### BE-075 — Capture de la version d'offre au devis et au contrat
- Domaine : catalogue (consommation)
- Vague : 5
- Routes : aucune
- Tables / migrations :
  - `plan_version_snapshot` : `id`, `planRef`, `planVersion`, `capturedAt`, `sourceCatalogueRef`, `snapshotJson` (immuable).
  - Champs exacts NON DÉFINI, voir QE-FAC-04.
- Droits : lecture interne uniquement. Aucune permission client directe sur le catalogue.
- Dépendances : BE-071, BE-023 (catalogue `plan` et `planVersion` : versions publiées immuables ; retrait sans effet sur les souscriptions existantes, voir QE-FAC-10)
- Critères d'acceptation :
  - CA-1 : un devis capture la version publiée de l'offre ; une modification ultérieure du catalogue n'altère pas le snapshot.
  - CA-2 : une offre au statut `withdrawn` ne peut plus être capturée pour un nouveau devis (`INVALID_TRANSITION`), mais un abonnement existant la conserve.
  - CA-3 : test de refus : un appelant sans droit de lecture catalogue ne peut pas lire `snapshotJson` (`FORBIDDEN`).
  - CA-4 : test d'isolation tenant : un snapshot du tenant A n'est pas visible depuis le tenant B.
- Documentation attendue : docstrings ; doc de module `app/billing/catalog_snapshot`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (agrégat Offre/plan)

### BE-076 — Consentements versionnés
- Domaine : consentement
- Vague : 6
- Routes :
  - `POST /api/v1/billing/consents`
- Tables / migrations :
  - `consent_record` : `id`, `personId`, `accountId`, `consentTextVersion`, `scope`, `recordedAt`, `correctionOfId` (nullable). Append-only. Colonnes exactes NON DÉFINI, voir QE-FAC-16.
- Droits : permission d'acheteur ACTF-04 (scope payeur) ou ACTF-05 (contact de facturation). Refus `FORBIDDEN` (403 recommandé, QE-FAC-02). Un consentement pour un autre compte renvoie `SCOPE_MISMATCH`.
- Dépendances : BE-071, BE-073
- Critères d'acceptation :
  - CA-1 : un consentement enregistré porte la version du texte, la personne, le compte, l'heure et le scope.
  - CA-2 : une correction crée une nouvelle entrée liée (`correctionOfId`) ; l'entrée d'origine reste inchangée.
  - CA-3 : test de refus : un ACTF sans permission d'acheteur reçoit `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : un consentement d'un compte du tenant A est refusé pour le tenant B (`SCOPE_MISMATCH`).
- Documentation attendue : docstrings de la route et du service ; doc de module `app/billing/consents`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Consentement) ; `#Événements et commandes conceptuels` (`RecordConsent`)

### BE-077 — Devis (Quote) : création, lecture, acceptation
- Domaine : achat
- Vague : 7
- Routes :
  - `POST /api/v1/billing/quotes`
  - `GET /api/v1/billing/quotes/{quoteId}`
  - `POST /api/v1/billing/quotes/{quoteId}/accept`
- Tables / migrations :
  - `quote` : `id`, `payerId`, `beneficiaryTenantId`, `planVersionSnapshotId`, `status`, `version`, `expiresAt`, `createdAt`. Statuts `created → priced → accepted | expired | revoked`. Colonnes exactes NON DÉFINI, voir QE-FAC-04 ; durée d'expiration NON DÉFINI, voir QE-FAC-21.
- Droits : `POST` et `accept` exigent ACTF-04 (acheteur) ; `GET` exige ACTF-04 ou ACTF-05 dans le scope payeur. Refus `FORBIDDEN` (403 recommandé). Objet hors scope : réponse identique à l'inexistant (404 recommandé, QE-FAC-02).
- Dépendances : BE-072, BE-075, BE-078
- Critères d'acceptation :
  - CA-1 : un devis `created` sans prix configuré passe en `priced` seulement si BE-078 réussit ; sinon la réponse porte `PRICE_NOT_CONFIGURED` et le devis reste `created`.
  - CA-2 : `accept` sur un devis `expired` renvoie `QUOTE_EXPIRED` et ne crée aucune souscription.
  - CA-3 : test de refus : `accept` par un ACTF sans permission d'acheteur renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : `GET` d'un devis du tenant A avec un scope B renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings des 3 routes ; doc de module `app/billing/quotes` ; doc des états.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Quote/checkout) ; `#Événements et commandes conceptuels` (`CreateQuote`, `QuoteAccepted`)

### BE-078 — Résolution de prix, devise et taxe (blocage si non configurés)
- Domaine : facturation (paramétrage)
- Vague : 6
- Routes : aucune (service interne utilisé par BE-077, BE-081, BE-086, BE-088)
- Tables / migrations : `price_rule` (prix, devise, taxe par objet et scénario) : colonnes et valeurs NON DÉFINI, voir QE-FAC-06 ; aucune valeur n'est insérée.
- Droits : interne ; aucune route. L'autorité par objet et scénario est finance (catalogue PH-09 pour l'offre), voir QE-FAC-10.
- Dépendances : BE-075 ; décision finance sur prix, taxes, devise : EXT non résolu (aucune tâche d'objet correspondant ; QE-FAC-26). BE-077 dépend de cette tâche, et non l'inverse.
- Critères d'acceptation :
  - CA-1 : sans règle configurée, la résolution renvoie `PRICE_NOT_CONFIGURED`, `TAX_NOT_CONFIGURED` ou `CURRENCY_NOT_CONFIGURED` selon le cas ; aucun montant par défaut n'est retourné.
  - CA-2 : une règle configurée fixe devise et taxe, et le snapshot du devis les capture.
  - CA-3 : test de refus : une règle modifiée après acceptation d'un devis ne change pas le montant accepté.
  - CA-4 : test d'isolation tenant : une règle d'un tenant n'est jamais appliquée à un autre tenant.
- Documentation attendue : docstrings ; doc de module `app/billing/pricing`, avec la mention explicite « valeurs non définies ».
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-05, D-16)

### BE-079 — Agrégat Subscription et états indépendants
- Domaine : abonnement
- Vague : 5
- Routes :
  - `GET /api/v1/billing/subscriptions/{subscriptionId}`
- Tables / migrations :
  - `subscription` : utilise la table `subscription` de BE-023 (non redéfinie ici) ; colonnes ajoutées par BE-071 (`payerId`, `beneficiaryTenantId`, `adminUserId`) ; colonnes ajoutées par cette tâche : `lifecycleStatus`, `financialStatus`, `incidentStatus` ; `version` ajoutée par BE-072. Trois axes séparés, ne jamais fusionner en un seul état.
  - Colonnes exactes NON DÉFINI, voir QE-FAC-04 ; propriétaire de l'objet voir QE-FAC-10.
- Droits : `GET` exige ACTF-04 ou ACTF-05 dans le scope payeur, ou un rôle d'administration du tenant bénéficiaire (PH-08, NON DÉFINI). Refus `FORBIDDEN` ; hors scope : réponse de l'inexistant.
- Dépendances : BE-023, BE-071, BE-072
- Critères d'acceptation :
  - CA-1 : les trois axes (`lifecycle`, `financial`, `incident`) sont persistés et lisibles séparément ; une transition sur un axe ne modifie pas les deux autres.
  - CA-2 : une transition non prévue par la machine d'état renvoie `INVALID_TRANSITION`.
  - CA-3 : test de refus : `GET` sans permission renvoie `FORBIDDEN` ; un état `active` seul n'accorde aucun droit (test de lecture de droits = inchangé).
  - CA-4 : test d'isolation tenant : un abonnement du tenant A renvoie la réponse de l'inexistant au scope B.
- Documentation attendue : docstrings ; doc de module `app/billing/subscriptions` avec tableau des transitions.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Subscription)

### BE-080 — Démarrage d'essai
- Domaine : abonnement
- Vague : 7
- Routes :
  - `POST /api/v1/billing/subscriptions/trials`
- Tables / migrations : écrit dans `subscription` (BE-079) et `consent_record` (BE-076). Champs `trialEnd`, `timezone`, `calendarBounds` : NON DÉFINI, voir QE-FAC-05.
- Droits : ACTF-04 acheteur, scope payeur. Refus `FORBIDDEN`. Consentement explicite obligatoire par défaut (recommandation approuvée 2026-11-02) : absence renvoie `CONSENT_REQUIRED`.
- Dépendances : BE-076, BE-079
- Critères d'acceptation :
  - CA-1 : sans consentement enregistré, la requête renvoie `CONSENT_REQUIRED` et ne crée aucun abonnement.
  - CA-2 : avec consentement, l'abonnement passe à `trialing` ; l'événement `TrialStarted` est écrit dans l'outbox.
  - CA-3 : test de refus : un ACTF non acheteur reçoit `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : démarrer un essai sur un payeur du tenant A depuis le scope B renvoie `SCOPE_MISMATCH` ou la réponse de l'inexistant (QE-FAC-02).
  - CA-5 : le démarrage d'un essai ne crée aucun droit d'accès (pas d'allocation dans PH-09 sans BE-085).
- Documentation attendue : docstrings de la route ; doc de module `app/billing/trials`.
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-14)

### BE-081 — Achat par checkout
- Domaine : achat
- Vague : 8
- Routes :
  - `POST /api/v1/billing/checkouts`
  - `GET /api/v1/billing/checkouts/{checkoutId}`
- Tables / migrations :
  - `checkout` : `id`, `quoteId`, `status`, `version`, `createdAt`. Statuts `open → pending → completed | failed | cancelled | expired`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : `POST` exige ACTF-04 ; `GET` ACTF-04 ou ACTF-05, scope payeur. Refus `FORBIDDEN`. Devis non `priced` : `QUOTE_EXPIRED` ou `INVALID_TRANSITION` selon le cas.
- Dépendances : BE-076, BE-077, BE-078, BE-079
- Critères d'acceptation :
  - CA-1 : un checkout n'est créé que depuis un devis `accepted` avec consentement requis enregistré (`CONSENT_REQUIRED` sinon).
  - CA-2 : le retour de l'interface (`completed` côté client) ne passe pas le checkout à `completed` tant que BE-083 n'a pas confirmé le paiement.
  - CA-3 : test de refus : `POST` sans permission ACTF-04 renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : `GET` d'un checkout du tenant A depuis le scope B renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/checkouts` (transitions).
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Quote/checkout ; « retour UI ne prouve pas paiement ») ; `#Événements et commandes conceptuels` (`StartCheckout`)

### BE-082 — Tentatives de paiement (PaymentAttempt) et soumission
- Domaine : paiement
- Vague : 9
- Routes :
  - `POST /api/v1/billing/checkouts/{checkoutId}/payment-attempts`
- Tables / migrations :
  - `payment_attempt` : `id`, `checkoutId`, `invoiceId` (nullable), `installmentRef`, `providerRef` (nullable), `status`, `version`, `submittedAt`. Statuts `created → submitted → requires_action | pending | unknown | succeeded | failed | cancelled`. Colonnes NON DÉFINI, voir QE-FAC-04.
  - Aucun numéro de carte n'est stocké (minimisation des données de paiement).
- Droits : ACTF-04 acheteur, scope payeur. Refus `FORBIDDEN`. Déclinaison : `PAYMENT_DECLINED` ; fournisseur indisponible : `PROVIDER_UNAVAILABLE`. Codes HTTP NON DÉFINI, voir QE-FAC-02.
- Dépendances : BE-072, BE-081, BE-028 (adaptateur neutre existant, stub et sandbox) ; PSP définitif non choisi : NON DÉFINI, voir QE-FAC-11
- Critères d'acceptation :
  - CA-1 : la commande est enregistrée avant l'appel fournisseur (`created` puis `submitted`).
  - CA-2 : un délai dépassé sans réponse place la tentative en `unknown`, jamais `failed`.
  - CA-3 : test de refus : soumission sans permission ACTF-04 renvoie `FORBIDDEN` et n'appelle pas le fournisseur.
  - CA-4 : test d'isolation tenant : une tentative d'un checkout du tenant A n'est pas soumise depuis le scope B.
  - CA-5 : aucune donnée de carte ne figure dans la base (test de schéma et de payload).
- Documentation attendue : docstrings ; doc de module `app/billing/payment_attempts` ; interface d'adaptateur fournisseur documentée (adaptateur fictif pour les tests).
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (PaymentAttempt) ; `#Erreurs et permissions de contrat` ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-17)

### BE-083 — Ingestion des événements fournisseur et déduplication
- Domaine : paiement / événements
- Vague : 13
- Routes :
  - `POST /api/v1/billing/provider-events`
- Périmètre : cette tâche ne décrit que la route d'entrée et la vérification de signature. La table d'idempotence des évènements, la déduplication, la quarantaine et l'effet métier sont portés par BE-029 (table `payment_webhook_event`), dont cette tâche dépend. Aucune table propre.
- Tables / migrations : aucune table propre ; table d'idempotence de BE-029.
- Droits : aucune permission utilisateur. Authentification par signature fournisseur (ACTF-11). Signature absente ou invalide : refus (401 recommandé, QE-FAC-12). Rotation des secrets : NON DÉFINI, voir QE-FAC-12.
- Dépendances : BE-029, BE-163 (signature, tenant ; le périmètre déduplication est BE-029 : voir QE-FAC-27)
- Critères d'acceptation :
  - CA-1 : un événement à signature invalide est rejeté sans persistance.
  - CA-2 : test de refus : un appelant sans signature reçoit le refus 401, pas un message d'erreur interne.
  - CA-3 : un événement à signature valide est transmis au service de BE-029 sans traitement métier dans cette tâche (test de contrat).
- Documentation attendue : docstrings ; doc de module `app/billing/provider_events`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Idempotence, concurrence, reprise` ; `#Questions de compatibilité/version` (PH-13 signature)

### BE-084 — Confirmation d'abonnement à partir d'un paiement confirmé
- Domaine : abonnement / paiement
- Vague : 14
- Routes : aucune (déclenchée par BE-083)
- Tables / migrations : met à jour `subscription` (BE-079) : `pending → active` ; émet `SubscriptionActivated` dans l'outbox (BE-074).
- Droits : interne ; aucune route. Refus de droit non applicable (déclenchement système, ACTF-12).
- Dépendances : BE-079, BE-081, BE-083
- Critères d'acceptation :
  - CA-1 : un paiement `succeeded` confirmé passe l'abonnement à `active` et émet `SubscriptionActivated`.
  - CA-2 : un succès fournisseur avec échec local est repris par la finalisation (outbox), sans nouvelle capture (test de non-double-débit).
  - CA-3 : un paiement `unknown` ne déclenche pas l'activation.
  - CA-4 : test d'isolation tenant : la confirmation ne modifie que l'abonnement du checkout concerné.
- Documentation attendue : docstrings ; doc de module `app/billing/activation`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Idempotence, concurrence, reprise` (success externe + échec local) ; `#Événements et commandes conceptuels` (`ConfirmSubscription`)

### BE-085 — Demande et suivi de changement de droits (entitlement sync)
- Domaine : droits (intégration)
- Vague : 15
- Routes : aucune (interne)
- Tables / migrations : `entitlement_sync` : `id`, `subscriptionId`, `status` (`requested | applied | failed | retry_pending`), `attempts`, `lastErrorCode`, `requestedAt`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : interne ; PH-09 reste la seule autorité de droits. Le paiement ne crée aucun droit.
- Dépendances : BE-074, BE-084, BE-024 (PH-09 seule autorité de droits ; API de changement de droit non décrite, voir QE-FAC-30)
- Critères d'acceptation :
  - CA-1 : une synchronisation `failed` ne revient jamais à `succeeded` sans nouvelle demande (`ENTITLEMENT_SYNC_PENDING` tant que non appliquée).
  - CA-2 : paiement réussi et droits non confirmés : l'abonnement reste commercialement `active`, l'incident de cohérence est ouvert, sans re-débit (test de non-double-débit).
  - CA-3 : test de refus : la synchronisation ne peut pas être déclenchée depuis une route publique (aucune route, test de routage).
  - CA-4 : test d'isolation tenant : une synchronisation ne modifie que les droits du tenant du scope de l'abonnement.
- Documentation attendue : docstrings ; doc de module `app/billing/entitlement_sync`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Entitlement sync) ; `#Erreurs et permissions de contrat` (`ENTITLEMENT_SYNC_PENDING`)

### BE-086 — Facture (Invoice) : brouillon et finalisation
- Domaine : facturation
- Vague : 7
- Routes :
  - `POST /api/v1/billing/invoices/{invoiceId}/finalize`
  - `GET /api/v1/billing/invoices/{invoiceId}`
- Tables / migrations :
  - `invoice` : `id`, `subscriptionId`, `status`, `currency`, `taxSnapshot`, `total`, `version`, `finalizedAt`. Statuts `draft → finalized → open | partially_paid | paid`. Montants, lignes, numérotation : NON DÉFINI, voir QE-FAC-15.
  - `invoice_line` : `invoiceId`, `label`, `quantity`, `unitAmount`, `taxRate`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : `finalize` exige ACTF-09 (finance) ; `GET` ACTF-09 ou ACTF-05 dans le scope payeur. Refus `FORBIDDEN`. Hors scope : réponse de l'inexistant.
- Dépendances : BE-072, BE-073, BE-078
- Critères d'acceptation :
  - CA-1 : une facture finalisée est append-only ; toute modification renvoie `INVALID_TRANSITION` ou refus base.
  - CA-2 : finaliser sans devise ni taxe configurées renvoie `CURRENCY_NOT_CONFIGURED` ou `TAX_NOT_CONFIGURED` ; aucune facture n'est finalisée.
  - CA-3 : test de refus : `finalize` par un ACTF sans permission finance renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : `GET` d'une facture du tenant A depuis le scope B renvoie la réponse de l'inexistant.
  - CA-5 : la finalisation écrit une entrée d'audit et `InvoiceFinalized` dans l'outbox.
- Documentation attendue : docstrings ; doc de module `app/billing/invoices`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Invoice/Credit) ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-16)

### BE-087 — Avoir et correction d'une facture finalisée
- Domaine : facturation
- Vague : 8
- Routes :
  - `POST /api/v1/billing/invoices/{invoiceId}/credit-notes`
- Tables / migrations : `credit_note` : `id`, `invoiceId` (lien obligatoire), `amount`, `currency`, `reason`, `status`, `createdAt`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : ACTF-09 (finance), approbation ACTF-08 si la règle d'approbation l'exige (NON DÉFINI, voir QE-FAC-09). Refus `FORBIDDEN` ; approbation absente : `APPROVAL_REQUIRED`.
- Dépendances : BE-086
- Critères d'acceptation :
  - CA-1 : un avoir est toujours lié à une facture finalisée ; la facture d'origine n'est pas modifiée.
  - CA-2 : un avoir sans motif est refusé.
  - CA-3 : test de refus : une demande d'avoir sans approbation requise renvoie `APPROVAL_REQUIRED` ; sans permission finance, `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : un avoir ne peut viser qu'une facture du même scope.
- Documentation attendue : docstrings ; doc de module `app/billing/credit_notes`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Invoice/Credit : `finalized → credited/voided` selon règle approuvée)

### BE-088 — Changement de plan : aperçu et application
- Domaine : abonnement
- Vague : 7
- Routes :
  - `POST /api/v1/billing/subscriptions/{subscriptionId}/plan-change/preview`
  - `POST /api/v1/billing/subscriptions/{subscriptionId}/plan-change`
- Tables / migrations : `plan_change` : `id`, `subscriptionId`, `targetPlanVersionSnapshotId`, `direction` (`upgrade | downgrade`), `effectiveAt`, `status`, `previewJson`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : ACTF-04 acheteur, scope payeur. Refus `FORBIDDEN`. Hors scope : réponse de l'inexistant.
- Dépendances : BE-075, BE-078, BE-079
- Critères d'acceptation :
  - CA-1 : un downgrade est appliqué à échéance, jamais immédiatement (recommandation approuvée).
  - CA-2 : l'aperçu d'upgrade renvoie les effets financiers sans formule de prorata calculée ; le prorata est NON DÉFINI, la réponse signale son absence par un code NON DÉFINI (voir QE-FAC-05) ; aucun montant inventé.
  - CA-3 : test de refus : la demande sans permission acheteur renvoie `FORBIDDEN` ; aucune modification de l'abonnement.
  - CA-4 : test d'isolation tenant : un changement de plan sur un abonnement d'un autre tenant renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/plan_changes`.
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Recommandations approuvées le 2026-11-02 — choix détaillé différé` (downgrade à échéance, aperçu d'upgrade) ; `#Événements et commandes conceptuels` (`ChangePlan`)

### BE-089 — Renouvellement d'abonnement (job rejouable)
- Domaine : abonnement
- Vague : 15
- Routes : aucune (job système)
- Tables / migrations : `renewal_run` : `subscriptionId`, `periodKey`, `status`, `attemptedAt`. Clé de déduplication : subscription + période + type. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : système (ACTF-12). Aucune permission utilisateur.
- Dépendances : BE-072, BE-084, BE-086
- Critères d'acceptation :
  - CA-1 : rejouer le job pour la même période ne crée pas de deuxième facture ni de deuxième tentative.
  - CA-2 : un renouvellement sur abonnement `cancelled` ou `expired` ne s'exécute pas (`INVALID_TRANSITION` journalisé).
  - CA-3 : test de refus : le job ne peut pas être déclenché par un utilisateur sans rôle système (`FORBIDDEN`).
  - CA-4 : test d'isolation tenant : un job traite un abonnement à la fois, sans écriture sur un autre scope.
- Documentation attendue : docstrings ; doc de module `app/billing/renewal_job`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Idempotence, concurrence, reprise` (job d'échéance rejouable, clé de période) ; `#Événements et commandes conceptuels` (`RenewSubscription`)

### BE-090 — Résiliation d'abonnement (à échéance ou immédiate)
- Domaine : abonnement
- Vague : 6
- Routes :
  - `POST /api/v1/billing/subscriptions/{subscriptionId}/cancel`
- Tables / migrations : `subscription` (BE-079) ; champs `cancelMode` (`end_of_period | immediate`), `cancelEffectiveAt`. Mode par défaut : à échéance, voir QE-FAC-08.
- Droits : ACTF-04 acheteur, scope payeur ; ou administrateur du tenant (NON DÉFINI, QE-FAC-03). Refus `FORBIDDEN`. Hors scope : réponse de l'inexistant.
- Dépendances : BE-073, BE-079
- Critères d'acceptation :
  - CA-1 : la résiliation par défaut passe en `cancel_scheduled` et ne coupe rien avant l'échéance.
  - CA-2 : une résiliation immédiate est refusée tant que QE-FAC-08 n'est pas tranché (réponse `INVALID_TRANSITION` ou refus de mode, code NON DÉFINI) ; la résiliation à échéance reste disponible.
  - CA-3 : test de refus : résiliation sans permission renvoie `FORBIDDEN` ; l'abonnement reste inchangé.
  - CA-4 : test d'isolation tenant : résilier un abonnement d'un autre tenant renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/cancellation`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Subscription) ; `#Événements et commandes conceptuels` (`CancelSubscription`) ; `PH-10...#Recommandations approuvées le 2026-11-02` (résiliation selon contrat)

### BE-091 — Échec de paiement, grâce et suspension
- Domaine : paiement / incident
- Vague : 16
- Routes : aucune (transitions déclenchées par BE-082, BE-083, BE-089)
- Tables / migrations : `subscription.incidentStatus` (`past_due | grace | suspended | disputed | incomplete`) ; `graceUntil` (nullable). Durée de grâce NON DÉFINI, voir QE-FAC-07.
- Droits : système. Effet d'accès pendant incident : NON DÉFINI (QE-FAC-07) ; recommandation appliquée : aucun changement de droit automatique (PH-09 non modifié).
- Dépendances : BE-079, BE-082, BE-083, BE-085, BE-089
- Critères d'acceptation :
  - CA-1 : un échec `failed` fait passer `incidentStatus` à `past_due` et émet `PaymentAttemptSubmitted/Failed` sans toucher à `lifecycleStatus`.
  - CA-2 : aucune suspension automatique n'est appliquée tant que la durée de grâce et la politique d'accès ne sont pas décidées (test : aucun appel à BE-085 suspensif).
  - CA-3 : test de refus : une transition `suspended` manuelle sans permission renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : l'incident d'un tenant n'affecte pas un autre tenant.
- Documentation attendue : docstrings ; doc de module `app/billing/incidents`.
- Source : `00-pilotage/architecture-fondation/phases/PH-10-abonnements-facturation-paiements.md#Démarche pas à pas` (étape 3) ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-15, Q-05)

### BE-092 — Réactivation après incident ou résiliation
- Domaine : abonnement
- Vague : 17
- Routes :
  - `POST /api/v1/billing/subscriptions/{subscriptionId}/reactivate`
- Tables / migrations : `subscription` (BE-079) ; événement `SubscriptionActivated` (BE-074).
- Droits : ACTF-04 acheteur, scope payeur. Refus `FORBIDDEN`. Réactivation exige un paiement confirmé (BE-083) : sinon `PAYMENT_DECLINED` ou `RECONCILIATION_REQUIRED` selon le cas.
- Dépendances : BE-090, BE-091
- Critères d'acceptation :
  - CA-1 : réactivation sans paiement confirmé est refusée ; l'état reste inchangé.
  - CA-2 : réactivation d'un abonnement `closed` renvoie `INVALID_TRANSITION`.
  - CA-3 : test de refus : réactivation sans permission acheteur renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : réactivation d'un abonnement d'un autre tenant renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/reactivation`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Subscription : `expired/cancelled → ...`) ; `PH-10...#Démarche pas à pas` (étape 3, reprise)

### BE-093 — Remboursement (RequestRefund) avec approbation humaine
- Domaine : paiement / finance
- Vague : 10
- Routes :
  - `POST /api/v1/billing/payments/{paymentId}/refunds`
- Tables / migrations : `refund` : `id`, `paymentAttemptId`, `amount`, `currency`, `status` (`requested | pending | succeeded | failed`), `approverId`, `reason`, `request_id`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : demande ACTF-09 (finance) ; approbation ACTF-08 obligatoire. Refus `FORBIDDEN` ; sans approbation : `APPROVAL_REQUIRED` ; au-delà du seuil : `REFUND_LIMIT_EXCEEDED`. Seuil NON DÉFINI : recommandation appliquée, voir QE-FAC-09.
- Dépendances : BE-072, BE-073, BE-082
- Critères d'acceptation :
  - CA-1 : aucun remboursement n'est exécuté sans approbation enregistrée (test de séquence).
  - CA-2 : un second remboursement avec la même clé de requête (`payment` + `request`) rejoue le résultat, sans second envoi fournisseur.
  - CA-3 : test de refus : une demande sans permission finance renvoie `FORBIDDEN` ; l'approbateur ne peut pas être le demandeur (`SCOPE_MISMATCH` ou refus NON DÉFINI, QE-FAC-02).
  - CA-4 : test d'isolation tenant : rembourser un paiement d'un autre tenant renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/refunds`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Refund/dispute) ; `#Idempotence, concurrence, reprise` (refund par payment+request) ; `PH-10...#Recommandations approuvées le 2026-11-02` (contrôle humain)

### BE-094 — Litiges (dispute) : ouverture et clôture
- Domaine : paiement / incident
- Vague : 14
- Routes :
  - `GET /api/v1/billing/disputes/{disputeId}`
- Tables / migrations : `dispute` : `id`, `paymentAttemptId`, `status` (`opened | evidence_due | under_review | won | lost | withdrawn`), `providerRef`, `openedAt`, `resolvedAt`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : `GET` ACTF-09 (finance) ou ACTF-07 (support), scope du tenant concerné. Refus `FORBIDDEN`. Ouverture uniquement par événement fournisseur (BE-083), donc aucune route d'écriture publique.
- Dépendances : BE-083, BE-093
- Critères d'acceptation :
  - CA-1 : un litige ouvert par événement fournisseur passe à `opened` et met `incidentStatus` à `disputed` (BE-091).
  - CA-2 : un litige clôturé `lost` ne déclenche aucune écriture automatique de remboursement.
  - CA-3 : test de refus : `GET` sans permission finance ou support renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : un litige du tenant A est invisible depuis le scope B.
- Documentation attendue : docstrings ; doc de module `app/billing/disputes`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Refund/dispute) ; `#Événements et commandes conceptuels` (`DisputeOpened/Resolved`)

### BE-095 — Réconciliation des paiements et résultats incertains
- Domaine : paiement / finance
- Vague : 14
- Routes :
  - `POST /api/v1/billing/reconciliations`
- Tables / migrations : `reconciliation_run` : `id`, `scope`, `periodKey`, `status`, `differenceCount`, `startedAt`. `reconciliation_difference` : `id`, `runId`, `paymentAttemptId`, `status`. Colonnes NON DÉFINI, voir QE-FAC-04 ; source d'autorité NON DÉFINI, voir QE-FAC-11.
- Droits : ACTF-09 (finance) ; ACTF-06/07 (support) pour consultation. Refus `FORBIDDEN`. Hors scope : réponse de l'inexistant.
- Dépendances : BE-082, BE-083, BE-086
- Critères d'acceptation :
  - CA-1 : une tentative `unknown` est recherchée auprès du fournisseur sous la même référence avant toute nouvelle capture (test de non-double-débit).
  - CA-2 : un écart détecté crée `ReconciliationDifferenceDetected` sans correction automatique.
  - CA-3 : test de refus : lancer une réconciliation sans permission finance renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : une réconciliation ne porte que sur le scope demandé.
- Documentation attendue : docstrings ; doc de module `app/billing/reconciliation`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Idempotence, concurrence, reprise` (timeout → unknown + lookup) ; `#Machine d'état conceptuelle` (PaymentAttempt, ledger local)

### BE-096 — Cas de facturation et d'assistance (billing case)
- Domaine : support / cas
- Vague : 17
- Routes :
  - `POST /api/v1/billing/cases`
  - `POST /api/v1/billing/cases/{caseId}/resolve`
- Tables / migrations : `billing_case` : `id`, `scope`, `subjectRef`, `status` (`open | assigned | investigating | action_pending | resolved | closed | escalated`), `assigneeId`, `reason`, `openedAt`. Colonnes NON DÉFINI, voir QE-FAC-04 ; autorité de la file, voir QE-FAC-14.
- Droits : ACTF-06/07 (support, moindre privilège, Q-06) ; `resolve` exige approbation indépendante pour toute action sensible (NON DÉFINI, QE-FAC-09). Refus `FORBIDDEN`.
- Dépendances : BE-073, BE-091, BE-093
- Critères d'acceptation :
  - CA-1 : un cas `open` ou `assigned` n'empêche pas la fermeture d'un abonnement et ne se ferme jamais en cascade (test de non-cascade).
  - CA-2 : un cas ne peut être `resolved` sans motif et sans entrée d'audit (BE-073).
  - CA-3 : test de refus : un ACTF support sans permission d'action sensible renvoie `FORBIDDEN` ; aucune impersonation n'est possible (test de routage).
  - CA-4 : test d'isolation tenant : un cas d'un tenant n'est pas visible depuis un autre scope.
- Documentation attendue : docstrings ; doc de module `app/billing/cases`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Billing/support case) ; `#Erreurs et permissions de contrat` (support sensibles, pas d'impersonation) ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#2. Matrice des axes et décisions ouvertes` (D-18)

### BE-097 — Clôture d'abonnement (close operation)
- Domaine : abonnement
- Vague : 16
- Routes :
  - `POST /api/v1/billing/subscriptions/{subscriptionId}/close`
- Tables / migrations : `close_operation` : `id`, `subscriptionId`, `status` (`requested | close_pending_finance | close_pending_entitlement | close_pending_data | completed | blocked | escalated`), `prerequisitesJson`, `requestedAt`. Colonnes NON DÉFINI, voir QE-FAC-04.
- Droits : ACTF-04 acheteur ou ACTF-09 finance selon l'étape ; administrateur du tenant (NON DÉFINI, QE-FAC-03). Refus `FORBIDDEN`. Hors scope : réponse de l'inexistant.
- Dépendances : BE-085, BE-090, BE-095
- Critères d'acceptation :
  - CA-1 : `subscription_closed` n'est écrit qu'après vérification de chaque prérequis requis (finance, droits, données) ; un prérequis manquant bloque la clôture.
  - CA-2 : un cas support ouvert (BE-096) n'empêche pas la clôture (non-bloquant).
  - CA-3 : test de refus : clôture sans permission renvoie `FORBIDDEN` ; l'abonnement reste inchangé.
  - CA-4 : test d'isolation tenant : clôturer un abonnement d'un autre tenant renvoie la réponse de l'inexistant.
- Documentation attendue : docstrings ; doc de module `app/billing/close`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Close operation) ; `#Événements et commandes conceptuels` (`CloseSubscription`)

### BE-098 — Demande d'export des données de facturation
- Domaine : données
- Vague : 8
- Routes :
  - `POST /api/v1/billing/data-exports`
- Tables / migrations : `data_export_request` : `id`, `scope`, `requestedBy`, `status`, `requestedAt`, `fileRef`. Format et contenu : NON DÉFINI, voir QE-FAC-25.
- Droits : ACTF-04 acheteur ou ACTF-05 contact de facturation, scope payeur. Refus `FORBIDDEN`. Export exclut tout secret de paiement.
- Dépendances : BE-073, BE-079, BE-086
- Critères d'acceptation :
  - CA-1 : l'export ne contient que les objets du scope demandé (test de contenu).
  - CA-2 : l'export ne contient aucun PAN, CVV ni secret (test de contenu).
  - CA-3 : test de refus : une demande sans permission renvoie `FORBIDDEN`.
  - CA-4 : test d'isolation tenant : une demande de scope B ne retourne jamais les données du tenant A.
- Documentation attendue : docstrings ; doc de module `app/billing/exports`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Événements et commandes conceptuels` (`RequestDataExport`) ; `#Événements et commandes conceptuels` (payload minimal sans PAN/CVV)

### BE-099 — Historique commercial consultable par portée
- Domaine : consultation
- Vague : 10
- Routes :
  - `GET /api/v1/billing/history`
- Tables / migrations : lecture de `audit_event` (BE-007, alimentée par BE-073), `payment_attempt` (BE-082), `invoice` (BE-086). Aucune nouvelle table. Champs de visibilité et rétention : NON DÉFINI, voir QE-FAC-13.
- Droits : ACTF-04, ACTF-05, ACTF-09, ACTF-06/07, chacun limité à son scope ; un support ne voit que le détail nécessaire (moindre privilège, Q-06). Refus `FORBIDDEN`.
- Dépendances : BE-073, BE-082, BE-086
- Critères d'acceptation :
  - CA-1 : la liste retourne uniquement les entrées du scope de l'appelant, avec pagination.
  - CA-2 : un appelant sans permission reçoit `FORBIDDEN` (test de refus).
  - CA-3 : test d'isolation tenant : aucune entrée du tenant A n'apparaît pour le tenant B, même avec filtre forgé.
  - CA-4 : la réponse n'expose aucun secret de paiement (test de payload).
- Documentation attendue : docstrings ; doc de module `app/billing/history`.
- Source : `00-pilotage/architecture-fondation/etats-et-contrats-abonnement-facturation.md#Machine d'état conceptuelle` (Historique) ; `03-plateforme/matrice-offres-droits-quotas-entitlements.md#4. Couverture canonique des capacités` (CAP-COMMERCE-012)

## Points ouverts

- Question : Quels chemins d'API (routes) faut-il retenir pour le domaine facturation ?
  - NON DÉFINI : aucun endpoint n'est fixé par les sources. Recommandation appliquée : préfixe `/api/v1/billing/` (routeur réel : `app/main.py` monte `/api/v1` ; `app/api/v1/router.py` monte `/billing`), avec les ressources des tâches BE-076 à BE-099, à valider au contrat PH-14 avant implémentation. | QE-FAC-01

- Question : Quels codes HTTP renvoyer pour chaque code d'erreur, et quel code pour un objet hors scope ?
  - NON DÉFINI : aucun code HTTP n'est fixé. Recommandation appliquée : 401 pour non authentifié ; 403 pour `FORBIDDEN` et `SCOPE_MISMATCH` ; 404 pour tout objet hors scope (réponse identique à l'inexistant) ; 409 pour `INVALID_TRANSITION`, `VERSION_CONFLICT`, `DUPLICATE` ; 422 pour `CONSENT_REQUIRED`, `QUOTE_EXPIRED`, `*_NOT_CONFIGURED` ; 402 pour `PAYMENT_DECLINED` ; 503 pour `PROVIDER_UNAVAILABLE` ; 202 avec statut `unknown` pour `RESULT_UNKNOWN`. | QE-FAC-02

- Question : Quelles permissions nommées (PH-08) protègent chaque route ?
  - NON DÉFINI : la permission détaillée attend PH-08 et la question Q-06. Recommandation appliquée : une permission par couple (ressource, action) nommée `billing.<ressource>.<action>`, rattachée aux rôles ACTF-04 à ACTF-12 ; refus 403 tel que décrit par tâche. | QE-FAC-03

- Question : Quels noms de tables et de colonnes retenir ?
  - NON DÉFINI : aucun schéma n'est fixé. Recommandation appliquée : colonnes en camelCase, conformément au code develop, avec les noms indiqués dans chaque tâche (pluriel évité) et clés étrangères explicites ; les noms de tables sont en snake_case (QE-FAC-31) ; la liste définitive est validée par la première migration. | QE-FAC-04

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
  - NON DÉFINI : convention de casse des tables. Recommandation appliquée : tables en snake_case partout (décision du coordinateur) ; les colonnes restent en camelCase. Trois noms renommés : `auditLog` devient `audit_log` (BE-073), `paymentAttempt` devient `payment_attempt` (Code existant de BE-072), `paymentWebhookEvent` devient `payment_webhook_event` (BE-083). Les autres tables étaient déjà en snake_case. Chemins de route, fichiers et permissions non modifiés. | QE-FAC-31
