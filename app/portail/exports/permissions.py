"""Permission de l'export de données du portail (BE-117).

`data.export` (format `domaine.action`, voir CLAUDE.md : la fiche écrit `data:export`) couvre la
demande, la lecture du statut et le téléchargement d'un export de l'organisation courante.
Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py), ou à un rôle
qui la reçoit explicitement. Sans cette ligne en base, `require_permission` refuse, y compris
au propriétaire.
"""

DATA_EXPORT = "data.export"
