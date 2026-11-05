"""Permissions du registre et des routes des connecteurs (BE-164, BE-162).

Déclarées ici et enregistrées en base par `app/integrations/seed.py` : sans cette
déclaration, `require_permission` refuse, y compris au propriétaire.

- `integrations.read` : lecture du journal des tentatives (BE-164) et de la liste des
  connecteurs (BE-162) ;
- `integrations.manage` : création, transitions et reprise de configuration (BE-162).
"""

INTEGRATIONS_READ = "integrations.read"
INTEGRATIONS_MANAGE = "integrations.manage"
