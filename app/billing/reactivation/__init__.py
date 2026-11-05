"""Réactivation d'abonnement après incident ou résiliation (BE-092).

Contenu du paquet :
- `service.py` : `reactiver_abonnement`, seule porte d'écriture de la réactivation. Elle remet le
  cycle de vie à `active` (depuis `cancel_scheduled`, `cancelled` ou `expired`) et l'incident à
  `none` (depuis `past_due`, `grace` ou `suspended`), seulement sur présentation d'une tentative de
  paiement `succeeded` rattachée à une facture de l'abonnement ;
- `router.py` : `POST /api/v1/billing/subscriptions/{subscriptionId}/reactivate`.

Règles :
- un abonnement clos (`close_pending`, `subscription_closed`) ou en litige (`disputed`) ou
  incomplet (`incomplete`) n'est pas réactivable : `INVALID_TRANSITION` ;
- un paiement non confirmé est refusé : `PAYMENT_DECLINED`, ou `RECONCILIATION_REQUIRED` si l'issue
  est `unknown` (jamais assimilée à un échec) ;
- un seul `SubscriptionActivated` est écrit dans l'outbox (BE-074), dans la même transaction.

Décisions hors définition : la permission est `billing.subscription.manage`, comme pour la
résiliation (QE-FAC-03 non tranché) ; la transition `cancelled`/`expired` -> `active` est locale à
ce paquet et n'altère pas la table de BE-079 ; aucune synchronisation des droits n'est lancée.
"""
