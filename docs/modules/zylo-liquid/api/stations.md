# Endpoint 2 : stations (`stations`)

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

### Endpoint 2 — Stations (`stations`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.1.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/stations` | `zyloLiquid.station.manage` |
| GET | `/api/v1/zylo-liquid/stations` | `zyloLiquid.station.read` |
| GET | `/api/v1/zylo-liquid/stations/{id}` | `zyloLiquid.station.read` |
| PATCH | `/api/v1/zylo-liquid/stations/{id}` | `zyloLiquid.station.manage` |
| POST | `/api/v1/zylo-liquid/stations/{id}/deactivate` | `zyloLiquid.station.manage` |
| POST | `/api/v1/zylo-liquid/stations/{id}/reactivate` | `zyloLiquid.station.manage` |

Modèle `Station` déjà existant (Phase 1), déjà `organizationId`-scopé —
aucune extension de modèle nécessaire (§9.3 confirmé : réutiliser tel quel).
`GET /stations` inclut `activeTankCount` par station (compté via jointure
sur `Tank.active`, conforme au contrat Point 2 §1.1 "nombre de cuves
actives"). Statut modifiable uniquement via `deactivate`/`reactivate`,
jamais via `PATCH` (garde-fou de transition d'état, Point 2 §1.1).

Tests : `tests/test_zylo_liquid_stations.py` (8 cas). Ville inconnue du
référentiel géo Core → `city_not_found` (422). Isolation tenant stricte :
accès à une station d'une autre organisation → 404 `station_not_found`
(jamais 403, pour ne rien révéler de l'existence des données d'un autre
tenant, conforme à Point 2 §1.1). Preuve à 3 niveaux : `validation_log.md`.
