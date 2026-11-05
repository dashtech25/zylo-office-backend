from fastapi import APIRouter

from app.alerts.router import router as alerts_router
from app.api.v1.endpoints import health
from app.auth.router import router as auth_router
from app.billing.router import current_organization_router as billing_current_organization_router
from app.billing.lecture_router import router as billing_lecture_router
from app.billing.invoices_router import router as billing_invoices_router
from app.billing.allocation_router import router as billing_allocation_router
from app.billing.consent_router import router as billing_consent_router
from app.billing.exports.router import router as billing_exports_router
from app.billing.router import router as billing_router
from app.billing.subscriptions.router import router as billing_subscriptions_router
from app.billing.cancellation.router import router as billing_cancellation_router
from app.billing.trials.router import router as billing_trials_router
from app.billing.plan_changes.router import router as billing_plan_changes_router

from app.billing.quotes.router import router as billing_quotes_router
from app.billing.checkouts.router import router as billing_checkouts_router
from app.files.router import router as files_router
from app.identity.router import router as organizations_router
from app.identity.router import account_router
from app.identity.router import users_router
from app.location.router import router as location_router
from app.modules.zylo_liquid.router import router as zylo_liquid_router
from app.modules.zylo_tanker.router import router as zylo_tanker_router
from app.modules_registry.audit_router import router as module_audit_router
from app.modules_registry.router import organizations_modules_router
from app.modules_registry.admin_router import router as modules_admin_router
from app.modules_registry.reconciliation_router import router as reconciliation_admin_router
from app.modules_registry.catalog_router import router as catalog_router
from app.modules_registry.router import router as modules_router
from app.rbac.grants_membres import router as grants_membres_router
from app.rbac.module_router import router as rbac_module_router
from app.notifications.router import router as notifications_router
from app.rbac.router import router as rbac_router
from app.rbac.roles_lecture import router as roles_lecture_router
from app.audit.router import organization_audit_router
from app.audit.router import router as audit_router
from app.shared.currency_router import currency_router, exchange_rate_router
from app.shared.export_router import export_router
from app.shared.geo_router import country_router, geo_router
from app.shared.import_router import import_router
from app.shared.storage_router import storage_router
from app.operator.router import router as operator_router
from app.operator.health import admin_router as operator_admin_router
from app.operator.health import internal_router as internal_health_router
from app.operator.admin_audit_router import router as admin_audit_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(organizations_router, prefix="/organizations", tags=["organizations"])
api_router.include_router(billing_current_organization_router, prefix="/organizations", tags=["billing"])
api_router.include_router(users_router, prefix="/users", tags=["users"])
api_router.include_router(account_router, prefix="/account", tags=["account"])
api_router.include_router(organizations_modules_router, prefix="/organizations", tags=["modules"])
api_router.include_router(modules_router, prefix="/modules", tags=["modules"])
api_router.include_router(modules_admin_router, prefix="/admin", tags=["admin-modules"])
api_router.include_router(reconciliation_admin_router, prefix="/admin", tags=["admin-reconciliation"])
# BE-043 : catalogue public (publié + visible), sans authentification.
api_router.include_router(catalog_router, prefix="/catalog", tags=["catalog"])
api_router.include_router(module_audit_router, prefix="/organizations", tags=["modules"])
api_router.include_router(rbac_router, prefix="/rbac", tags=["rbac"])
# BE-016 : lecture des rôles de l organisation courante (lecture seule).
api_router.include_router(roles_lecture_router, prefix="/organizations", tags=["rbac"])
api_router.include_router(grants_membres_router, prefix="/organizations", tags=["rbac"])
api_router.include_router(rbac_module_router, prefix="/rbac", tags=["rbac"])
api_router.include_router(audit_router, prefix="/audit", tags=["audit"])
api_router.include_router(organization_audit_router, prefix="/organizations", tags=["audit"])
api_router.include_router(notifications_router, prefix="/notifications", tags=["notifications"])
api_router.include_router(billing_router, prefix="/billing", tags=["billing"])
api_router.include_router(billing_invoices_router, prefix="/billing", tags=["billing"])
# BE-079 : agrégat abonnement (GET /billing/subscriptions/{subscriptionId}).
api_router.include_router(billing_subscriptions_router, prefix="/billing", tags=["billing"])
# BE-090 : résiliation d'abonnement (POST /billing/subscriptions/{subscriptionId}/cancel).
api_router.include_router(billing_cancellation_router, prefix="/billing", tags=["billing"])
# BE-080 : démarrage d'essai (POST /billing/subscriptions/trials).
api_router.include_router(billing_trials_router, prefix="/billing", tags=["billing"])
# BE-088 : aperçu et application d'un changement de plan (POST /billing/subscriptions/{subscriptionId}/plan-change[/preview]).
api_router.include_router(billing_plan_changes_router, prefix="/billing", tags=["billing"])

