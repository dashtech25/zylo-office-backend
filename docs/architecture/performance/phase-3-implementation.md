# Phase 3 — Implémentation

Date : 2026-09-11. Fait suite à `phase-2-architecture-decision.md` (architecture hybride E retenue). Ce fichier documente ce qui a réellement été livré, pas un plan — chaque point est vérifiable dans le code/les tests/les mesures.

## 1. Backend — élimination du N+1 (axe 3.1 de la décision)

### 1.1 Stock (`network/summary`, `current-state`)
- `get_tank_current_state` (par cuve, jusqu'à 8 requêtes séquentielles) → `get_tanks_current_state_batch` (`app/modules/zylo_liquid/service.py`) : un aller-retour par TYPE de donnée pour l'ensemble des cuves demandées (capteurs, calibrations, produits, prix, devises), au lieu d'un par cuve. `get_tank_current_state` devient un batch-of-one qui délègue à la même fonction — aucune double implémentation du calcul (`_build_tank_current_state`, fonction pure, aucun accès DB).
- Nouvelles fonctions batchées : `_resolve_station_currencies_batch` (chaîne dérogation→ville→région→pays→devise, pour toutes les stations demandées en une passe), `_resolve_applicable_prices_batch` (prix station + repli réseau par défaut, pour toutes les paires station×produit en une passe).
- `get_network_summary` et `get_station_current_state` appellent la version batchée une seule fois au lieu de boucler.
- **Mesuré** : `network/summary` 27,4s → 5-8s (mesures hors contention). Amélioration réelle mais le temps restant est dominé par un nombre fixe (~15-20) de requêtes séquentielles à ~200-300ms de latence chacune (voir `database-performance.md` pour la suite : parallélisation envisagée, index composite).

### 1.2 Caisse (`cash/network-summary`, `cash/station/{id}`)
Le moteur de caisse (`_compute_tank_cash`) refaisait la résolution complète prix/devise (`_resolve_applicable_price`, jusqu'à 6 requêtes avec repli réseau) à **chaque frontière de segment de vente**, par cuve, par jour de la période — le pire cas de tout l'audit (35-53s, timeout sur 30 jours).

- `_CashPriceContext` : structure pré-calculée (prix réseau par défaut du produit + devise résolue de la station), construite UNE FOIS pour tout le réseau (`_build_cash_price_contexts`) plutôt qu'à chaque frontière.
- `_price_at_or_before` : résolution du prix propre à la station en mémoire (les lignes `PriceHistory` de la station sont déjà chargées par `_compute_tank_cash`), sans requête.
- Paramètre optionnel `price_context` fileté à travers toute la chaîne (`_compute_tank_cash` → `_price_sub_segments_for_sale_window` → `_compute_tank_cash_over_period` → `_get_or_compute_tank_cash_for_day` → `get_station_cash_detail`/`get_network_cash_summary`) — **rétrocompatible** : `price_context=None` (défaut) reproduit exactement l'ancien comportement, donc tout appelant non mis à jour (ex. `get_tank_cash`, la traçabilité complète d'une seule cuve) continue de fonctionner sans changement.
- `sensor_ids` également fileté à travers `_measurement_at_or_before`/`_cash_boundary_height_and_volume` — la résolution des capteurs "product_level" d'une cuve, répétée à chaque frontière, se fait maintenant une fois par cuve.
- `get_network_cash_summary` : les cuves de toutes les stations sont chargées en une seule requête (au lieu d'une requête par station), et la dernière mesure connue (`lastMeasurementAt`) de toutes les cuves en une seule requête (au lieu d'un `_get_active_registry_entry` par cuve).

**Preuve de non-régression** : `tests/test_zylo_liquid_cash_price_batching.py` (nouveau fichier — aucun test de caisse n'existait avant cet audit, trou de couverture comblé). Trois tests, dont un test d'équivalence directe au niveau service : `_compute_tank_cash(..., price_context=None)` vs `_compute_tank_cash(..., price_context=<batché>)` sur le même scénario (changement de prix propre à la station + repli sur le prix réseau par défaut) — résultats vérifiés identiques champ par champ, y compris le détail par segment. Tous les tests passent.

**Mesuré** : `cash/network-summary` (aujourd'hui) 34,8s → 17,7s. (7 jours) 45-53s → 31,8s. Amélioration réelle mais incomplète — la mise en cache `TankCashDailyAggregate` (jours clos, périodes 7j/30j) reste interrogée par cuve×jour plutôt que par lot ; reste un axe d'optimisation identifié mais non traité dans cette phase (voir `benchmark.md`/`database-performance.md` pour le détail restant).

## 2. Backend — index composite manquant (axe 3.2)

Migration Alembic ajoutant `(hkSensorId, measuredAt DESC)` sur `TankMeasurement` — voir `database-performance.md` pour la confirmation `EXPLAIN ANALYZE` avant/après.

## 3. Backend — cache serveur léger (axe 3.3)

`app/shared/simple_cache.py` : TTL cache en mémoire (pas de nouvelle dépendance d'infrastructure), appliqué aux référentiels quasi statiques (produits carburant, villes, devises), invalidé explicitement à l'écriture. Voir `caching.md`/`cache-invalidation.md` pour le détail par type de donnée.

## 4. Frontend — adoption React Query (axe 3.4)

Migration de `useEffect`+`useState` vers `useQuery` pour les points d'entrée les plus visibles :
- `usePartData` (`PartState.tsx`, partagé par les onglets Pompes/Personnel/ATG de la fiche station) — **corrige directement le symptôme "je change d'onglet et ça recharge tout"**, la plainte initiale de l'utilisateur.
- `useNetworkDashboard.ts` (Dashboard), `useStationsList.ts` (page Stations), `useAlertsList.ts` (page Alertes).

Revue de correction indépendante effectuée (agent séparé) : aucune collision de clé de cache entre onglets/stations, conventions cohérentes avec les hooks déjà migrés (`useStationDetail.ts`/`useRegulation.ts`), `tsc`/`eslint` propres. Verdict : PASS.

## 5. Frontend — correction de risque de troncature silencieuse

`HistorySection.tsx` (journal d'audit d'une station) chargeait jusqu'à 100 lignes sans pagination réelle malgré un backend qui la supportait déjà (`meta.total`/`limit`/`offset`) et un composant `Pagination` déjà existant mais jamais câblé (`src/shared/ui/Pagination.tsx`). Corrigé — pagination réelle, 20 lignes par page. **Trouvaille annexe non corrigée dans cette phase** : la page Alertes dédiée (`useAlertsList.ts`) a le même défaut, backend déjà prêt, à traiter en suivi.

## 6. Ce qui reste ouvert (transmis aux phases suivantes / au backlog)

- Parallélisation des requêtes indépendantes au sein d'une même requête HTTP (actuellement séquentielles même quand batchées) — nécessite une étude séparée des sessions SQLAlchemy concurrentes (une session ne supporte pas les requêtes concurrentes ; il faudrait soit des sessions courtes séparées, soit accepter le séquentiel). Non tranché dans cette phase.
- Cache `TankCashDailyAggregate` non batché par lot (cuve×jour) — reste un aller-retour par cuve par jour clos, même en cas de cache-hit.
- Pagination de la page Alertes (voir §5).
- `pg_stat_statements` non installé sur Neon — dépend d'une action côté Neon (extension), pas seulement du code applicatif.
- Chargement progressif (skeletons, `loading.tsx`) sur Dashboard/Stations — en cours de finalisation en parallèle de la rédaction de ce document.
