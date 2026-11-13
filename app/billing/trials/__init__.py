"""Démarrage d'essai d'un abonnement (BE-080).

Contenu du paquet :
- `service.py` : `demarrer_essai`, seule porte d'écriture du passage `pending -> trialing` ;
- `router.py` : `POST /api/v1/billing/subscriptions/trials`.

Ce paquet réutilise sans les redéfinir :
- la table `TRANSITIONS_CYCLE_DE_VIE` et `charger_abonnement_du_tenant` (BE-079) ;
- `enregistrer_consentement` (BE-076) pour un consentement fourni dans la requête ;
- `publier_enveloppe` (BE-150) pour l'événement `TrialStarted`.

Aucune table nouvelle, aucune migration : l'essai est porté par `lifecycleStatus`, `startDate`
et `endDate` de `subscription`. Aucun droit d'accès n'est alloué ici (CA-5) ; l'allocation
dans le socle relève de BE-085.
"""
