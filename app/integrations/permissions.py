"""Permission de lecture du journal des tentatives d'intégration (BE-164).

Déclarée ici et enregistrée en base par `app/integrations/seed.py` : sans cette
déclaration, `require_permission` refuse, y compris au propriétaire.
"""

INTEGRATIONS_READ = "integrations.read"

INTEGRATIONS_MANAGE = "integrations.manage"
