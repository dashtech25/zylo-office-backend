MODULE_MANAGE = "modules.module.manage"

# Droits de la console plateforme du catalogue de modules (BE-042, QE-MOD-16 recommandation appliquée).
# Portée plateforme, sans tenant : ils ne passent pas par `rbac.service.user_has_permission`,
# qui exige une organisation. Leur attribution est décrite dans `platform_rights.py`.
PLATFORM_MODULE_WRITE = "platform.module.write"
PLATFORM_MODULE_PUBLISH = "platform.module.publish"

# Lecture des permissions déclarées par les modules de l'organisation (BE-055, QE-MOD-16 : code
# recommandé). Accordée au propriétaire à la création de l'organisation (OWNER_DEFAULT_PERMISSIONS).
ORGANIZATION_MODULE_READ = "organization.module.read"

# Installation technique d'un module pour l'organisation courante (BE-047, QE-MOD-16 : code recommandé).
# Portée organisation `{orgId}`. Accordée au propriétaire à la création (OWNER_DEFAULT_PERMISSIONS).
ORGANIZATION_MODULE_INSTALL = "organization.module.install"

# Mise à jour d'une installation de version rN vers rN+1 (BE-051, QE-MOD-16 : code recommandé).
# Portée organisation `{orgId}`. Accordée au propriétaire à la création (OWNER_DEFAULT_PERMISSIONS).
ORGANIZATION_MODULE_UPGRADE = "organization.module.upgrade"
