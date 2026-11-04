"""Changement de plan d'abonnement : aperçu et application (BE-088).

Contenu du paquet :
- `service.py` : `apercu_changement_plan` (lecture seule) et `appliquer_changement_plan`
  (seule porte d'écriture, qui crée la demande `plan_change`) ;
- `router.py` : `POST .../plan-change/preview` et `POST .../plan-change`, montées sous
  `/api/v1/billing`.

Règles :
- un downgrade est planifié à `endDate` (fin de période) : l'abonnement garde son plan,
  sa date de fin et son axe lifecycle jusqu'à l'échéance (CA-1) ;
- un upgrade a un aperçu d'effets financiers sans prorata. Le prorata n'est pas calculé
  (QE-FAC-05), son statut `NON_DEFINI` est renvoyé ; le montant vient uniquement de la
  résolution de prix BE-078, et n'est jamais inventé (CA-2) ;
- l'application d'un upgrade est refusée en cours de période (QE-FAC-05, recommandation
  appliquée) ;
- une seule demande `scheduled` par abonnement (index unique partiel de la migration b088c0d1e2f3).

Décisions hors définition, à valider (voir POINTS-OUVERTS, QE-FAC-05 et QE-FAC-10) :
- `SCENARIO_CHANGEMENT_PLAN` est le scénario de prix utilisé pour l'aperçu ;
- `PRORATA_STATUT_NON_DEFINI` est le code provisoire signalant l'absence de prorata ;
- la permission est `billing.subscription.manage` sur le tenant bénéficiaire, comme BE-090 ;
  le périmètre payeur (ACTF-04, QE-FAC-03) n'est pas ouvert ;
- la direction est fournie par le client et contrôlée ; elle n'est pas déduite des prix.
"""
