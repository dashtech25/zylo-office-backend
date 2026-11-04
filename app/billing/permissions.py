"""Codes de permission de la facturation.

Chaque code suit le format `domaine.entite.action` et est accordé au rôle
propriétaire à la création d'une organisation (`OWNER_DEFAULT_PERMISSIONS`,
app/identity/service.py). `BILLING_INVOICE_READ` est une recommandation
(QE-SOC-06) : le code de lecture de la facturation n'était pas défini dans la
définition ; il est retenu ici pour les routes de lecture de BE-027.
"""

PLAN_MANAGE = "billing.plan.manage"
SUBSCRIPTION_MANAGE = "billing.subscription.manage"
# BE-026 (recommandation QE-SOC-06) : lecture de l'abonnement, des droits et des
# entitlements de l'organisation courante. Accordée au propriétaire à la création
# de l'organisation (app/identity/service.py::OWNER_DEFAULT_PERMISSIONS).
SUBSCRIPTION_READ = "billing.subscription.read"
ENTITLEMENT_MANAGE = "entitlement.manage"
# Lecture des factures de l'organisation courante (BE-027, routes /organizations/current/invoices).
BILLING_INVOICE_READ = "billing.invoice.read"
# BE-045 (QE-MOD-16, recommandation appliquée) : lecture des entitlements d'une organisation
# désignée par son identifiant dans le chemin (GET /organizations/{organization_id}/entitlements).
# Portée organisation ; accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS.
ORGANIZATION_ENTITLEMENT_READ = "organization.entitlement.read"
# BE-046 (QE-MOD-16, recommandation appliquée) : attribuer un siège (allocation) d'un
# entitlement à un membre, et révoquer ce siège. Deux permissions distinctes : un acteur
# peut attribuer sans pouvoir révoquer, et inversement. Portée organisation.
ORGANIZATION_ENTITLEMENT_ALLOCATE = "organization.entitlement.allocate"
ORGANIZATION_ENTITLEMENT_REVOKE = "organization.entitlement.revoke"
# BE-075 : lecture interne du catalogue figé (snapshotJson). Aucune permission client
# directe sur le catalogue : ce code n'est accordé à aucun rôle par défaut.
BILLING_CATALOGUE_READ = "billing.catalogue.read"
