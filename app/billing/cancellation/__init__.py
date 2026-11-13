"""Résiliation d'abonnement, à échéance ou immédiate (BE-090).

Contenu du paquet :
- `service.py` : `resilier_abonnement`, seule porte d'écriture de la résiliation ;
- `router.py` : `POST /api/v1/billing/subscriptions/{subscriptionId}/cancel`.

Règles de la résiliation :
- à échéance (`end_of_period`, mode par défaut) : l'axe lifecycle de l'abonnement passe de
  `active` à `cancel_scheduled` ; rien n'est coupé avant `endDate`, qui devient
  `cancelEffectiveAt` ;
- immédiate (`immediate`) : refusée par `INVALID_TRANSITION` tant que QE-FAC-08 n'est pas
  tranché (recommandation appliquée) ;
- le motif est exigé par l'audit de BE-073 (geste sensible `billing.subscription.terminate`) ;
- le lifecycle est lu et écrit via app/billing/subscriptions/etats.py (BE-079), la table
  `subscription` appartient à BE-023 et ses colonnes `cancelMode` / `cancelEffectiveAt` à
  la migration a090c1d2e3f4.

Décisions hors définition : aucun remboursement au prorata ; le périmètre payeur (ACTF-04)
n'est pas ouvert (QE-FAC-03) ; le code d'erreur de la résiliation immédiate refusée est
`INVALID_TRANSITION` (code non défini dans la définition).
"""