# BE-077 : devis (POST /billing/quotes, GET /billing/quotes/{quoteId}, POST .../accept).
api_router.include_router(billing_quotes_router, prefix="/billing", tags=["billing"])
api_router.include_router(billing_checkouts_router, prefix="/billing", tags=["billing"])
api_router.include_router(billing_lecture_router, prefix="/organizations", tags=["billing"])
# BE-046 : attribution et révocation des sièges d'entitlement (sous /organizations/{id}/entitlements).
api_router.include_router(billing_allocation_router, prefix="/organizations", tags=["billing"])
# BE-076 : consentements versionnés (POST /billing/consents).
api_router.include_router(billing_consent_router, prefix="/billing", tags=["billing"])
# BE-098 : export des données de facturation (POST /billing/data-exports).
api_router.include_router(billing_exports_router, prefix="/billing", tags=["billing"])
api_router.include_router(operator_router, prefix="/admin", tags=["operator"])
api_router.include_router(operator_admin_router, prefix="/admin", tags=["operator"])
# BE-122 : journal d'audit administratif, lecture seule (GET /admin/audit-events).
api_router.include_router(admin_audit_router, prefix="/admin", tags=["admin-audit"])
api_router.include_router(internal_health_router, tags=["health"])
api_router.include_router(zylo_liquid_router, prefix="/zylo-liquid", tags=["zylo-liquid"])
api_router.include_router(files_router, prefix="/zylo-liquid", tags=["files"])
api_router.include_router(location_router, prefix="/zylo-liquid", tags=["location"])
api_router.include_router(alerts_router, prefix="/zylo-liquid", tags=["alerts"])
# Généralisation Zylo Tanker (2026-09-16) — même routeur Python que
# location_router ci-dessus, monté une deuxième fois sous un préfixe
# différent (exactement comme Files/Location/Alertes le sont déjà
# plusieurs fois sous /zylo-liquid) : app/location/router.py sert
# maintenant le tracking GPS des camions ET des navires, chaque route y
# porte sa propre garde require_module_active (voir sa docstring).
#
# ORDRE IMPORTANT : monté AVANT zylo_tanker_router. Starlette résout les
# routes dans leur ordre d'enregistrement, jamais par spécificité — sans
# cet ordre, `GET /zylo-tanker/vessels/{vessel_id}` (CRUD Vessel,
# zylo_tanker_router) intercepterait `GET /zylo-tanker/vessels/current-positions`
# (location_router) en essayant de parser "current-positions" comme un
# UUID, provoquant une 422 (bug constaté en testant ce chantier — la
# routes GET /trucks/{truck_id} n'existe pas côté zylo_liquid_router,
# seul PATCH, donc cette collision précise n'existait pas encore avant
# Zylo Tanker).
api_router.include_router(location_router, prefix="/zylo-tanker", tags=["zylo-tanker", "location"])
api_router.include_router(zylo_tanker_router, prefix="/zylo-tanker", tags=["zylo-tanker"])
api_router.include_router(currency_router, prefix="/currencies", tags=["currencies"])
api_router.include_router(exchange_rate_router, prefix="/exchange-rates", tags=["exchange-rates"])
api_router.include_router(geo_router, prefix="/cities", tags=["geo"])
api_router.include_router(country_router, prefix="/countries", tags=["geo"])
api_router.include_router(export_router, prefix="/export", tags=["export"])
api_router.include_router(import_router, prefix="/import", tags=["import"])
api_router.include_router(storage_router, prefix="/storage", tags=["storage"])
