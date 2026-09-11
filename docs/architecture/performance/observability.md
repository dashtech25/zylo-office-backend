# Observabilité — combler le trou identifié en Phase 1

Date : 2026-09-11. Fait suite à `phase-1-audit.md` (problème #12, classé P2) et `phase-2-architecture-decision.md` (§4, `pg_stat_statements` cité comme instrument de suivi pour décider du partitionnement futur de `TankMeasurement`).

## 1. Objectif

**Étant donné une plainte "cette page est lente", pouvoir répondre "combien de requêtes SQL, combien de temps DB total, quel endpoint" en quelques minutes — pas en re-dérivant l'information via un `EXPLAIN ANALYZE` ad hoc à chaque fois**, comme cela a été nécessaire pour produire `phase-1-audit.md`. C'est le trou que ce document vise à combler : aujourd'hui, chaque diagnostic de lenteur part de zéro.

## 2. `pg_stat_statements` — non installé, à activer

Vérifié en Phase 1, sur l'instance Neon utilisée : `pg_stat_statements` n'est **pas** installé. Sans lui, aucune visibilité agrégée sur les requêtes les plus coûteuses en conditions réelles — les mesures de `phase-1-audit.md` ont dû être obtenues via `EXPLAIN ANALYZE` ciblé et du chronométrage HTTP manuel, requête par requête, plutôt qu'en interrogeant une vue d'ensemble.

Neon supporte `pg_stat_statements` comme extension activable en self-serve sur les plans où les extensions PostgreSQL standard sont autorisées (`CREATE EXTENSION pg_stat_statements;`) — **à vérifier concrètement sur ce projet Neon avant de considérer l'activation acquise** : la disponibilité dépend du plan et de la configuration du projet (`shared_preload_libraries`), qui peut nécessiter un redémarrage de l'instance ou un ajustement via le dashboard/support Neon plutôt qu'un simple `CREATE EXTENSION` en SQL. Non vérifié directement dans le cadre de cette mission — à confirmer avant la prochaine phase d'implémentation.

## 3. Middleware de requête — ce qui existe, ce qui manque

`app/core/middleware.py` contient aujourd'hui `RequestIdMiddleware` : attribue un `request_id` (UUID ou repris de l'en-tête `X-Request-Id` entrant) à chaque requête, le propage via une `contextvar` (`request_id_ctx`, `app/core/logging.py`) dans tous les logs émis pendant le traitement, et le renvoie dans l'en-tête de réponse. Vérifié au moment de ce document (aucune session parallèle n'a encore modifié ce fichier) : **aucun timing de requête ni comptage de requêtes SQL n'y est ajouté** — le middleware trace l'identité de la requête, pas sa durée ni son coût DB.

## 4. Recommandation : middleware de timing + comptage SQL

Prochaine étape concrète, minimale, sans nouvelle dépendance :

1. **Durée totale de la requête** — mesurer `time.monotonic()` avant/après `call_next(request)` dans un middleware (à ajouter à côté de `RequestIdMiddleware`, même fichier ou nouveau `TimingMiddleware` dans `app/core/middleware.py`), logger `request_id` (déjà disponible via `request_id_ctx`), méthode, chemin, code de statut, durée en ms.
2. **Nombre de requêtes SQL par requête HTTP** — un compteur simple, incrémenté via l'événement SQLAlchemy `after_cursor_execute` (event listener sur l'`engine`, `app/core/database.py`), stocké dans la même `contextvar` que `request_id` (ou une nouvelle dédiée) et remis à zéro à chaque requête HTTP entrante — pas besoin d'un compteur par `AsyncSession` si les sessions ne sont jamais partagées entre requêtes (vérifié : `get_db()` crée une session par requête, `app/core/database.py:25-27`).
3. **Log structuré en sortie de requête** : `{request_id, method, path, status, duration_ms, sql_query_count}` — un seul log par requête HTTP, émis à la fin de `dispatch()`, suffisant pour répondre à la question posée en §1 par une simple recherche sur `request_id` ou un `grep`/filtre sur `duration_ms` élevé, sans réinstrumenter à chaque incident.

Cette proposition n'est pas implémentée à ce jour (vérifié : `middleware.py` ne contient que `RequestIdMiddleware`). Elle est indépendante de `pg_stat_statements` (§2) : le middleware donne une vue par requête HTTP individuelle en temps réel, `pg_stat_statements` donne une vue agrégée par requête SQL sur toute l'instance dans le temps — les deux se complètent, aucun ne remplace l'autre.

## 5. Priorité relative

Classé P2 en Phase 1 — sous les corrections P0 déjà traitées (N+1, index composite) et sous la pagination (P0, risque de correction en plus de performance, cf. `pagination.md`). Pertinent dès maintenant en soutien du suivi de `TankMeasurement` (Phase 2 §4 : le partitionnement mensuel documenté mais non implémenté doit être décidé "avant que le volume réel n'atteigne l'échelle où un index seul ne suffit plus... à surveiller via `pg_stat_statements` une fois installé") — sans cet instrument, ce seuil ne peut être détecté qu'empiriquement, après dégradation perceptible.
