# Phase 2 — Comparaison d'architectures et décision

Date : 2026-09-11. Fait suite à `phase-1-audit.md` (15 problèmes classés P0-P3, preuves mesurées).

## 1. Objectif de la phase

Comparer les architectures candidates (A à E) pour résoudre durablement les causes identifiées en Phase 1, et choisir — avec justification, pas par défaut ni par mode.

## 2. Architectures comparées

| # | Architecture | Résout le N+1/latence SQL ? | Résout le refetch au changement d'onglet ? | Nouvelle infra ? | Verdict |
|---|---|---|---|---|---|
| A | Fetch classique (état actuel) | Non | Non | — | Rejetée (cause du problème) |
| B | API + cache client seul | Non | Oui | Non (React Query déjà installé) | Insuffisante seule — le backend resterait lent au premier chargement de chaque page |
| C | Cache serveur (Redis) + cache client | Oui (masque la lenteur) | Oui | **Oui (Redis)** | Rejetée pour l'instant — masque le symptôme sans corriger la cause (le N+1 reste, juste moins souvent exécuté), et ajoute une dépendance d'infrastructure sans preuve qu'elle soit nécessaire à l'échelle actuelle (5 stations, 13 cuves, 17 8K mesures) |
| D | Chargement progressif seul | Non | Non | Non | Nécessaire mais pas suffisante seule — améliore le perçu, pas le réel |
| E | Hybride (voir §3) | **Oui** | **Oui** | Non | **Retenue** |

## 3. Décision : Architecture E (hybride), composée de 5 éléments

Ordre de priorité respecté (règle de la mission, §30) : performance réelle > stabilité > scalabilité > simplicité > maintenabilité > observabilité > coût > sophistication. Chaque élément est justifié individuellement — aucun choisi par mode.

### 3.1 Réduction du nombre de requêtes SQL (la vraie cause, cf. Phase 1 §2.1)
Regroupement des requêtes par lot (`IN (...)`) au lieu d'une par cuve/station, résolution des prix/devises en mémoire à partir de données déjà chargées plutôt que re-résolues à chaque frontière. **Implémenté aujourd'hui** pour `network/summary`, `station/current-state` et l'intégralité du moteur de caisse (`get_network_cash_summary`, `get_station_cash_detail`) — voir `phase-3-implementation.md` pour le détail et les mesures avant/après.

### 3.2 Index composite manquant
`(hkSensorId, measuredAt DESC)` sur `TankMeasurement` — preuve `EXPLAIN ANALYZE` en Phase 1 (17 473 lignes filtrées sur 17 636). Sans coût de complexité, sans nouvelle dépendance — juste une migration Alembic.

### 3.3 Cache serveur léger, en mémoire, sans nouvelle infrastructure
Pour les données quasi statiques (produits carburant, villes, devises) : un cache TTL en mémoire du processus (pas Redis — aucune preuve qu'un cache partagé entre workers soit nécessaire à cette échelle ; si l'app tourne un jour sur plusieurs workers/instances, ce choix sera à revisiter, documenté comme limite connue en §8). Invalidé explicitement à l'écriture — jamais une donnée périmée servie après une modification dans le même processus.

### 3.4 Adoption de React Query partout (cache client)
L'infrastructure existe déjà (`QueryProvider.tsx`, config saine : `staleTime: 60s`, `gcTime: 10min`). Le trou était l'adoption (4 hooks sur 45), pas l'outil. Priorité aux hooks qui causent le symptôme le plus visible : `usePartData` (partagé par les onglets Pompes/Personnel/ATG de la fiche station — la cause directe du "je change d'onglet et ça recharge tout"), puis Dashboard, Stations, Alertes.

### 3.5 Rendu progressif par widget
Pas de refonte Suspense/Server Components à ce stade (aucun composant serveur ne fetch de données actuellement — migrer serait un chantier séparé, plus risqué, à ne considérer que si le cache client+serveur ne suffit pas). À la place : garder chaque widget de dashboard indépendant dans son fetch (déjà largement le cas structurellement), et s'assurer qu'aucun état `loading` global ne bloque tout un écran quand une seule section est concernée — règle à faire respecter dans `developer-guide.md`, pas un chantier de réécriture immédiat.

## 4. Ce qui N'est PAS fait, et pourquoi

- **Pas de WebSocket/SSE** : l'ingestion télémétrie arrive déjà par polling 5s (`sync_holykell_live.py`), et aucun écran actuel n'affiche de promesse de fraîcheur sub-5s. Introduire du push serait de la sophistication sans besoin prouvé (règle §30 : ne jamais choisir une techno parce qu'elle est moderne). À revisiter si un écran "temps réel" explicite est demandé.
- **Pas de Redis** : voir §3.3.
- **Pas de partitionnement `TankMeasurement` immédiat** : à 17,8K lignes, l'index composite (§3.2) suffit. Le partitionnement mensuel documenté dans le modèle (jamais implémenté) reste un P3 — à traiter avant que le volume réel n'atteigne l'échelle où un index seul ne suffit plus (estimation : plusieurs millions de lignes, à surveiller via `pg_stat_statements` une fois installé, cf. `observability.md`).
- **Pas de Server Components pour le fetch** : chantier de réécriture architecturale plus large, avec un gain incertain tant que le vrai goulot (SQL) n'est pas éliminé. À reconsidérer seulement après mesure que les 4 axes ci-dessus ne suffisent pas.

## 5. Résultat

Architecture cible choisie et justifiée : hybride E, 5 axes, aucune nouvelle dépendance d'infrastructure. Implémentation en cours (voir `phase-3-implementation.md`).

## 6. Livrable

Ce fichier : `docs/architecture/performance/phase-2-architecture-decision.md`.
