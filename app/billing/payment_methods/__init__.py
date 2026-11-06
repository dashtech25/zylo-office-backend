"""Moyens de paiement de l'organisation : ajout, remplacement et sélection (BE-116).

Contenu :
- `service.py` : écriture transactionnelle (`add_payment_method`, `select_payment_method`) et
  émission de `PaymentMethodChanged` dans la même transaction ;
- `schemas.py` : requête d'ajout et réponse, sans valeur de token ;
- `router.py` : routes montées sous `/api/v1/organizations/{organization_id}/billing/payment-methods`.

Règles : aucune donnée de carte (PAN, CVV) n'est acceptée ni stockée (QE-POR-13) ; une
réauthentification par mot de passe courant est exigée pour toute écriture (QE-POR-16) ;
la permission `billing.payment_method.manage` et la portée organisation sont vérifiées par la
route avant le corps.
"""
