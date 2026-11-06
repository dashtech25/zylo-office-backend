"""Permissions des jobs d'import et d'export (BE-213).

Une permission par type de job (QE-API-27) : la demande, la lecture du statut et le téléchargement
exigent la permission du type du job. Un rôle qui n'a que la permission d'un autre type ne suffit pas.
"""

JOB_EXPORT_CLIENTS = "export.clients"
JOB_IMPORT_CLIENTS = "import.clients"

PERMISSION_EXPORT_CLIENTS = "jobs.export.create"
PERMISSION_IMPORT_CLIENTS = "jobs.import.create"

PERMISSION_PAR_TYPE: dict[str, str] = {
    JOB_EXPORT_CLIENTS: PERMISSION_EXPORT_CLIENTS,
    JOB_IMPORT_CLIENTS: PERMISSION_IMPORT_CLIENTS,
}
"""Permission exigée pour chaque type de job. Les codes de types sont NON DÉFINIS par la fiche
(formes retenues dans tests/test_be213_jobs_import_export.py)."""
