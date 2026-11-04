"""Agrégat Subscription et ses trois états indépendants (BE-079).

Contenu du paquet :
- `etats.py` : machine d'état des axes, `transition_etat` (seule porte d'écriture), et
  `charger_abonnement_du_tenant` (périmètre tenant, sans fuite d'existence) ;
- `router.py` : `GET /api/v1/billing/subscriptions/{subscriptionId}`.

La table `subscription` appartient à BE-023 ; ce paquet ne la redéfinit pas. Les colonnes
`lifecycleStatus`, `financialStatus` et `incidentStatus` sont ajoutées par la migration
e079a1b2c3d4. `status` (BE-023) reste en place pour les routes existantes.

Tableau des transitions (une ligne par état courant ; une transition hors du tableau
renvoie `INVALID_TRANSITION`) :

| Axe | État courant | Cibles permises |
|---|---|---|
| lifecycle | pending | trialing, active |
| lifecycle | trialing | active, expired |
| lifecycle | active | change_scheduled, cancel_scheduled, expired |
| lifecycle | change_scheduled | active |
| lifecycle | cancel_scheduled | active, cancelled |
| lifecycle | expired | close_pending |
| lifecycle | cancelled | close_pending |
| lifecycle | close_pending | subscription_closed |
| lifecycle | subscription_closed | (terminal) |
| financial | none | pending |
| financial | pending | settled, failed |
| financial | failed | pending |
| financial | settled | (terminal) |
| incident | none | past_due, disputed, incomplete |
| incident | past_due | grace, suspended, none |
| incident | grace | suspended, none |
| incident | suspended | none |
| incident | disputed | none |
| incident | incomplete | none |

Aucun axe ne confère de droit d'accès : les droits sont calculés par
app/billing/entitlements.py. Le périmètre de lecture est le tenant bénéficiaire.
"""
