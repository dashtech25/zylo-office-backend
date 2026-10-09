# Routes publiques et exceptions au garde d'appartenance (T-023)

Source de vérité : `tests/route_inventory.py::ROUTES_PUBLIQUES`. Le test
`tests/test_route_inventory.py` échoue si une route sans garde d'appartenance n'y figure pas, ou si une
exception ne correspond plus à une route. Chaque entrée porte sa justification et sa date (2026-10-09).

Routes sans appartenance à une organisation : santé, racine, authentification (inscription, connexion,
rafraîchissement, déconnexion, profil de l'utilisateur connecté), organisations de l'utilisateur, catalogues
`GET /modules` et `GET /billing/plans` (publics, décision IAM-020 en attente), webhooks GPS (secret d'ingestion
de l'organisation), utilitaires d'export et d'import, téléchargement par URL signée.

## Dette connue (à traiter)

- `POST /api/v1/billing/plans` : tout utilisateur connecté peut créer un plan. Retrait prévu par T-019.
- Routes de module sans garde de permission : liste figée dans `tests/route_baseline_sans_permission.txt`.
  Elle ne doit que diminuer.

## Décisions attendues

- Catalogues publics : passage authentifié (`docs/questions/securite/catalogues-publics.md`, recommandation : authentifiés).
- Utilitaires d'export et d'import : confirmer qu'ils ne touchent aucune donnée d'organisation.
