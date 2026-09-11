"""Cache TTL en mémoire, minimal, pour données de référence quasi
statiques (produits carburant, villes, devises...).

Décision volontaire (Phase 1 — audit performance, `docs/architecture/
performance/phase-1-audit.md`, problème #3) : pas de Redis ni d'autre
infrastructure nouvelle à cette échelle (5 stations, tables petites) —
un cache in-process suffit et évite d'ajouter une dépendance non prouvée
nécessaire. `cachetools` n'est pas dans `requirements.txt` (vérifié) : pas
réinventé pour réinventer, juste plus simple d'écrire les ~25 lignes utiles
ici que d'ajouter une dépendance pour ça.

Limite assumée : ce cache est local au process. Avec plusieurs workers/
instances (pas le cas actuel — un seul process dev), chaque worker aurait
sa propre copie et pourrait servir une valeur légèrement différente
pendant la fenêtre TTL. Acceptable pour des données quasi statiques avec
TTL court (60s, aligné sur le `staleTime` React Query du frontend,
`QueryProvider.tsx`) ; à revisiter seulement si la mise à l'échelle
horizontale devient réelle."""

import time
from typing import Any


class TTLCache:
    """Cache clé/valeur arbitraire avec expiration TTL. Pas thread-safe au
    sens strict (pas nécessaire : un seul thread d'event loop asyncio par
    worker, jamais de vrai parallélisme sur ce dict)."""

    def __init__(self, default_ttl_seconds: float = 60.0) -> None:
        self._default_ttl = default_ttl_seconds
        self._store: dict[str, tuple[Any, float]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.monotonic() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl_seconds: float | None = None) -> None:
        ttl = self._default_ttl if ttl_seconds is None else ttl_seconds
        self._store[key] = (value, time.monotonic() + ttl)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def invalidate_prefix(self, prefix: str) -> None:
        """Invalide toutes les clés commençant par `prefix` — utile pour une
        liste paginée où la clé varie par page/limite mais dont la donnée
        source vient de changer (une seule organisation, par exemple)."""
        for key in [k for k in self._store if k.startswith(prefix)]:
            self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()
