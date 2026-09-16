"""Registre d'événements de domaine — en mémoire, un seul process, pas de
bus distribué (Phase 5 de la migration monolithe modulaire, voir
`ARCHITECTURE.md` §4). `subscribe(event_name, handler)` enregistre un
handler asynchrone ; `publish(event_name, **payload)` exécute tous les
handlers abonnés à cet événement, dans l'ordre d'inscription.

**Toujours publier après le commit** de la transaction qui a produit
l'événement — jamais avant, jamais dans la même transaction. Un handler
peut avoir besoin d'ouvrir sa propre session (`AsyncSessionLocal`) pour
écrire sa propre conséquence métier ; s'il lisait un état pas encore
committé par l'appelant, il verrait une donnée qui n'existe peut-être
jamais vraiment (rollback possible entre la publication et le commit).
Ce module ne fait respecter cette règle par aucun mécanisme — c'est une
discipline à l'appel, documentée ici et illustrée par le premier cas
d'usage réel : `app.location.service.run_truck_stop_detection` collecte
les événements `TruckStopUnqualified` pendant sa boucle mais ne les
publie qu'après son propre `await db.commit()`.

Une erreur dans un handler est journalisée et n'interrompt jamais les
handlers suivants ni l'appelant de `publish` — même discipline que les
autres opérations dérivées "best-effort" du projet (ex. détection
d'arrêt lancée depuis l'ingestion GPS)."""

import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

EventHandler = Callable[..., Awaitable[None]]

_handlers: dict[str, list[EventHandler]] = defaultdict(list)


def subscribe(event_name: str, handler: EventHandler) -> None:
    """Enregistre `handler` pour `event_name` — appelé une fois par
    process, typiquement au démarrage de l'application (voir `app/main.py`),
    jamais à l'intérieur d'une requête."""
    _handlers[event_name].append(handler)


async def publish(event_name: str, **payload: Any) -> None:
    """Exécute chaque handler abonné à `event_name` avec `payload` en
    arguments nommés. Aucun consommateur abonné : silencieux, pas une
    erreur — un événement de domaine n'a pas d'obligation d'être écouté."""
    for handler in _handlers.get(event_name, []):
        try:
            await handler(**payload)
        except Exception:
            logger.exception("échec du handler d'événement %s (%s)", event_name, getattr(handler, "__qualname__", handler))
