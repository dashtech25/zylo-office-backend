PLAN_MANAGE = "billing.plan.manage"
SUBSCRIPTION_MANAGE = "billing.subscription.manage"
# BE-026 (recommandation QE-SOC-06) : lecture de l'abonnement, des droits et des
# entitlements de l'organisation courante. Accordée au propriétaire à la création
# de l'organisation (app/identity/service.py::OWNER_DEFAULT_PERMISSIONS).
SUBSCRIPTION_READ = "billing.subscription.read"
ENTITLEMENT_MANAGE = "entitlement.manage"
