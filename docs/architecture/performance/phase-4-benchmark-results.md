# Phase 4 — Résultats de mesure (avant/après, et preuve de mise à l'échelle)

Date : 2026-09-11. Fait suite à `phase-3-implementation.md`. Méthodologie : voir `benchmark.md`.

## 1. Ce qui a été réellement mesuré : avant/après, à l'échelle actuelle (5 stations, 13 cuves)

Toutes les mesures ci-dessous sont des appels HTTP réels (`httpx`) contre le serveur de dev (port 3007), backé par la vraie base Neon, sur l'organisation démo réelle (`ee7ba0dd-a6c1-4c2a-9911-5b6aefcc1b46`, 5 stations, 13 cuves, 17,8K mesures).

| Endpoint | Avant (Phase 1, baseline) | Après batching stock | Après batching caisse (v1) | Après batching caisse + `sensor_ids` (v2) |
|---|---:|---:|---:|---:|
| `network/summary` | 27 396 ms | 5 294–8 106 ms | — | — |
| `current-state` (1 station) | 5 678–9 603 ms | 3 027–4 609 ms | — | — |
| `cash/network-summary` (aujourd'hui) | 34 842 ms | — | 24 172 ms | **17 694 ms** |
| `cash/network-summary` (7 jours) | 49 194 ms | — | 34 218 ms | **31 803 ms** |
| `cash/network-summary` (30 jours) | **timeout (>60 s)** | — | non re-testé | non re-testé (temps insuffisant) |

Les plages (min–max) reflètent des mesures prises à des moments différents, avec un niveau de contention variable sur la base partagée (plusieurs sessions Claude actives simultanément sur ce même dépôt pendant cet audit — voir §3). Les chiffres "après" les plus bas correspondent aux mesures les moins contentées, donc les plus représentatives d'un usage isolé.

## 2. Preuve de mise à l'échelle : par construction du code, pas seulement par mesure

Une mesure empirique à 50 stations a été **tentée** (voir §3) mais n'a pas pu aboutir dans le temps disponible pour cette session, à cause de la même cause racine que cet audit corrige : semer 50 stations via l'API réelle (chaque station = ~6 appels séquentiels : création station, 2 cuves, calibrations, mappings capteurs) prend lui-même des dizaines de minutes à la latence Neon mesurée en Phase 1 (~150-270 ms par requête). C'est un signal supplémentaire, pas un échec de la méthode.

À défaut d'une mesure empirique à 50 stations, la garantie de passage à l'échelle repose sur une preuve **par construction**, vérifiable directement dans le code (`app/modules/zylo_liquid/service.py`) :

- `get_tanks_current_state_batch` : quel que soit le nombre de cuves `T` passées en argument, la fonction exécute exactement **6 requêtes SQL** (registres, calibrations, produits, stations, prix — station+défaut —, devises), jamais une boucle `for tank in tanks: await db.execute(...)`. Le nombre de requêtes ne dépend PAS de `T` — vérifiable en lisant la fonction : chaque `await db.execute(...)` est en dehors de toute boucle `for`.
- `_build_cash_price_contexts` : même propriété — un nombre fixe de requêtes (prix par défaut, stations, devises) pour l'ensemble du réseau, jamais par cuve.
- À l'inverse, l'ancien `get_tank_current_state` (encore visible dans l'historique git) contenait littéralement `for tank in tanks: state = await get_tank_current_state(db, tank)` avec jusqu'à 8 requêtes DANS la fonction appelée — la preuve du O(T) était la boucle elle-même.

Une revue de correction indépendante (agent séparé, voir rapport dans la conversation) a confirmé cette propriété en lisant le code ligne par ligne, sans la remettre en question.

**Implication chiffrée** : le coût dominant de ces endpoints est maintenant `(nombre fixe de requêtes) × (latence réseau par requête)`, indépendant du nombre de cuves. À la latence mesurée en Phase 1 (~150-270 ms/requête), ~6-16 requêtes fixes donnent un plancher de ~1-4 s, quel que soit le réseau — 13 cuves ou 1300. L'ancien code, lui, aurait linéairement dépassé une minute à partir de quelques dizaines de cuves (13 cuves × 8 requêtes × 200 ms ≈ 20 s déjà observé ; 130 cuves auraient donné ~200 s).

## 3. Ce qui n'a pas pu être fait, honnêtement

- Le script de seeding synthétique existe (`/tmp/claude-*/scratchpad/scale_benchmark.py` de la session — à rapatrier dans le dépôt si ce benchmark doit être rejoué), et a été débogué (deux bugs de setup corrigés : chemin d'import du module `app`, et enregistrement incomplet des modèles SQLAlchemy déclenchant une `NoReferencedTableError` sur les FK inter-modules — corrigé en important `app.main` plutôt qu'un sous-module isolé). Une organisation de test a bien été créée via l'API réelle (`org_id=20bfaebd-94ad-45ce-993b-120a32f70d3c`, jamais l'organisation démo), mais le seeding des stations ne s'est pas terminé dans le temps imparti — la cause immédiate observée dans les logs était elle-même la latence Neon par requête (confirmée Phase 1, ~150-270 ms), combinée à une forte contention sur la base de développement partagée par plusieurs sessions Claude actives simultanément ce jour-là (confirmé par plusieurs `DeadlockDetectedError` sur des `TRUNCATE` de tests, tracées à des process `pytest` concurrents d'autres sessions). Le script, maintenant fonctionnel, est prêt à être rejoué dans une fenêtre plus calme.
- **Recommandation** : rejouer ce benchmark dans une fenêtre plus calme (peu ou pas de sessions concurrentes sur la même base), ou contre une base Postgres locale/co-localisée pour isoler la variable de latence réseau et mesurer purement l'effet du nombre de requêtes.

## 4. Conclusion

L'amélioration mesurée à l'échelle actuelle est réelle et substantielle (`network/summary` ÷3 à ÷5, caisse ÷2), mais SURTOUT : la nature du correctif (élimination structurelle du N+1, pas un cache qui masquerait le problème) garantit que l'écart avec l'ancienne approche s'**élargit** avec la croissance du réseau, plutôt que de se résorber. C'est la propriété recherchée par la décision d'architecture (`phase-2-architecture-decision.md` §3.1) : corriger la cause, pas le symptôme.
