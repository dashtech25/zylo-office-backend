"""Litiges fournisseur (dispute) : ouverture, clôture et lecture (BE-094).

Un litige est ouvert ou clos uniquement par un évènement fournisseur reçu sur
`POST /api/v1/billing/provider-events` (BE-083), traité par `app/billing/webhooks.py`
(BE-029). Il n'existe aucune route d'écriture publique sur les litiges.

Fichiers :
- `service.py` : `appliquer_evenement_litige` (effet d'un évènement, sans commit : la
  transaction appartient à BE-029) et `lire_litige` (lecture, permission et scope tenant) ;
- `router.py` : `GET /api/v1/billing/disputes/{disputeId}`.

Règles :
- `dispute.opened` crée le litige en `opened` et met `incidentStatus` de l'abonnement à
  `disputed`, seulement si la table de transitions de l'incident le permet (BE-091 ; un
  abonnement en `past_due` garde son incident, faute de transition autorisée) ;
- `dispute.resolved` avec `won`, `lost` ou `withdrawn` clôt le litige (`resolvedAt`). Un litige
  `lost` ne déclenche aucune écriture de remboursement : rembourser reste une décision humaine
  (BE-093). Quand plus aucun litige n'est ouvert sur l'abonnement, `incidentStatus` repasse de
  `disputed` à `none` ;
- un évènement visant un litige inconnu ou déjà clos est enregistré sans effet.

Pas de table propre à ce paquet au-delà de `dispute` (app/billing/models.py, migration BE-094).
Les statuts `evidence_due` et `under_review` sont acceptés par le schéma mais aucun évènement
de cette version ne les pose : ils restent ouverts pour la clôture.
Permission de lecture : `billing.dispute.read` (ACTF-09). Le rôle support ACTF-07 n'est pas
modélisé dans l'API organisation ; sa consultation relève de la console opérateur, hors de ce paquet.
"""
