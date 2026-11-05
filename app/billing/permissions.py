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
# BE-076 (QE-FAC-03, recommandation appliquée) : enregistrer un consentement versionné pour un
# compte payeur. Porte les rôles ACTF-04 (acheteur) et ACTF-05 (contact de facturation) ; accordée
# au propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py). Sans elle : 403 FORBIDDEN.
BILLING_CONSENT_RECORD = "billing.consent.record"
# BE-086 (ACTF-09, finance) : finaliser une facture brouillon. Code absent de la définition
# (QE-SOC-06 : recommandation appliquée, nom aligné sur le geste d'audit `billing.invoice.finalize`).
# Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS. Sans elle : 403 FORBIDDEN.
BILLING_INVOICE_FINALIZE = "billing.invoice.finalize"
# BE-098 (QE-FAC-03, recommandation appliquée) : demander un export des données de facturation
# d'un compte payeur. Porte les rôles ACTF-04 (acheteur) et ACTF-05 (contact de facturation) ;
# accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS (app/identity/service.py). Sans elle : 403 FORBIDDEN.
BILLING_DATA_EXPORT_REQUEST = "billing.data_export.request"
# BE-099 (QE-FAC-03, recommandation appliquée) : consulter l'historique commercial du tenant
# courant (GET /api/v1/billing/history), lu dans `audit_event`. Accordée au propriétaire via
# OWNER_DEFAULT_PERMISSIONS. Sans elle : 403 FORBIDDEN.
BILLING_HISTORY_READ = "billing.history.read"
# BE-093 (ACTF-09, finance) : demander un remboursement. L'approbation (ACTF-08) n'est pas une
# permission ici : elle est contrôlée par la règle d'approbation (app/billing/refunds/service.py).
# Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS. Sans elle : 403 FORBIDDEN.
BILLING_REFUND_REQUEST = "billing.refund.request"

# BE-094 (ACTF-09, finance ; ACTF-07 support non modélisé ici, voir disputes/__init__.py) : lire un litige
# fournisseur de l'organisation courante (GET /api/v1/billing/disputes/{disputeId}). Accordée au propriétaire
# via OWNER_DEFAULT_PERMISSIONS. Sans elle : 403 FORBIDDEN.
BILLING_DISPUTE_READ = "billing.dispute.read"
# BE-095 (ACTF-09, finance) : lancer une réconciliation des paiements (POST /billing/reconciliations).
# Accordée au propriétaire via OWNER_DEFAULT_PERMISSIONS. Sans elle : 403 FORBIDDEN.
BILLING_RECONCILIATION_RUN = "billing.reconciliation.run"
