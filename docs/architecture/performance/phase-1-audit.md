# Phase 1 — Audit de l'architecture de performance (observation seule)

Date : 2026-09-11
Périmètre : Zylo Office / module Zylo Liquid, frontend (`zylo-office-frontend`) + backend (`zylo-office-backend`) + base Neon Postgres.
Méthode : mesures réelles (EXPLAIN ANALYZE, chronométrage HTTP, lecture de code avec citations fichier:ligne) — aucune supposition non vérifiée. Aucune correction appliquée pendant cette phase.

---

## 1. Objectif de la phase

Cartographier précisément le chemin de la donnée sur les parcours critiques (Dashboard, Stations, détail station + onglets, Alertes, Caisse) — frontend → fetch → cache → API → service → ORM → SQL → Postgres — et identifier, avec preuves, où le temps est réellement perdu et comment ce coût va évoluer avec la croissance des données.

## 2. Analyse réalisée

### 2.1 Backend / Base de données (mesuré directement)

- Connexion TCP/SSL initiale vers Neon (Frankfurt, `eu-central-1`) : **~1,2 s**. Un `SELECT 1` isolé, hors toute logique applicative : **130–270 ms**. C'est le plancher de latence par requête, quel que soit le code — en partie une question de topologie réseau (l'environnement de dev n'est pas co-localisé avec Neon), pas uniquement de code.
- `GET /zylo-liquid/network/summary` : **27,4 s** avant correctif partiel appliqué aujourd'hui → **5,3–8,1 s** après (mesures avec/sans contention). Cause : `get_tank_current_state()` faisait jusqu'à **8 requêtes séquentielles par cuve** (capteur niveau produit, calibration, capteur eau, capteur température, produit carburant, prix station, prix réseau par défaut avec sa propre chaîne station→ville→région→pays→devise, devise). Avec 13 cuves : ~65-100 allers-retours séquentiels × ~200 ms.
- `GET /zylo-liquid/cash/network-summary` (aujourd'hui) : **34,8–37,9 s**. `GET .../cash/network-summary` (7 jours) : **45–53 s**. `GET .../cash/network-summary` (30 jours) : **timeout (>60 s)**. Cause identifiée dans le code (non corrigée) : `_price_sub_segments_for_sale_window` (service.py ~L3044) rappelle `_resolve_applicable_price` — la chaîne complète de résolution prix/devise (jusqu'à 6 requêtes) — **à chaque frontière de segment de vente, pour chaque cuve, pour chaque jour de la période demandée**. Sur 7-30 jours, ce coût se multiplie par le nombre de jours.
- **Aucun cache serveur nulle part** : `grep` sur `Cache-Control`, `lru_cache`, `redis`/`Redis`, `cachetools` dans `app/` → 0 résultat. Chaque requête recalcule tout depuis zéro, y compris des données quasi statiques (produits carburant, villes, devises, config organisation).
- **Index manquant, prouvé par `EXPLAIN ANALYZE`** : la requête "dernière mesure connue avant un instant, pour un capteur" (`TankMeasurement` filtrée par `hkSensorId`, triée par `measuredAt`) utilise l'index sur `measuredAt` seul et **filtre `hkSensorId` après coup** : `Rows Removed by Filter: 17473` sur 17 636 lignes totales — quasiment un balayage complet de la table pour trouver 1 ligne, déjà à ce volume modeste. Il manque un index composite `(hkSensorId, measuredAt DESC)`. Le modèle documente lui-même (commentaire `TankMeasurement`, models.py L133-141) que le schéma source partitionne cette table par mois — jamais reproduit ici.
- `pg_stat_statements` **non installé** sur cette instance Neon — aucune visibilité agrégée sur les requêtes les plus coûteuses en conditions réelles (trou d'observabilité, cf. §26 de la mission).
- `ENVIRONMENT=development` → `echo=True` sur SQLAlchemy (`app/core/database.py:18`) : chaque requête est journalisée deux fois (texte + JSON), synchrone sur disque — surcharge réelle mais secondaire.
- `pool_size=20, max_overflow=20` (déjà ajusté aujourd'hui par une autre session, commentaire daté 2026-09-11 dans `database.py`) — mesure montre que ce n'était pas la cause principale : même avec un pool large, chaque requête individuelle reste lente à cause du nombre d'allers-retours, pas d'un manque de connexions.
- **43 occurrences de `limit: 100`** côté frontend (liste ci-dessous, §2.2) sans pagination serveur réelle en face — pas seulement un problème de performance : au-delà de 100 lignes par organisation sur n'importe laquelle de ces entités (logs d'audit, alertes, équipements, déclarations...), les données seront **silencieusement tronquées**, jamais signalées comme incomplètes.

### 2.2 Frontend (audité par sous-agent, vérifié par citations fichier:ligne)

- **React Query réellement utilisé : 4 fichiers sur ~45** hooks de fetching (`useStationDetail.ts`, `useRegulation.ts`, `useDeliveryFlow.ts`, `useSuppliers.ts` — tous dans `station-detail/`). Partout ailleurs : `useEffect` + `useState` local, un seul booléen `loading` qui bloque tout le rendu de la page. Config React Query elle-même saine (`QueryProvider.tsx:36-52` : `staleTime: 60s`, `gcTime: 10min`, `refetchOnWindowFocus: true`) — le problème est l'adoption, pas la configuration.
- **Remount d'onglet confirmé** : `StationDetailScreen.tsx` utilise les `Tabs` Radix (`shared/ui/Tabs.tsx`), qui démontent le contenu inactif par défaut (pas de `forceMount`) — déjà documenté dans un commentaire du code lui-même (`PartState.tsx:27-29`). Résultat mesuré dans le code : changer d'onglet Aperçu → Pompes → Aperçu redéclenche `usePartData`'s `useEffect` à chaque fois pour Pompes/Personnel/ATG (`PumpsTab.tsx:28`, `StaffTab.tsx:20`, `AtgTab.tsx:63`) — spinner plein écran à chaque retour. Seul l'onglet Réglementation est épargné (React Query).
- **Cascades séquentielles non parallélisées** dans les hooks les plus lourds : `useStationsList.ts:90-107` (3 étapes séquentielles), `useNetworkDashboard.ts:116-133` (2 étapes), `useStationDetail.ts:44-52` (3 étapes, la dernière même pas parallélisée avec le lot précédent).
- **Aucun Server Component ne fetch de données** : toutes les 81 pages `app/zylo-liquid/*/page.tsx` sont de simples ré-exports de composants `"use client"`. **Aucun `loading.tsx`** nulle part sous `src/app/zylo-liquid/` — pas de Suspense, pas de streaming, juste le spinner client. **Aucun `router.prefetch()`** dans tout le code.
- Caisse (`CaisseScreen.tsx:47,59,75`) appelle `useNetworkCash` **3 fois** (principal, comparaison hier, moyenne 7 jours) — 3 fetches indépendants et non cachés de données largement superposées.

## 3. Problèmes détectés (classés)

| # | Problème | Niveau | Preuve |
|---|---|---|---|
| 1 | N+1 séquentiel sur `current-state`/`network summary` | **P0** | Mesuré 27,4s → corrigé partiellement aujourd'hui (5,3-8,1s) |
| 2 | Résolution prix/devise complète répétée à chaque frontière de segment de vente, par cuve, par jour (Caisse) | **P0** | Code lu, `_price_sub_segments_for_sale_window` service.py ~L3044 ; mesuré 35-53s / timeout, non corrigé |
| 3 | Aucun cache serveur | **P0** | `grep` négatif sur tout `app/` |
| 4 | 4/45 hooks frontend cachés ; remount d'onglet = refetch complet | **P0** | Audit fichier:ligne ci-dessus |
| 5 | Index manquant `(hkSensorId, measuredAt DESC)` sur `TankMeasurement` | **P0** (impact futur catastrophique) | `EXPLAIN ANALYZE` : 17 473 lignes filtrées sur 17 636 |
| 6 | `limit: 100` × 43 sans pagination réelle | **P0** (risque de troncature silencieuse à l'échelle) | `grep` sur le frontend |
| 7 | Cascades séquentielles non parallélisées (3 hooks lourds) | **P1** | `useStationsList.ts`, `useNetworkDashboard.ts`, `useStationDetail.ts` |
| 8 | `echo=True` (double logging SQL synchrone) | **P1** | `database.py:18`, `ENVIRONMENT=development` |
| 9 | Aucun `loading.tsx`/Suspense — page bloquée en tout-ou-rien | **P1** | `find` négatif |
| 10 | Aucun `router.prefetch()` | **P1** | `grep` négatif |
| 11 | Latence plancher Neon ~130-270ms/requête (partiellement infra) | **P1** | Mesuré directement (asyncpg) |
| 12 | `pg_stat_statements` non installé | **P2** | Vérifié sur l'instance |
| 13 | Cache `TankCashDailyAggregate` lui-même interrogé par cuve×jour, pas batché | **P2** | Lecture de `_get_or_compute_tank_cash_for_day` |
| 14 | Pas de partitionnement/downsampling `TankMeasurement` malgré doc l'exigeant | **P3** | Commentaire du modèle lui-même, jamais implémenté |
| 15 | Pas de stratégie temps réel définie (polling/SSE/WebSocket) | **P3** | Aucun mécanisme présent, à concevoir avant que le besoin ne devienne pressant |

## 4. Décisions possibles pour la suite

Pas encore tranchées — c'est l'objet des phases suivantes. Deux axes se dessinent déjà clairement à partir des preuves :

- **Réduire le nombre d'allers-retours DB** (regroupement de requêtes, résolution en mémoire des prix déjà chargés) plutôt que d'ajouter du cache pour masquer la lenteur — déjà amorcé aujourd'hui côté stock (Phase implémentation précédente), à terminer côté Caisse.
- **Adopter React Query partout** plutôt qu'ajouter une solution de cache concurrente — l'infrastructure existe déjà et sa config est saine ; le travail restant est l'adoption, pas le choix d'outil.

Ces deux axes ne s'excluent pas — ils s'additionnent (moins de requêtes ET moins souvent).

## 5. Implications

- Le problème n'est pas la bande passante internet de l'utilisateur (confirmé par les mesures : le goulot est le nombre d'allers-retours séquentiels vers une base distante, pas le volume de données transférées).
- À la volumétrie actuelle (13 cuves, 17,8K mesures), les symptômes sont déjà sévères. Sans intervention, l'aggravation sera **plus que linéaire** : le N+1 scale avec le nombre de cuves, l'absence d'index scale avec le volume de télémétrie, et les deux se multiplient avec la durée des périodes demandées (Caisse 7j/30j).
- Le `limit: 100` n'est pas qu'une question de vitesse : au prochain palier de croissance, des données vont disparaître silencieusement des listes sans qu'aucune erreur ne soit levée.

## 6. Résultat

Cartographie complète établie, avec preuves mesurées à chaque niveau (frontend, API, ORM, SQL, Postgres). 15 problèmes identifiés et classés P0-P3. Aucune correction supplémentaire appliquée pendant cette phase, conformément à la consigne.

## 7. Livrable

Ce fichier : `docs/architecture/performance/phase-1-audit.md`.
