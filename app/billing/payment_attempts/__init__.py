"""Tentatives de paiement d'un checkout (BE-082).

Module `app/billing/payment_attempts` : crée une tentative `created`, l'enregistre `submitted`
puis appelle l'adaptateur fournisseur (`app/billing/payment_provider.py`, BE-028). Le modèle est
la table `paymentAttempt` (app/billing/models.py), partagée avec les tentatives de facture.

Fichiers :
- `service.py` : décisions et transitions (seule porte d'écriture) ;
- `router.py` : route `POST /billing/checkouts/{checkoutId}/payment-attempts` et sélection
  de l'adaptateur (`obtenir_fournisseur`, remplaçable par `app.dependency_overrides` en test).

Aucune donnée de carte n'est acceptée ni stockée : le corps de la requête est ignoré.
"""
