from fastapi import APIRouter

from app.alerts.router import router as alerts_router
from app.api.v1.endpoints import health
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.files.router import router as files_router
from app.identity.router import router as organizations_router
from app.location.router import router as location_router
from app.modules.zylo_liquid.router import router as zylo_liquid_router
from app.modules.zylo_tanker.router import router as zylo_tanker_router
from app.modules_registry.router import router as modules_router
from app.rbac.router import router as rbac_router
from app.audit.router import router as audit_router
from app.shared.currency_router import currency_router, exchange_rate_router
from app.shared.export_router import export_router
from app.shared.geo_router import country_router, geo_router
from app.shared.storage_router import storage_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(organizations_router, prefix="/organizations", tags=["organizations"])
api_router.include_router(modules_router, prefix="/modules", tags=["modules"])
api_router.include_router(rbac_router, prefix="/rbac", tags=["rbac"])
api_router.include_router(audit_router, prefix="/audit", tags=["audit"])
api_router.include_router(billing_router, prefix="/billing", tags=["billing"])
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
api_router.include_router(storage_router, prefix="/storage", tags=["storage"])
