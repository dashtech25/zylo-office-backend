"""Permissions déclarées par le module rbac lui-même — gérer les rôles et les
grants est une capacité du socle, pas d'un module métier (convention reprise
de app/identity/permissions.py)."""

ROLE_MANAGE = "rbac.role.manage"
GRANT_MANAGE = "rbac.grant.manage"
