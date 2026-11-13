"""Permission déclarée par le module Notifications (BE-171).

Convention `domaine.entite.action`, reprise de `app/audit/permissions.py`. Elle donne
accès aux livraisons des notifications (`GET /api/v1/notifications/{id}/livraisons`)
pour toute notification de l'organisation active ; sans elle, seule la notification
du compte courant est visible, et ses livraisons renvoient `403`.

Attribution : QE-PAR-03 (NON DÉFINI dans la source) ; aucun rôle ne la porte par défaut.
"""

NOTIFICATIONS_READ = "notifications.read"
