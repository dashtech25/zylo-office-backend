"""Exports de données asynchrones du portail organisation (BE-117).

Fichiers : `models.py` (table `export_job`), `service.py` (demande, traitement de fond, expiration,
téléchargement), `router.py` (routes sous `/api/v1/organizations/{organization_id}/exports`),
`schemas.py`, `permissions.py` et `seed.py` (permission `data.export`).
Documentation de module : docs/portail-organisation/exports.md.
"""
