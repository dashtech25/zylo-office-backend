"""Capacité partagée Notifications.

Boîte de réception (BE-035) : `GET /api/v1/notifications/inbox` liste les éléments
adressés au compte courant dans l'organisation active ; `PATCH
/api/v1/notifications/inbox/{itemId}` les marque lus (idempotent). Aucun élément
n'est créé par une route HTTP : seul `service.create_inbox_item` écrit, et aucun
producteur métier n'est raccordé tant que le catalogue d'événements (PH-13) et la
frontière Notifications/Alertes (ARC-007) ne sont pas validés. La liste vide est
donc l'état attendu. Détail du contrat : `docs/architecture/notifications/inbox-api.md`.
"""
