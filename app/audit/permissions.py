"""Permission déclarée par le module audit — convention reprise de
app/identity/permissions.py. Reprend le code exact anticipé par
`formation/role_permission.md` §1.8 (`audit.log.view`), préfixé "audit" pour
respecter la convention <module>.<ressource>.<action> du socle."""

AUDIT_LOG_VIEW = "audit.log.view"

# BE-056 (QE-MOD-16, recommandation appliquée) : lecture du journal des transitions de modules
# d'une organisation (GET /organizations/{orgId}/module-audit). Portée organisation, accordée au
# propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py).
ORGANIZATION_AUDIT_READ = "organization.audit.read"

# BE-172 (QE-PAR-16, hypothèse) : un événement dont `visibility` vaut VISIBILITE_RESTREINTE
# n'est lu en détail, et n'apparaît en recherche, qu'avec AUDIT_RESTRICTED_VIEW.
# Valeur de visibilité et permission NON DÉFINIES dans la source ; à confirmer.
VISIBILITE_RESTREINTE = "restreinte"
AUDIT_RESTRICTED_VIEW = "audit.restricted.view"

# BE-173 (EVT-AUD-02) : demander un export du journal d'audit et lire son statut ou son
# contenu. Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py).
AUDIT_EXPORT = "audit.export"
