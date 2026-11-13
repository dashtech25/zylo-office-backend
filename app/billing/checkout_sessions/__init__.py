"""Session de paiement du portail (BE-110).

Contenu du paquet :
- `service.py` : `creer_session_paiement` (idempotente, enchaîne devis, acceptation, consentement et
  checkout) et `lire_session_paiement` (lecture de l'état durable, tenant d'abord) ;
- `router.py` : `POST` et `GET` sous `/api/v1/organizations/{organization_id}/checkout-sessions`.

La session est le checkout de BE-081 ; aucune table ni migration n'est ajoutée (QE-POR-29). La
permission `billing.checkout.purchase` et la portée organisation sont vérifiées par la route avant
le corps. Documentation : `docs/portail-organisation/checkout.md`.
"""
