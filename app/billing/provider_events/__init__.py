"""Ingestion des évènements fournisseur de paiement (BE-083).

Ce paquet ne contient pas de code métier. Il décrit la frontière d'entrée des
évènements fournisseur, dont le traitement est réparti ainsi :

- Route : `POST /api/v1/billing/provider-events`, déclarée dans `app/billing/router.py`
  (fonction `flutterwave_webhook`). Elle vérifie la signature fournisseur (en-tête
  `verif-hash`, comparé au secret `FLUTTERWAVE_WEBHOOK_SECRET`, ACTF-11) puis délègue.
- Signature refusée : 401 `webhook_signature_invalid`, rien n'est lu ni persisté.
- Signature valide : le corps brut est transmis à `app/billing/webhooks.py`
  (`traiter_evenement_webhook`, BE-029), qui porte l'idempotence (table
  `paymentWebhookEvent`), la déduplication, la quarantaine et l'effet métier.

Aucune table propre à ce paquet. Hors périmètre de BE-083 : la rotation des secrets
(QE-FAC-12, non définie) et les règles de paiement (BE-024, BE-027).
"""
