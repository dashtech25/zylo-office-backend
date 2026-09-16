"""Codes de permission du module Files — valeurs de chaîne inchangées
depuis `app/modules/zylo_liquid/permissions.py` (2026-09-15, extraction
Phase 1) : ce sont ces chaînes exactes qui sont déjà semées dans la table
`permission` et assignées à des rôles existants — les renommer casserait
les affectations de rôles déjà en base. Seul l'emplacement du code Python
bouge, jamais la valeur."""

DOCUMENT_READ = "zyloLiquid.document.read"
DOCUMENT_CREATE = "zyloLiquid.document.create"
DOCUMENT_MANAGE = "zyloLiquid.document.manage"
DOCUMENT_DELETE = "zyloLiquid.document.delete"
DOCUMENT_READ_SENSITIVE = "zyloLiquid.document.readSensitive"
