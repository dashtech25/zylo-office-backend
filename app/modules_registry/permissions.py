MODULE_MANAGE = "modules.module.manage"

# Droits de la console plateforme du catalogue de modules (BE-042, QE-MOD-16 recommandation appliquée).
# Portée plateforme, sans tenant : ils ne passent pas par `rbac.service.user_has_permission`,
# qui exige une organisation. Leur attribution est décrite dans `platform_rights.py`.
PLATFORM_MODULE_WRITE = "platform.module.write"
PLATFORM_MODULE_PUBLISH = "platform.module.publish"
