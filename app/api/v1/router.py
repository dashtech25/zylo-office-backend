from fastapi import APIRouter

from app.api.v1.endpoints import health
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.files.router import router as files_router
from app.identity.router import router as organizations_router
from app.location.router import router as location_router
from app.modules.zylo_liquid.router import router as zylo_liquid_router
from app.modules_registry.router import router as modules_router
from app.rbac.router import router as rbac_router
from app.audit.router import router as audit_router
from app.shared.currency_router import currency_router, exchange_rate_router
from app.shared.geo_router import geo_router
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
api_router.include_router(currency_router, prefix="/currencies", tags=["currencies"])
api_router.include_router(exchange_rate_router, prefix="/exchange-rates", tags=["exchange-rates"])
api_router.include_router(geo_router, prefix="/cities", tags=["geo"])
api_router.include_router(storage_router, prefix="/storage", tags=["storage"])
