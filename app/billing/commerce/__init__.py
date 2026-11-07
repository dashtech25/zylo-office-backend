"""Devis, checkout et consentement d'essai (BE-202), routes à la racine de `/api/v1`.

Contenu du paquet :
- `service.py` : `creer_devis`, `ouvrir_checkout`, `enregistrer_consentement`, seules portes
  d'écriture de ce lot ; elles s'appuient sur le socle d'idempotence (BE-072) ;
- `router.py` : `POST /api/v1/quotes`, `POST /api/v1/checkouts`, `POST /api/v1/consents`.

Les routes BE-077 (`/api/v1/billing/quotes`) et BE-081 (`/api/v1/billing/checkouts`) restent
en place ; ce paquet ne les remplace pas (voir le rapport BE-202).
"""
