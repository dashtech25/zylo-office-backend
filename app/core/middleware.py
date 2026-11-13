"""Middlewares ASGI transverses (BE-001).

- `RequestIdMiddleware` : un request ID par requête, repris du client s'il
  respecte le motif, sinon généré ; posé dans `scope["state"]`, dans la
  contextvar `request_id_ctx` (journaux) et dans les en-têtes
  `X-Request-Id` et `X-Correlation-Id` de la réponse.
- `TimingMiddleware` : journalise les requêtes lentes et leur coût SQL.

Les deux sont en ASGI pur, pour ne pas bufferiser les réponses en flux.
Le format des erreurs est dans app/core/errors.py.
"""

import logging
import re
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import correlation_id_ctx, operation_id_ctx, request_id_ctx

_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
# Même contrat que BE-232 (app/core/idempotency.py) : clé choisie par le client,
# 16 à 120 caractères.
_IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,120}$")
_METHODES_MUTANTES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Espace de noms fixe : un même (méthode, chemin, clé) donne toujours le même UUID v5.
_NAMESPACE_OPERATION = uuid.uuid5(uuid.NAMESPACE_URL, "zylo-office:operation")


def _operation_id(method: str, path: str, headers) -> str | None:
    """Retourne l'operationId d'une requête, ou None pour une lecture.

    BE-181 (CA-3) : chaque mutation reçoit un operationId. Quand le client
    envoie un Idempotency-Key valide, l'identifiant est un UUID v5 dérivé de
    la méthode, du chemin et de la clé : un rejeu (même clé, même route)
    obtient le même operationId, sans état partagé. Sans clé valide, un UUID
    v4 neuf est généré : il n'est alors stable pour aucun rejeu (cas à traiter
    côté client, voir la documentation de la tâche).

    L'operationId sert à corréler les journaux et l'audit, jamais à décider
    d'une autorisation : deux tenants envoyant la même clé sur la même route
    partagent donc le même identifiant, ce qui est acceptable pour une trace."""
    if method not in _METHODES_MUTANTES:
        return None
    cle = headers.get("idempotency-key")
    if cle is not None and _IDEMPOTENCY_KEY_PATTERN.fullmatch(cle):
        return str(uuid.uuid5(_NAMESPACE_OPERATION, f"{method} {path}\n{cle}"))
    return str(uuid.uuid4())


def _request_id(headers) -> str:
    """Retient le premier identifiant client valide parmi X-Request-Id puis
    X-Correlation-Id ; sinon génère un UUID.

    Chaque en-tête est jugé séparément : un X-Request-Id invalide ne doit pas
    écarter un X-Correlation-Id valide (CA-6 de BE-001). Le motif borne la
    longueur et le jeu de caractères, car la valeur est reprise dans les
    journaux et dans les en-têtes de réponse."""
    for nom in ("x-request-id", "x-correlation-id"):
        candidate = headers.get(nom)
        if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
            return candidate
    return str(uuid.uuid4())


def _correlation_id(headers, request_id: str) -> str:
    """Retient le X-Correlation-Id client s'il respecte le motif, sinon reprend
    le request_id (contrat BE-001 : une requête sans correlation garde un seul
    identifiant visible). Un X-Correlation-Id distinct du X-Request-Id donne
    donc un correlationId distinct, propagé à travers les tâches et intégrations
    de la requête (BE-224, CA-1)."""
    candidate = headers.get("x-correlation-id")
    if candidate is not None and _REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return request_id


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
        request_id = _request_id(request.headers)
        # Starlette ServerErrorMiddleware (qui produit les 500 non gérées)
        # est extérieur aux middlewares applicatifs. Le garder dans le scope
        # permet au gestionnaire d'erreur externe de le récupérer même après
        # la sortie de cette contextvar.
        correlation_id = _correlation_id(request.headers, request_id)
        scope.setdefault("state", {})["request_id"] = request_id
        scope["state"]["correlation_id"] = correlation_id
        operation_id = _operation_id(scope.get("method", "GET"), scope.get("path", ""), request.headers)
        scope["state"]["operation_id"] = operation_id
        token = request_id_ctx.set(request_id)
        # Copiée par les tâches asynchrones créées pendant la requête et lue
        # par les appels d'intégration : même correlationId de bout en bout.
        correlation_token = correlation_id_ctx.set(correlation_id)
        operation_token = operation_id_ctx.set(operation_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                # Remplace les éventuels headers posés par une route pour que
                # la réponse et l'enveloppe d'erreur gardent un ID unique.
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() not in (b"x-request-id", b"x-correlation-id")
                ]
                headers.append((b"x-request-id", request_id.encode()))
                headers.append((b"x-correlation-id", correlation_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            operation_id_ctx.reset(operation_token)
            correlation_id_ctx.reset(correlation_token)
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
