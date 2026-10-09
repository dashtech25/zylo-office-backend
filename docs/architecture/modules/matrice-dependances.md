# Matrice des dépendances autorisées et interdites

- **Source de vérité** : `.importlinter` (racine du dépôt backend). Ce document le résume ; en cas d'écart, `.importlinter` fait foi et ce document est corrigé.
- **Périmètre** : paquets de premier niveau sous `app/` (base `base-T004`, T-036).
- **Date** : 2026-10-09 (T-036).
- Les exceptions (imports tolérés malgré une règle) sont listées dans `exceptions-importlinter.md`.

## 1. Règles par famille

| Famille (source) | Peut dépendre de | Ne dépend jamais de | Contrat |
|---|---|---|---|
| `app/modules/zylo_liquid`, `app/modules/zylo_tanker` (métier) | `shared`, `core`, `identity`, `rbac`, `modules_registry`, `billing`, `audit`, et les capacités `files`, `location`, `alerts`, `integrations.holykell` (via leur service public) | `app.files.models`, `app.location.models`, `app.alerts.models` ; `identity` au-delà des `models` et `security` publics | `zylo-liquid-files-through-service-only`, `zylo-liquid-location-through-service-only`, `zylo-liquid-location-alerts-through-service-only`, `identity-rbac-not-reachable-from-internals` |
| `zylo_liquid` <-> `zylo_tanker` | rien l'un de l'autre | toute importation réciproque | `modules-metier-acyclic-siblings` |
| `app/files` (capacité) | `core`, `shared`, `rbac`, `audit`, `identity.models` | `app.modules.zylo_liquid` ; autres capacités | `files-never-imports-zylo-liquid`, `capabilities-never-import-each-other` |
| `app/location` (capacité) | `core`, `shared`, `rbac`, `identity.models`, `modules_registry.service` (guard d'activation) ; `zylo_liquid.models`/`permissions` et `zylo_tanker.models`/`permissions` (exception documentée) | `zylo_liquid.service/router/schemas`, `zylo_tanker.service/router/schemas`, `app.alerts` (hors événement) | `location-never-imports-zylo-liquid-or-zylo-tanker-logic`, `acyclic-location-zylo-liquid-tanker`, `capabilities-never-import-each-other` |
| `app/alerts` (capacité) | `core`, `shared`, `rbac`, `audit`, `identity.models` ; `zylo_liquid.models` et `zylo_tanker.models` (jointures de portée, exception documentée) | `zylo_liquid.service/router/schemas`, `zylo_tanker.service/router/schemas`, `app.location` | `alerts-never-imports-zylo-liquid-or-zylo-tanker-logic`, `acyclic-alerts-zylo-liquid-tanker`, `alerts-models-no-zylo-liquid-location-import` |
| `app/alerts/models.py` | `core`, `shared` seulement (FK résolues par nom de table) | tout module métier et `location` | `alerts-models-no-zylo-liquid-location-import` |
| `app/integrations/holykell` | `core`, `shared` | `app.modules.zylo_liquid` | `holykell-never-imports-zylo-liquid` |
| `app/notifications` (capacité, snapshot wip uniquement) | `core`, `shared`, `identity.models`, `rbac`, événements (`app.shared.events`) | `app.modules.zylo_liquid` (voir exceptions, contrat à poser en T-004b) | à poser (`exceptions-importlinter.md` §3) |
| Socle : `core`, `shared`, `identity`, `rbac`, `audit`, `billing`, `auth`, `modules_registry` | ne dépend d'un module métier qu'à travers le registre de seeders (cible) | `app.modules.*` (sauf `modules_registry`, exception) | `modules_registry` : `ignore_imports` ARC-008 ; autres règles du socle **non contractées** (ARC-009) |
| `app/api/v1`, `app/main.py` (racine de composition) | tout | rien ne dépend de la racine | aucun contrat (point d'assemblage) |

## 2. Cycles entre paquets de premier niveau

Principe : un cycle entre deux paquets est interdit sauf si la dépendance dans un sens est une exception documentée. Le type `acyclic_siblings` ne couvre que des paquets frères (ici `app.modules.*`). Pour les autres paires, on utilise un contrat `forbidden` dans le sens **capacité -> module** (interdit par `CLAUDE.md`), la direction **module -> capacité** restant autorisée.

| Paire | État base-T004 | Traitement |
|---|---|---|
| `zylo_liquid` <-> `zylo_tanker` | aucun cycle | `modules-metier-acyclic-siblings` (KEPT) |
| `alerts` -> `zylo_liquid` / `zylo_tanker` (et retour via `zylo_liquid.service` -> `alerts.service`) | cycle, ARC-005 | `acyclic-alerts-zylo-liquid-tanker` ; 2 exceptions de jointure + 2 chaînes par le socle |
| `location` -> `zylo_liquid` / `zylo_tanker` (retour par les `permissions` seedées) | cycle, ARC-005/006 | `acyclic-location-zylo-liquid-tanker` ; 2 exceptions de types + 2 chaînes par le socle |
| `modules_registry` -> `zylo_liquid` / `zylo_tanker` (retour par les routeurs) | cycle, ARC-008 | `ignore_imports` existant (registre de seeders à faire) |
| `core` <-> `identity`, `identity` <-> `rbac`, `rbac` <-> `shared`, etc. | cycles du socle, ARC-009 | **hors T-036** : non contractés, dette documentée |

## 3. Ce qui n'est pas autorisé, en une phrase

Une capacité partagée (`files`, `location`, `alerts`, `integrations/holykell`) ne lit jamais le modèle ni le service d'un module métier, et un module métier ne lit jamais les tables d'une capacité : il passe par le `service.py` public de la capacité.
