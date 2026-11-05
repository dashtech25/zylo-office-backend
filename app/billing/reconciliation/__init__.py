"""Réconciliation des paiements et résultats incertains (BE-095).

Module `app/billing/reconciliation` : constate les tentatives de paiement `unknown` qui ont un débit
confirmé chez le fournisseur, sans jamais en initier de nouvelle et sans les corriger.

Fichiers :
- `service.py` : `lancer_reconciliation`, seule porte d'écriture (run, écarts, évènement, audit) ;
- `router.py` : route `POST /billing/reconciliations` et sélection de l'adaptateur
  (`obtenir_fournisseur_reconciliation`, remplaçable par `app.dependency_overrides` en test).

Tables : `reconciliation_run` et `reconciliation_difference` (migration c095a1b2d3e4).
Écart saisi dans l'outbox : `Billing.ReconciliationDifferenceDetected`.
"""
