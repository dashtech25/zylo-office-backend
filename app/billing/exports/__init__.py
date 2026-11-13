"""Export des données de facturation (BE-098).

Module de documentation et de regroupement : le contrat tient en trois fichiers.

- `app/billing/exports/service.py` : la règle (permission, périmètre, contenu, audit) ;
- `app/billing/exports/router.py` : la route `POST /api/v1/billing/data-exports` ;
- `app/billing/models.py::DataExportRequest` : la table `data_export_request`
  (migration b098e0f1a2c3).

Contenu de l'export (format retenu, QE-FAC-25) : un objet JSON structuré, lisible, qui ne
contient que les abonnements et les factures du compte demandé, dans le tenant courant.
Aucune tentative de paiement, aucun PAN, aucun CVV, aucune URL de paiement ni référence
fournisseur n'y figure : ces champs ne sont pas dans la liste blanche de `service.py`.
"""
