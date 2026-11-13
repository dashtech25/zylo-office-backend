"""Échec de paiement, grâce et suspension : l'axe `incidentStatus` (BE-091).

Doc de module : `app/billing/incidents`.

Contenu du paquet :
- `service.py` : `appliquer_echec_paiement` (échec `failed` d'une tentative -> `past_due`, avec
  événement `Billing.PaymentAttemptFailed`) et `suspendre_manuellement` (transition `suspended`
  déclenchée par une personne habilitée).

Règles tenues par ce paquet :
- un échec ne touche jamais `lifecycleStatus` ni `financialStatus` ; seul `incidentStatus` change ;
- aucune suspension automatique : ni durée de grâce, ni job, ne suspend l'abonnement tant que
  la durée de grâce et la politique d'accès ne sont pas décidées (QE-FAC-07). Aucun appel à la
  synchronisation des droits (BE-085) n'est fait ici : un incident de paiement ne retire aucun droit ;
- la lecture et l'écriture restent dans le périmètre du tenant bénéficiaire (isolation tenant).

Les transitions de l'axe incident sont celles de `app/billing/subscriptions/etats.py` (BE-079).
Aucune route HTTP n'est ajoutée par BE-091 : les transitions sont déclenchées par BE-082, BE-083
et BE-089 (succès ou échec d'une tentative), et par la suspension manuelle du service.
"""
