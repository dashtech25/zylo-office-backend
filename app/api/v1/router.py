from fastapi import APIRouter

from app.api.v1.endpoints import health
from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.identity.router import router as organizations_router
from app.modules_registry.router import router as modules_router

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
api_router.include_router(organizations_router, prefix="/organizations", tags=["organizations"])
api_router.include_router(modules_router, prefix="/modules", tags=["modules"])
api_router.include_router(billing_router, prefix="/billing", tags=["billing"])
