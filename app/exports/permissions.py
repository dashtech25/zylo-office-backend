"""Permission de l'export de données (BE-243).

Le nom n'est pas fixé par la définition (NON DÉFINI) : `donnees.export.creer` est retenu
provisoirement. Elle couvre la demande, la lecture du statut et le téléchargement d'un export.
Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py).
"""

DONNEES_EXPORT_CREER = "donnees.export.creer"
