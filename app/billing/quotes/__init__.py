"""Devis (Quote) : création, lecture et acceptation (BE-077).

Contenu du paquet :
- `service.py` : `creer_devis`, `lire_devis`, `accepter_devis`, seules portes
  d'écriture et de lecture des devis ;
- `router.py` : `POST /api/v1/billing/quotes`, `GET /api/v1/billing/quotes/{quoteId}`,
  `POST /api/v1/billing/quotes/{quoteId}/accept`.
"""
