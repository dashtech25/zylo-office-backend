"""Clôture d'abonnement (BE-097).

Contenu du paquet :
- `service.py` : `demander_cloture`, seule porte d'écriture de la clôture ;
- `router.py` : `POST /api/v1/billing/subscriptions/{subscriptionId}/close`.

Règles :
- la clôture part de `cancelled` ou `expired` (lifecycle `close_pending`, puis
  `subscription_closed`) ; tout autre état renvoie `INVALID_TRANSITION` ;
- `subscription_closed` n'est écrit qu'après vérification de chaque prérequis requis :
  finance (état financier non en attente et aucun paiement `unknown`), droits (dernière
  synchronisation PH-09 `applied`), données (aucune demande d'export non produite) ;
- un prérequis manquant laisse la clôture en `close_pending_finance`,
  `close_pending_entitlement` ou `close_pending_data` (le premier manquant, dans cet ordre) ;
- un cas support ouvert ne bloque jamais la clôture (aucun cas de facturation n'est lu).
"""
