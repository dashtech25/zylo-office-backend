# Observabilité — ce qui a été implémenté

Date : 2026-09-11. Compagnon de `observability.md` (qui documente le constat et la
recommandation, non implémentée au moment où il a été écrit) : ce document décrit
ce qui a **réellement été codé** suite à cette recommandation, avec les noms de
champs exacts et comment s'en servir pour diagnostiquer une lenteur. Fait suite à
`phase-1-audit.md` (problème #12, `pg_stat_statements` non installé sur Neon —
toujours vrai, non traité ici, cf. `observability.md` §2).

## 1. Ce qui a été ajouté

- `app/core/middleware.py` : nouveau `TimingMiddleware`, à côté de
  `RequestIdMiddleware` existant, même fichier, même style (sous-classe de
  `starlette.middleware.base.BaseHTTPMiddleware`).
- `app/main.py` : enregistrement de `TimingMiddleware` via `app.add_middleware(...)`,
  ajouté **avant** `RequestIdMiddleware` (voir §3, ordre important).
- Aucune nouvelle dépendance, aucune infrastructure nouvelle — uniquement le
  système d'événements déjà fourni par SQLAlchemy (`sqlalchemy.event`) et le
  mécanisme de `contextvar` déjà en place pour `request_id_ctx`
  (`app/core/logging.py`), réutilisé à l'identique pour les compteurs SQL.
- `app/modules/zylo_liquid/service.py` n'a **pas** été touché (plusieurs sessions
  concurrentes y travaillent actuellement) — cette implémentation est strictement
  transverse (middleware + event listeners sur l'`Engine`), elle instrumente
  n'importe quel endpoint sans modifier son code.

## 2. Ce qui est mesuré, par requête HTTP

- **Durée totale (wall-clock)** : `time.perf_counter()` avant/après
  `call_next(request)` dans `TimingMiddleware.dispatch`.
- **Nombre de requêtes SQL** et **temps cumulé passé dans le driver DB** : deux
  listeners globaux, enregistrés une fois à l'import de `middleware.py` :
  `sqlalchemy.event.listens_for(Engine, "before_cursor_execute")` et
  `"after_cursor_execute"` (sur l'`Engine` de `app/core/database.py`, celui
  utilisé par toutes les sessions). Ils ne font rien si aucune requête HTTP n'est
  en cours (contextvar à `None` — par exemple les requêtes SQL du polling
  Holykell en tâche de fond, hors requête HTTP, ne sont jamais comptées : c'est
  volontaire, seul le coût attribuable à une requête HTTP donnée nous intéresse
  ici).

### Portée par requête : le mécanisme exact

Un compteur (`_SqlStats`, `query_count` + `total_ms`) est créé au début de
`TimingMiddleware.dispatch` et stocké dans une nouvelle `contextvar`,
`_sql_stats_ctx` (`app/core/middleware.py`) — **exactement le même mécanisme que
`request_id_ctx`** déjà utilisé par `RequestIdMiddleware` (une `contextvar` par
tâche asyncio, correctement isolée entre requêtes concurrentes ; un attribut
d'instance ou une variable globale simple serait partagé entre requêtes et donc
faux dès la première concurrence réelle). Les listeners `before/after_cursor_execute`
lisent cette contextvar et incrémentent l'objet qu'elle contient — aucune
modification de `app/core/database.py` n'a été nécessaire, les listeners
s'attachent sur la classe `Engine` de SQLAlchemy en général.

## 3. Ordre des middlewares — pourquoi il compte

`app/main.py` enregistre `TimingMiddleware` **avant** `RequestIdMiddleware`.
Starlette empile les middlewares dans l'ordre inverse des appels à
`add_middleware` (le dernier ajouté est le plus externe). Avec cet ordre,
`RequestIdMiddleware` s'exécute autour de `TimingMiddleware` : `request_id_ctx`
est déjà positionné quand `TimingMiddleware` journalise sa ligne, et n'est
réinitialisé qu'après. Sans cet ordre, `requestId` serait `null` dans la ligne de
timing.

## 4. Le log émis — champs exacts

Un seul logger dédié, `zylo_office.timing` (`logging.getLogger("zylo_office.timing")`),
qui passe par le même `JsonFormatter` que tout le reste de l'application
(`app/core/logging.py`, `setup_logging()` — aucun logger de ce projet ne doit
configurer son propre formatteur). Une ligne JSON par requête HTTP, uniquement
si elle dépasse le seuil (§5) :

```json
{
  "timestamp": "2026-09-11T10:25:47-0400",
  "level": "INFO",
  "logger": "zylo_office.timing",
  "message": "request_timing path=/api/v1/zylo-liquid/cash/network-summary method=GET durationMs=5312.4 sqlQueryCount=41 sqlTotalMs=4890.7",
  "requestId": "3f2a1c9e-...-8b7d"
}
```

Exemple réel capturé pendant la vérification de cette implémentation (endpoint
`/` sans DB, seuil abaissé pour le test — voir §6) :

```json
{"timestamp": "2026-09-11T10:25:47-0400", "level": "INFO", "logger": "zylo_office.timing", "message": "request_timing path=/ method=GET durationMs=623.9 sqlQueryCount=0 sqlTotalMs=0.0", "requestId": "sanity-check-123"}
```

**Pourquoi les champs `path`/`method`/`durationMs`/`sqlQueryCount`/`sqlTotalMs`
sont dans `message` plutôt qu'en clés JSON de premier niveau** : `requestId` est
déjà injecté automatiquement en clé de premier niveau par `JsonFormatter` (via
`request_id_ctx`, mécanisme existant, non modifié). Les autres champs sont passés
en `%s`/`%d` dans le message du logger plutôt qu'en `extra={...}` — vérifié en
lisant `JsonFormatter.format()` (`app/core/logging.py`) : il ne sérialise **pas**
les attributs `extra` d'un `LogRecord` dans le JSON produit (`app/core/errors.py`
utilise déjà `extra={"path": ...}` de la même façon — ces champs n'apparaissent
donc pas non plus dans son JSON de sortie ; limitation préexistante de
`JsonFormatter`, hors du périmètre de cette tâche qui ne touche pas
`app/core/logging.py`). D'où le format `clé=valeur` inline dans `message`, choisi
pour rester grep-able et parsable malgré cette limitation, sans avoir à modifier
le formatteur partagé par toute l'application.

