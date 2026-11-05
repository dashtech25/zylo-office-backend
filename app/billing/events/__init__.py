"""Événements de facturation : enveloppe, émission outbox et réception inbox (BE-074).

Doc de module : ce paquet n'introduit aucune table d'outbox. L'émission écrit dans
`outbox_evenement` (BE-234, via `app.evenements.outbox`) dans la transaction de la commande
(CA-1). La seule table propre est `inbox_event`, qui consigne chaque événement reçu d'un
fournisseur (CA-2, CA-3).

Modules :
- `models` : table `inbox_event` (clé unique `provider` + `providerEventId`) ;
- `garde` : refus des données de carte (PAN, CVV) avant toute persistance (CA-4) ;
- `emission` : émission d'un événement de facturation, garde comprise ;
- `inbox` : réception idempotente et ordonnée d'un événement fournisseur.

Source : etats-et-contrats-abonnement-facturation.md, « Événements et commandes conceptuels »
et « Idempotence, concurrence, reprise ». Décisions QE-FAC-04, QE-FAC-17, QE-FAC-28 : le schéma
d'enveloppe reste celui de BE-150 (`app.evenements.enveloppe`).
"""
