"""Permissions déclarées pour le référentiel Core partagé (devises, taux de
change) — convention reprise de app/identity/permissions.py."""

CURRENCY_READ = "shared.currency.read"
CURRENCY_MANAGE = "shared.currency.manage"

EXCHANGE_RATE_READ = "shared.exchangeRate.read"
EXCHANGE_RATE_MANAGE = "shared.exchangeRate.manage"

GEO_READ = "shared.geo.read"

# T-018 : socle partagé, liste FERMÉE. Ces permissions ne sont pas propres à un
# module : un rôle de module peut les contenir sans être rejeté (voir
# rbac/module_policy.py). Ajouter une permission ici est une décision de
# socle, pas un raccourci : elle devient accordable depuis n'importe quel module.
SHARED_PERMISSION_CODES = frozenset(
    {
        CURRENCY_READ,
        CURRENCY_MANAGE,
        EXCHANGE_RATE_READ,
        EXCHANGE_RATE_MANAGE,
        GEO_READ,
    }
)