Champs, tous présents sur chaque ligne :

| Champ (emplacement) | Signification |
|---|---|
| `requestId` (clé JSON) | Identique à l'en-tête `X-Request-Id` de la réponse — même valeur que dans tous les autres logs de cette requête |
| `path` (dans `message`) | `request.url.path`, sans query string |
| `method` (dans `message`) | Méthode HTTP |
| `durationMs` (dans `message`) | Durée totale wall-clock du traitement de la requête (middleware à middleware), 1 décimale |
| `sqlQueryCount` (dans `message`) | Nombre de `cursor.execute` SQL exécutés pendant cette requête (toutes sessions confondues) |
| `sqlTotalMs` (dans `message`) | Somme du temps passé entre `before_cursor_execute` et `after_cursor_execute` pour ces requêtes, 1 décimale |

## 5. Seuil de journalisation : `> 500ms`, en INFO

Décision documentée en commentaire dans `app/core/middleware.py`
(`SLOW_REQUEST_THRESHOLD_MS = 500.0`) : la ligne n'est journalisée que si
`durationMs > 500`. Pas de journalisation systématique à chaque requête (gate en
INFO, jamais en DEBUG — demandé explicitement). Raisonnement :

- La latence plancher mesurée en Phase 1 pour une requête SQL individuelle vers
  Neon est de 130–270ms — 500ms laisse une marge confortable pour qu'une requête
  HTTP "normale" (une poignée de requêtes SQL séquentielles) ne déclenche jamais
  de log.
- Les endpoints identifiés comme problématiques en Phase 1
  (`network/summary`, `cash/network-summary`) se comptent en secondes (5,3 à
  plus de 45s) — très largement au-dessus du seuil, donc systématiquement
  capturés.
- Sans seuil, chaque requête (y compris les centaines de requêtes rapides et
  saines par minute en usage normal) produirait une ligne — volume de logs
  ingérable et bruit qui noierait les cas réellement intéressants.

Pour changer ce compromis (par exemple : tout logger en debug ponctuel), modifier
`SLOW_REQUEST_THRESHOLD_MS` dans `app/core/middleware.py` (mettre à `0` journalise
toutes les requêtes) — pas de flag d'environnement dédié à ce jour, volontairement
minimal.

## 6. Comment s'en servir pour répondre à "pourquoi cette page est lente"

