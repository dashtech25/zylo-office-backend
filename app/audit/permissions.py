"""Permission déclarée par le module audit — convention reprise de
app/identity/permissions.py. Reprend le code exact anticipé par
`formation/role_permission.md` §1.8 (`audit.log.view`), préfixé "audit" pour
respecter la convention <module>.<ressource>.<action> du socle."""

AUDIT_LOG_VIEW = "audit.log.view"

# BE-056 (QE-MOD-16, recommandation appliquée) : lecture du journal des transitions de modules
# d'une organisation (GET /organizations/{orgId}/module-audit). Portée organisation, accordée au
# propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py).
ORGANIZATION_AUDIT_READ = "organization.audit.read"
