import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.alerts.service import handle_truck_stop_unqualified
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import setup_logging
from app.core.middleware import RequestIdMiddleware, TimingMiddleware
from app.core.securite_http import EnTetesSecuriteMiddleware, options_documentation
from app.core.migrations import verifie_revision_a_jour
from app.modules.zylo_liquid.telemetry_sync import structural_sweep_loop, sync_loop as holykell_sync_loop
from app.modules.zylo_liquid.roles_seed import seed_default_roles as seed_roles_zylo_liquid
from app.modules.zylo_tanker.roles_seed import seed_default_roles as seed_roles_zylo_tanker
from app.modules_registry.service import enregistre_hook_activation
from app.notifications.service import handle_alert_created
from app.shared.events import subscribe

setup_logging()

TAGS_METADATA = [
    {"name": "health", "description": "Vérification de disponibilité du service."},
    {"name": "auth", "description": "Authentification globale : register, login, refresh, logout, session courante."},
    {"name": "organizations", "description": "Organisations (tenants) et leurs membres — modèle Organization → User → Role → Permission."},
    {"name": "modules", "description": "Registre des modules et activation par organisation (ex: zylo_liquid)."},
    {"name": "rbac", "description": "Rôles, permissions et grants individuels (allow/deny, scopés, délégables)."},
    {"name": "audit", "description": "Journal d'audit — qui a fait quoi, sur quel élément, quand, filtré par portée."},
    {"name": "billing", "description": "Plans, abonnements et facturation par module (aucun prestataire de paiement réel intégré)."},
    {"name": "operator", "description": "Support opérateur strictement en lecture seule, accessible par allowlist serveur."},
    {"name": "currencies", "description": "Référentiel des devises — Core, sans isolation tenant, réutilisable par tout module."},
    {"name": "exchange-rates", "description": "Taux de change historisés — Core, toujours une insertion, jamais une correction."},
]

# Intention (T-015) : Swagger, ReDoc et /openapi.json ne sont montés qu'en
# ENVIRONMENT=development (voir app/core/securite_http.py). Hors développement,
# ces routes n'existent pas : 404.
app = FastAPI(
    title=settings.APP_NAME,
    openapi_tags=TAGS_METADATA,
    **options_documentation(settings.ENVIRONMENT),
)

# Seeds de rôles par défaut, branchés à l'activation (composition root : le socle ne connaît pas les modules).
enregistre_hook_activation("zylo_liquid", seed_roles_zylo_liquid)
enregistre_hook_activation("zylo_tanker", seed_roles_zylo_tanker)

# Ordre important : TimingMiddleware doit être ajouté avant RequestIdMiddleware
# pour s'exécuter à l'intérieur de celui-ci (Starlette empile les middlewares
# dans l'ordre inverse de add_middleware — le dernier ajouté est le plus
# externe). Ainsi request_id_ctx est déjà positionné par RequestIdMiddleware
# quand TimingMiddleware journalise sa ligne "request_timing", et n'est
# réinitialisé qu'après (dans le finally de RequestIdMiddleware, exécuté en
# dernier).
app.add_middleware(TimingMiddleware)
app.add_middleware(RequestIdMiddleware)
# CORS (T-015) : méthodes et en-têtes listés explicitement, ceux qu'utilise le
# frontend (fetch GET/POST/PUT/PATCH/DELETE ; Authorization, Content-Type,
# X-Organization-Id). Une méthode ou un en-tête non listé est refusé au
# préflight. Les origines restent lues depuis la configuration (CORS_ORIGINS).
# T-037a : credentials explicites (cookies de session) et en-tête X-CSRF-Token
# (double soumission, voir app/core/session_http.py). Jamais de joker sur les origines.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Organization-Id", "X-CSRF-Token", "Accept"],
)
# En-têtes de sécurité (T-015) : ajoutés en dernier, donc les plus externes ;
# ils couvrent aussi les réponses du préflight CORS.
app.add_middleware(EnTetesSecuriteMiddleware)

register_exception_handlers(app)

app.include_router(api_router, prefix="/api/v1")

# Phase 5 (migration monolithe modulaire, événements de domaine en mémoire)
# — inscription des abonnements au niveau module, pas dans `on_startup` :
# la suite de tests appelle l'app via `httpx.ASGITransport`, qui ne
# déclenche jamais les événements FastAPI "startup" (voir le commentaire
# équivalent dans `tests/conftest.py` pour le seed des permissions) ; un
# abonnement enregistré seulement au démarrage serait donc silencieusement
# absent en test. `app/main.py` est le point de composition central du
# projet : le seul endroit autorisé à faire se connaître deux modules qui,
# sinon, n'ont plus besoin de s'importer l'un l'autre (voir
# `app.shared.events` et `app.location.service.run_truck_stop_detection`,
# premier cas d'usage réel).
subscribe("TruckStopUnqualified", handle_truck_stop_unqualified)
# Notifications Web Push (2026-09-20) — même mécanisme, voir la docstring
# de `app.notifications.service` pour le détail du découplage.
subscribe("AlertCreated", handle_alert_created)


@app.on_event("startup")
async def on_startup() -> None:
    # T-028 : le démarrage ne migre pas, ne seed pas et ne rejoue aucun backfill.
    # Migrations : `python -m app.cli migrer` ; seeds et backfills : `python -m
    # app.cli seed` puis `python -m app.cli backfill`, une fois par déploiement
    # (docs/operations/deploiement.md). Ici, seule une vérification en lecture
    # seule : une base non à la tête fait refuser le démarrage avec un message clair.
    await verifie_revision_a_jour()

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