- **Cas "j'ai un `requestId` précis"** (ex. remonté par le frontend dans un
  ticket, ou lu dans l'en-tête `X-Request-Id` de la réponse réseau) :
  `grep '"requestId": "<id>"' <fichier-de-logs>` — retrouve la ligne
  `request_timing` de cette requête (si elle a dépassé le seuil) ainsi que
  toutes les autres lignes de log émises pendant son traitement (même
  `requestId` partout, propagé par `RequestIdMiddleware`).
- **Cas "cette page est lente en général, je ne sais pas quel endpoint"** :
  filtrer sur `"logger": "zylo_office.timing"` puis trier/grep sur
  `durationMs=` dans `message`, par exemple :
  `grep '"logger": "zylo_office.timing"' <logs> | grep 'path=/api/v1/zylo-liquid/cash/network-summary'`
  pour isoler un endpoint donné, ou avec `jq` :
  `jq -r 'select(.logger=="zylo_office.timing") | .message' <logs>`
  puis filtrer/trier sur `durationMs=`.
- **Ce que `sqlQueryCount` et `sqlTotalMs` permettent de distinguer** (répond
  directement à la question posée dans `phase-1-audit.md`) :
  - `sqlQueryCount` élevé (ex. 40+) et `sqlTotalMs` proche de `durationMs` →
    problème de type N+1 (beaucoup de requêtes séquentielles), comme le cas
    `get_tank_current_state()` documenté en Phase 1 (§2.1, jusqu'à 8 requêtes
    par cuve).
  - `sqlQueryCount` bas mais `sqlTotalMs` élevé → une ou quelques requêtes
    individuellement lentes (candidates pour `EXPLAIN ANALYZE` ciblé, cf.
    l'index composite manquant documenté en Phase 1 §3#5).
  - `sqlTotalMs` très inférieur à `durationMs` → le temps perdu n'est pas côté
    DB (sérialisation de la réponse, logique applicative CPU-bound, etc.) —
    oriente la recherche ailleurs que vers le SQL.
- Ce mécanisme donne une vue **par requête HTTP individuelle, en temps réel**,
  complémentaire à `pg_stat_statements` (§2 de `observability.md`, non installé,
  toujours en attente) qui donnerait une vue agrégée par requête SQL sur toute
  l'instance dans le temps — aucun des deux ne remplace l'autre (cf.
  `observability.md` §4).

## 7. Vérification effectuée

- `.venv/bin/python3 -m pytest tests/test_zylo_liquid_network_summary.py
  tests/test_zylo_liquid_current_state.py -q` : ces deux fichiers échouent
  actuellement en environnement partagé avec une `DeadlockDetectedError`
  Postgres sur le `TRUNCATE` de fixture (`tests/conftest.py`) — **reproduit à
  l'identique sur le code non modifié** (vérifié via `git stash`), donc causé
  par la contention de plusieurs sessions concurrentes exécutant des tests sur
  la même base Postgres locale au même moment (annoncé dans la consigne de
  cette tâche), pas par ce changement.
- Script autonome (`TestClient` FastAPI direct, seuil de log abaissé
  temporairement dans le script uniquement, pas dans le code source) : l'app
  démarre avec les deux middlewares enregistrés, une requête `GET /` produit
  bien une ligne `zylo_office.timing` / `request_timing` avec `requestId`
  correctement propagé depuis l'en-tête `X-Request-Id` envoyé, `sqlQueryCount`
  et `durationMs` cohérents avec l'endpoint appelé — voir exemple exact au §4.

## 8. Limites connues, non traitées ici

- `pg_stat_statements` toujours non installé (`observability.md` §2) — vue
  agrégée par requête SQL toujours absente ; ce middleware couvre uniquement la
  vue par requête HTTP.
- `sqlTotalMs` mesure le temps entre l'envoi et la réception de chaque curseur
  (driver `asyncpg` compris) — pas une décomposition fine par requête SQL
  individuelle dans le log (pour ça, il faut encore lire les logs `echo=True`
  de SQLAlchemy en développement, ou activer `pg_stat_statements`).
- Aucune rétention/agrégation des logs dans le temps ni tableau de bord —
  volontairement hors périmètre (« pas de nouvelle infrastructure »), ce
  mécanisme suppose que les logs JSON de stdout sont déjà collectés quelque
  part (à vérifier séparément, hors périmètre de cette tâche).
