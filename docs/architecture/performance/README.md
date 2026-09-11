# Architecture de performance — Zylo Office / Zylo Liquid

Ce dossier documente l'audit, la décision d'architecture et les règles de performance du module Zylo Liquid (frontend Next.js + backend FastAPI + Postgres Neon). Point de départ recommandé : ce fichier, puis `phase-1-audit.md`.

**Le problème** : plusieurs écrans (réseau, station, caisse) devenaient lents à mesure que le volume de données croissait — jusqu'à 27,4 s pour `network/summary` et un timeout (>60 s) sur la caisse à 30 jours — à cause d'un pattern N+1 systématique côté backend (des dizaines à des centaines de requêtes SQL séquentielles par appel d'endpoint) combiné à l'absence quasi totale de cache client côté frontend (seuls 4 hooks sur 45 utilisaient React Query, causant un rechargement complet à chaque changement d'onglet).

**Ce qui a été trouvé** : cartographie complète en `phase-1-audit.md`, 15 problèmes classés P0-P3, chacun avec preuve mesurée (chronométrage HTTP, `EXPLAIN ANALYZE`, citations fichier:ligne) — aucune supposition non vérifiée.

**Ce qui a été décidé** : une architecture hybride en 5 axes (`phase-2-architecture-decision.md`) — réduction du nombre de requêtes SQL par batching `IN (...)` et résolution en mémoire, un index composite manquant, un cache serveur léger en mémoire (pas Redis), l'adoption de React Query partout, et un rendu progressif par widget — sans nouvelle dépendance d'infrastructure, en priorisant la performance réelle avant la sophistication.

## Sommaire

| Fichier | Contenu |
|---|---|
| [`phase-1-audit.md`](phase-1-audit.md) | Audit mesuré (baseline) — 15 problèmes classés P0-P3, preuves fichier:ligne et chronométrages réels |
| [`phase-2-architecture-decision.md`](phase-2-architecture-decision.md) | Comparaison des architectures candidates (A-E) et décision justifiée (E, hybride) |
| [`phase-3-implementation.md`](phase-3-implementation.md) | Ce qui a réellement été livré (backend + frontend), avec preuves de non-régression |
| [`phase-4-benchmark-results.md`](phase-4-benchmark-results.md) | Mesures avant/après réelles + preuve de mise à l'échelle par construction du code |
| [`performance-budget.md`](performance-budget.md) | Cibles chiffrées par catégorie d'endpoint (login, liste simple, agrégat réseau, caisse jour/7j/30j) et budget de payload, chacune dérivée des mesures de Phase 1 |
| [`benchmark.md`](benchmark.md) | Méthodologie de mesure (httpx bout-en-bout, `EXPLAIN ANALYZE` via asyncpg, comptage de requêtes, seeding synthétique) — pas de résultats, cross-référencer les fichiers de résultats séparés |
| [`anti-patterns.md`](anti-patterns.md) | Catalogue des patterns interdits avec cas réels de ce dépôt (N+1, `limit: 100` sans pagination, fetch sans cache, `loading` global, sur-interrogation de données statiques) et leur correctif |
| [`developer-guide.md`](developer-guide.md) | Règles DO/DON'T pour tout nouveau code, checklists avant d'ajouter un appel API ou une boucle DB |
| [`database-performance.md`](database-performance.md) | Détail du pattern N+1 côté `zylo_liquid/service.py` et de sa correction |
| [`api-performance.md`](api-performance.md) | Ce qui se joue au niveau HTTP/FastAPI/transport, séparément du SQL |
| [`caching.md`](caching.md) | Architecture de cache retenue (client React Query + cache serveur mémoire léger) |
| [`cache-invalidation.md`](cache-invalidation.md) | Détail par type de donnée des mécanismes d'invalidation |
| [`data-fetching.md`](data-fetching.md) | Stratégie de fetch côté Next.js 15 App Router |
| [`pagination.md`](pagination.md) | Le problème `limit: 100` (43 occurrences) et la pagination réelle à mettre en place |
| [`observability.md`](observability.md) | Combler le trou d'observabilité identifié en Phase 1 (`pg_stat_statements` absent) |
| [`real-time.md`](real-time.md) | Décision de ne pas introduire WebSocket/SSE à ce stade, et conditions de révision |

Cette liste reflète l'état du dossier au 2026-09-11 (vérifié par `ls` juste avant publication). Des fichiers supplémentaires peuvent avoir été ajoutés depuis par des sessions parallèles — vérifier `ls docs/architecture/performance/` pour la liste exhaustive courante.
