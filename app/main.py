import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware, TimingMiddleware
from app.audit.seed import seed_known_permissions as seed_audit_permissions
from app.core.database import AsyncSessionLocal
from app.identity.service import backfill_owner_default_permissions
from app.modules.zylo_liquid.seed import seed_known_permissions
from app.modules.zylo_liquid.telemetry_sync import structural_sweep_loop, sync_loop as holykell_sync_loop
from app.modules_registry.seed import seed_known_modules
from app.modules_registry.service import backfill_active_module_permissions_for_owners
from app.rbac.seed import seed_known_permissions as seed_rbac_permissions

setup_logging()

TAGS_METADATA = [
    {"name": "health", "description": "Vérification de disponibilité du service."},
    {"name": "auth", "description": "Authentification globale : register, login, refresh, logout, session courante."},
    {"name": "organizations", "description": "Organisations (tenants) et leurs membres — modèle Organization → User → Role → Permission."},
    {"name": "modules", "description": "Registre des modules et activation par organisation (ex: zylo_liquid)."},
    {"name": "rbac", "description": "Rôles, permissions et grants individuels (allow/deny, scopés, délégables)."},
    {"name": "audit", "description": "Journal d'audit — qui a fait quoi, sur quel élément, quand, filtré par portée."},
    {"name": "billing", "description": "Plans, abonnements et facturation par module (aucun prestataire de paiement réel intégré)."},
    {"name": "currencies", "description": "Référentiel des devises — Core, sans isolation tenant, réutilisable par tout module."},
    {"name": "exchange-rates", "description": "Taux de change historisés — Core, toujours une insertion, jamais une correction."},
]

app = FastAPI(title=settings.APP_NAME, openapi_tags=TAGS_METADATA)

# Ordre important : TimingMiddleware doit être ajouté avant RequestIdMiddleware
# pour s'exécuter à l'intérieur de celui-ci (Starlette empile les middlewares
# dans l'ordre inverse de add_middleware — le dernier ajouté est le plus
# externe). Ainsi request_id_ctx est déjà positionné par RequestIdMiddleware
# quand TimingMiddleware journalise sa ligne "request_timing", et n'est
# réinitialisé qu'après (dans le finally de RequestIdMiddleware, exécuté en
# dernier).
app.add_middleware(TimingMiddleware)
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
    await seed_rbac_permissions()
    await seed_audit_permissions()
    await seed_known_permissions()
    # Répare les organisations créées avant l'ajout d'une entrée à
    # OWNER_DEFAULT_PERMISSIONS (ex. ROLE_MANAGE/GRANT_MANAGE/AUDIT_LOG_VIEW) —
    # idempotent, sans effet une fois toutes les organisations à jour.
    async with AsyncSessionLocal() as db:
        await backfill_owner_default_permissions(db)
    # Même principe, côté permissions de module : répare les organisations
    # dont un module était déjà actif avant l'ajout de nouvelles permissions
    # à ce module (ex. couche déclarative/commerciale/rapprochement ajoutée
    # à zylo_liquid après coup, processus-double-sources-verite Phase 8) —
    # sans quoi un owner déjà actif ne reçoit jamais les permissions
    # ajoutées après son activation initiale du module.
    async with AsyncSessionLocal() as db:
        await backfill_active_module_permissions_for_owners(db)

    # Refonte alertes Étape 2 (décision D1) : la boucle de sondage Holykell
    # tourne dans ce process, plus jamais dépendante d'un script externe.
    # Vide par défaut (HOLYKELL_SYNC_BASE_URL non défini) = désactivée, sans
    # effet sur le dev local qui n'a pas de simulateur Holykell en ligne.
    if settings.HOLYKELL_SYNC_BASE_URL:
        app.state.holykell_sync_task = asyncio.create_task(holykell_sync_loop())
    else:
        app.state.holykell_sync_task = None
        logging.getLogger("zylo_office.holykell_sync").info(
            "HOLYKELL_SYNC_BASE_URL non défini — sondage Holykell désactivé."
        )

    # D5 (refonte alertes, incrémentation détection réelle) — prix/mapping
    # capteur/calibration manquants : structurel, indépendant de Holykell,
    # tourne toujours (contrairement au sondage ci-dessus).
    app.state.structural_sweep_task = asyncio.create_task(structural_sweep_loop())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    for attr in ("holykell_sync_task", "structural_sweep_task"):
        task = getattr(app.state, attr, None)
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


@app.get("/")
def root() -> dict[str, str]:
    return {"service": settings.APP_NAME, "status": "running"}
