"""Avoir et correction d'une facture finalisée (BE-087).

Contenu du paquet :
- `service.py` : `emettre_avoir`, seule porte d'écriture d'un avoir. Elle vérifie, dans
  l'ordre, le motif (CA-2), le périmètre de la facture (CA-4), l'approbation distincte
  (CA-3), puis le statut `finalized` (CA-1) ;
- la route `POST /api/v1/billing/invoices/{invoiceId}/credit-notes` est déclarée dans
  app/billing/invoices_router.py, avec les autres routes de facture.

Principe : un avoir corrige une facture sans la modifier. La facture d'origine reste
`finalized`, append-only (BE-086) ; l'avoir est une ligne séparée rattachée à elle.
Règle d'approbation : QE-FAC-09, recommandation appliquée (toute action financière
irréversible exige une approbation enregistrée, seuil implicite à zéro).
"""
