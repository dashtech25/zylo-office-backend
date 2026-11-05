"""Confirmation d'abonnement à partir d'un paiement confirmé (BE-084).

Contenu du paquet :
- `service.py` : `confirmer_abonnement`, qui passe l'abonnement du checkout de `pending` à
  `active` et émet `SubscriptionActivated` dans l'outbox (BE-074), dans une seule transaction.

Chaîne de liaison : tentative de paiement (`paymentAttempt`) -> checkout -> devis
(`quote.beneficiaryTenantId`, `quote.payerId`) -> abonnement `pending` du même tenant
bénéficiaire et du même payeur. Aucune colonne ne relie aujourd'hui le checkout à
l'abonnement ; cette recherche est la recommandation retenue, la liaison explicite relève
de QE-FAC-04.

Règles :
- seul un paiement `succeeded` active l'abonnement ; `unknown` renvoie `RESULT_UNKNOWN`
  (jamais un échec) et tout autre statut renvoie `INVALID_TRANSITION` ;
- le service ne reçoit aucun fournisseur de paiement et n'appelle aucune capture : une
  reprise après échec local rejoue seulement l'écriture locale (CA-2) ;
- l'identifiant d'évènement est dérivé de l'identifiant de tentative : un même paiement ne
  peut produire deux `SubscriptionActivated`.
"""
