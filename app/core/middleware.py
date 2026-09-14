import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import request_id_ctx


class RequestIdMiddleware:
    """Attribue un requestId unique à chaque requête, propagé dans tous les logs
    émis pendant son traitement (via la contextvar request_id_ctx) et renvoyé
    dans l'en-tête X-Request-Id pour permettre au client de le référencer.

    ASGI pur (pas `BaseHTTPMiddleware`, 2026-09-14) — `BaseHTTPMiddleware`
    attend que `call_next` ait entièrement consommé la réponse pour la
    reconstruire, ce qui bufferise sans fin une réponse en streaming
    (SSE `/trucks/live-positions`) : le client ne reçoit jamais rien tant
    que le flux ne se termine pas, et un flux voulu infini ne se termine
    jamais. Un middleware ASGI relaie chaque message dès qu'il est produit,
    sans le bug."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_ctx.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_ctx.reset(token)


_timing_logger = logging.getLogger("zylo_office.timing")

# Seuil au-delà duquel une requête est jugée "lente" et journalisée (voir
# TimingMiddleware ci-dessous). Choisi à partir des mesures de
# docs/architecture/performance/phase-1-audit.md : les endpoints identifiés
# comme problématiques (network/summary, cash/network-summary) se comptent en
# secondes, alors que la latence plancher Neon mesurée pour une requête
# individuelle est de 130-270ms. 500ms laisse une marge confortable au-dessus
# de ce plancher (même une poignée de requêtes séquentielles normales reste
# sous ce seuil) tout en capturant tout ce qui commence à dégrader
# l'expérience utilisateur — sans journaliser chaque requête en continu, ce
# qui produirait un volume de logs ingérable en usage normal (gate en INFO,
# pas en DEBUG, comme demandé).
SLOW_REQUEST_THRESHOLD_MS = 500.0


@dataclass
class _SqlStats:
    """Compteurs SQL accumulés pendant le traitement d'une requête HTTP —
    tenus par une contextvar (même mécanisme que request_id_ctx ci-dessus,
    seul moyen fiable de scoper un état par requête à travers les callbacks
    d'événements SQLAlchemy en contexte async, où un attribut d'instance ou
    une variable globale serait partagé entre requêtes concurrentes)."""

    query_count: int = 0
    total_ms: float = 0.0


_sql_stats_ctx: ContextVar["_SqlStats | None"] = ContextVar("sql_stats", default=None)


@event.listens_for(Engine, "before_cursor_execute")
def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    stats = _sql_stats_ctx.get()
    if stats is not None:
        context._zylo_query_start = time.perf_counter()


@event.listens_for(Engine, "after_cursor_execute")
def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:
    stats = _sql_stats_ctx.get()
    if stats is None:
        return
    start = getattr(context, "_zylo_query_start", None)
    if start is None:
        return
    stats.query_count += 1
    stats.total_ms += (time.perf_counter() - start) * 1000


class TimingMiddleware:
    """Mesure, pour chaque requête, la durée totale (wall-clock) et le coût SQL
    associé (nombre de requêtes + temps cumulé passé dans le driver DB), via
    les événements SQLAlchemy before/after_cursor_execute sur l'Engine
    (app/core/database.py). Répond au trou d'observabilité identifié en
    Phase 1 (pg_stat_statements non installé sur Neon, cf.
    docs/architecture/performance/phase-1-audit.md §2.1/§3#12) sans dépendance
    externe ni infrastructure supplémentaire — uniquement en-process.

    Ne journalise qu'au-delà de SLOW_REQUEST_THRESHOLD_MS pour rester
    utilisable en continu sans noyer les logs (voir commentaire du seuil).

    ASGI pur (pas `BaseHTTPMiddleware`, 2026-09-14) — même raison que
    `RequestIdMiddleware` ci-dessus : `call_next` bufferise sans fin une
    réponse en streaming (SSE). Un flux voulu infini n'est jamais "lent" au
    sens de ce seuil — durationMs mesuré ici court jusqu'à la fermeture de
    la connexion, jamais journalé pour un flux qui vit normalement plus de
    500ms (c'est son but), donc rien à filtrer spécifiquement."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        stats = _SqlStats()
        token = _sql_stats_ctx.set(stats)
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            _sql_stats_ctx.reset(token)
            if duration_ms > SLOW_REQUEST_THRESHOLD_MS:
                # requestId est déjà injecté automatiquement dans chaque ligne
                # JSON par JsonFormatter (via request_id_ctx) — les autres
                # champs sont encodés dans le message en clé=valeur pour rester
                # greppables (JsonFormatter, app/core/logging.py, ne
                # sérialise pas les kwargs `extra` dans le JSON de sortie).
                _timing_logger.info(
                    "request_timing path=%s method=%s durationMs=%.1f sqlQueryCount=%d sqlTotalMs=%.1f",
                    scope.get("path"),
                    scope.get("method"),
                    duration_ms,
                    stats.query_count,
                    stats.total_ms,
                )
