import logging
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_ctx


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Attribue un requestId unique à chaque requête, propagé dans tous les logs
    émis pendant son traitement (via la contextvar request_id_ctx) et renvoyé
    dans l'en-tête X-Request-Id pour permettre au client de le référencer."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        token = request_id_ctx.set(request_id)
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        response.headers["X-Request-Id"] = request_id
        return response


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


class TimingMiddleware(BaseHTTPMiddleware):
    """Mesure, pour chaque requête, la durée totale (wall-clock) et le coût SQL
    associé (nombre de requêtes + temps cumulé passé dans le driver DB), via
    les événements SQLAlchemy before/after_cursor_execute sur l'Engine
    (app/core/database.py). Répond au trou d'observabilité identifié en
    Phase 1 (pg_stat_statements non installé sur Neon, cf.
    docs/architecture/performance/phase-1-audit.md §2.1/§3#12) sans dépendance
    externe ni infrastructure supplémentaire — uniquement en-process.

    Ne journalise qu'au-delà de SLOW_REQUEST_THRESHOLD_MS pour rester
    utilisable en continu sans noyer les logs (voir commentaire du seuil)."""

    async def dispatch(self, request: Request, call_next) -> Response:
        stats = _SqlStats()
        token = _sql_stats_ctx.set(stats)
        start = time.perf_counter()
        try:
            response = await call_next(request)
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
                    request.url.path,
                    request.method,
                    duration_ms,
                    stats.query_count,
                    stats.total_ms,
                )
        return response
