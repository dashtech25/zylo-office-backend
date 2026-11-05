"""Remboursement d'un paiement réussi, avec approbation humaine (BE-093).

Contenu du paquet :
- `service.py` : `demander_remboursement`, seule porte d'écriture d'un remboursement. Elle vérifie
  la permission, le périmètre du paiement, l'approbation distincte, le statut du paiement et le
  reliquat, écrit l'approbation AVANT tout appel fournisseur, puis relit l'issue de l'envoi ;
- `router.py` : la route `POST /api/v1/billing/payments/{paymentId}/refunds`, qui relaie le service.

Principe : aucun remboursement n'est envoyé au prestataire sans une ligne `refund` déjà validée
(statut `pending`, approbateur renseigné) et une entrée d'audit `billing.refund.approve`. La clé de
requête (en-tête `Idempotency-Key`) est rejouée via le registre d'idempotence (BE-072), et stockée
dans `refund.request_id` avec le paiement : un second envoi fournisseur est impossible.

Règles d'approbation et de seuil : QE-FAC-02 et QE-FAC-09 (recommandations appliquées). Le seuil est
implicite à zéro : toute demande exige un approbateur humain ; le plafond est le montant du paiement
moins les remboursements non échoués.
"""
