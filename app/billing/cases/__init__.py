"""Cas de facturation et d'assistance (BE-096).

Contenu du paquet :
- `service.py` : `ouvrir_cas` et `resoudre_cas`, seules portes d'écriture de `billing_case` ;
- `router.py` : `POST /api/v1/billing/cases` et `POST /api/v1/billing/cases/{case_id}/resolve`.

Règles :
- un cas ne bloque ni ne déclenche la clôture d'abonnement (BE-097) : la clôture ne lit aucun cas ;
- la résolution exige un motif non vide et écrit une entrée d'audit dans la même transaction (CA-2) ;
- les permissions `billing.case.open` et `billing.case.resolve` sont distinctes ; sans elles, `FORBIDDEN` ;
- un cas est visible uniquement dans le tenant qui l'a ouvert ; un autre tenant reçoit `case_not_found`.
"""
