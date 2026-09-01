from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware
from app.modules.zylo_liquid.seed import seed_known_permissions
from app.modules_registry.seed import seed_known_modules

setup_logging()

TAGS_METADATA = [
    {"name": "health", "description": "Vérification de disponibilité du service."},
    {"name": "auth", "description": "Authentification globale : register, login, refresh, logout, session courante."},
    {"name": "organizations", "description": "Organisations (tenants) et leurs membres — modèle Organization → User → Role → Permission."},
    {"name": "modules", "description": "Registre des modules et activation par organisation (ex: zylo_liquid)."},
    {"name": "billing", "description": "Plans, abonnements et facturation par module (aucun prestataire de paiement réel intégré)."},
]

app = FastAPI(title=settings.APP_NAME, openapi_tags=TAGS_METADATA)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")


@app.on_event("startup")
async def on_startup() -> None:
    await seed_known_modules()
    await seed_known_permissions()


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.APP_NAME, "status": "running"}
