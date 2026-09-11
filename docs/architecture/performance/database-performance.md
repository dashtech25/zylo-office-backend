# Performance base de données — le problème N+1 et sa correction

Date : 2026-09-11. Fait suite à `phase-1-audit.md` (preuves mesurées) et `phase-2-architecture-decision.md` (architecture E retenue, §3.1). Ce document explique le pattern de correction appliqué aujourd'hui côté `zylo_liquid/service.py` et la règle à suivre pour tout code futur.

## 1. Le problème mesuré

Phase 1 a mesuré, avant tout correctif :

- `GET /zylo-liquid/network/summary` : **27,4 s**. Cause : `get_tank_current_state()` faisait jusqu'à **8 requêtes séquentielles par cuve** (capteur niveau, calibration, capteur eau, capteur température, produit, prix station, chaîne prix réseau par défaut station→ville→région→pays→devise, devise). Avec 13 cuves : ~65-100 allers-retours séquentiels.
- `GET /zylo-liquid/cash/network-summary` : **34,8–37,9 s** (aujourd'hui), **45–53 s** (7 jours), **timeout >60 s** (30 jours). Cause : `_price_sub_segments_for_sale_window` (service.py ~L3044) rappelait la chaîne complète de résolution prix/devise (jusqu'à 6 requêtes) **à chaque frontière de segment de vente, par cuve, par jour**.

Le goulot n'était pas le volume de données transférées ni la taille du pool de connexions — c'était le nombre d'allers-retours séquentiels vers une base distante (Neon, ~130-270 ms/requête, cf. `phase-1-audit.md` §2.1).

## 2. La correction : batching par type de donnée, pas par entité

Principe retenu (Phase 2 §3.1) : **une requête par TYPE de donnée pour l'ensemble des entités demandées, jamais une requête par entité**. Fonctions réellement en place dans `app/modules/zylo_liquid/service.py` :

- `get_tanks_current_state_batch` (L1311) — remplace l'ancien `get_tank_current_state` appelé en boucle. Charge en une passe : mappings capteurs (`TankSensorMapping` JOIN `HolykellDeviceRegistry`, `IN (tank_ids)`), calibrations (`IN (tank_ids)`), produits carburant (`IN (fuel_product_ids)`), stations (`IN (station_ids)`), puis résout les prix/devises via les fonctions batchées ci-dessous, et ne fait la recombinaison par cuve **qu'en mémoire** (boucle Python, aucune requête). `get_tank_current_state` (L1379) devient un simple appel à la version batchée avec une liste à un élément — le calcul (`_build_tank_current_state`) n'est jamais dupliqué.
- `_resolve_station_currencies_batch` (L2616) — remplace la chaîne station→ville→région→pays→devise rejouée par station. Une requête par étape de la chaîne (`Currency` pour les dérogations, `City`, `Region`, `Country`, `Currency`) pour **toutes** les stations demandées, recombinée par station en mémoire.
- `_resolve_applicable_prices_batch` (L2692) — même sémantique que l'ancien `_resolve_applicable_price` (prix station en priorité, repli prix réseau filtré par devise), mais une requête par étape pour l'ensemble des paires `(station, produit)`.
- `_CashPriceContext` / `_build_cash_price_contexts` (L2742/L2759) — spécifique à la caisse : pré-charge une fois par cuve les prix réseau par défaut et la devise résolue, pour éviter de refaire la chaîne complète à chaque frontière de segment de vente.
- `_price_at_or_before` (L2796) — résout un prix applicable **parmi des lignes déjà chargées en mémoire** (`max()` sur une liste filtrée), zéro requête. C'est la pièce qui transforme du "une requête par frontière" en "une requête pour tout, puis du calcul en mémoire".

### Avant/après (forme du problème, illustrative)

```python
# AVANT (forme du problème réel avant correctif — une requête par cuve)
for tank in tanks:
    sensor = await get_sensor_for_tank(db, tank.id)       # 1 requête
    calibration = await get_calibration(db, tank.id)       # 1 requête
    price = await resolve_applicable_price(db, tank)       # jusqu'à 6 requêtes
    ...

# APRÈS (get_tanks_current_state_batch, service.py L1311)
tank_ids = [t.id for t in tanks]
registry_result = await db.execute(select(...).where(TankSensorMapping.tankId.in_(tank_ids)))
price_by_pair = await _resolve_applicable_prices_batch(db, pairs, stations_by_id, now)
for tank in tanks:
    states[tank.id] = _build_tank_current_state(tank, registry_by_key.get(...), ...)  # mémoire, 0 requête
```

## 3. Résultat mesuré

`network/summary` : 27,4 s → **5,3–8,1 s** (mesures avec/sans contention réseau ambiante). Le plancher de latence par requête (~130-270 ms) subsiste — irréductible sans réduire encore le nombre d'allers-retours ou rapprocher l'environnement de dev de Neon. La caisse (`_price_sub_segments_for_sale_window`, service.py ~L3044) **n'est pas encore corrigée** au moment de ce document — `_build_cash_price_contexts` existe et est prêt à être branché, mais son intégration dans le chemin caisse sur 7/30 jours reste à vérifier dans `phase-3-implementation.md`.

## 4. Index composite manquant sur `TankMeasurement`

Preuve Phase 1 : `EXPLAIN ANALYZE` sur le pattern `_measurement_at_or_before` (service.py L2452, `WHERE hkSensorId IN (...) AND measuredAt <= X ORDER BY measuredAt DESC LIMIT 1`) montrait `Rows Removed by Filter: 17473` sur 17 636 lignes — l'index sur `measuredAt` seul ne permet pas de filtrer `hkSensorId` efficacement.

**État : appliqué.** La migration `alembic/versions/9355a8709666_tank_measurement_sensor_measuredat_index.py` (créée aujourd'hui) ajoute `ix_zyloLiquidTankMeasurement_hkSensorId_measuredAt` sur `(hkSensorId, measuredAt DESC)`, et `TankMeasurement.__table_args__` (`app/modules/zylo_liquid/models.py` L145-161) déclare le même index côté modèle déclaratif. Le partitionnement mensuel documenté dans le commentaire du modèle (L139-141) n'est lui **pas** implémenté — jugé non nécessaire au volume actuel (17,8K lignes), classé P3 en Phase 1, à surveiller via `pg_stat_statements` une fois installé (cf. `observability.md`).

## 5. Règle générale pour tout code futur

**Quand du code traite une liste d'entités, chaque dépendance se charge UNE fois via `WHERE x IN (...)`, jamais dans une boucle par entité.** Concrètement :

1. Rassembler les identifiants nécessaires (`{t.id for t in entities}`) avant toute requête.
2. Charger chaque type de dépendance en un seul `SELECT ... WHERE id IN (...)`, indexé par un dict `{id: objet}`.
3. Ne recombiner qu'en mémoire, dans une boucle Python — jamais de nouvel `await db.execute(...)` à l'intérieur de cette boucle.
4. Si une dépendance dépend elle-même d'une autre (ex. devise ← pays ← région ← ville ← station), batcher chaque étage de la chaîne séparément (voir `_resolve_station_currencies_batch`), pas la chaîne entière par entité de départ.

Un appel ponctuel sur une seule entité reste acceptable en déléguant à la version batchée avec une liste à un élément (cf. `get_tank_current_state`) — jamais en dupliquant le calcul.
