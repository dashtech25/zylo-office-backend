# Pagination — `limit: 100` comme risque de correction, pas seulement de performance

Date : 2026-09-11. Fait suite à `phase-1-audit.md` (problème #6, classé P0 — "risque de troncature silencieuse à l'échelle") et `phase-2-architecture-decision.md`.

## 1. Le constat

Phase 1 a compté **43 occurrences** de `limit: 100` côté frontend (`grep -rn "limit: 100" src/modules/zylo-liquid/`), sans pagination serveur réelle en face (pas de curseur, pas de "page suivante", pas de compte total renvoyé pour signaler une troncature). Au moment de ce document, le même grep sur l'état courant du dépôt frontend (avec le travail en cours d'une session parallèle, non lié à la pagination — adoption de React Query sur `useAlertsList.ts`, `useStationsList.ts`, `useNetworkDashboard.ts`, cf. §4) donne 46 occurrences dans 25 fichiers — l'écart vient de fichiers non comptés par le grep original ou de nouveaux appels (module GPS tracking en cours, `listCarriers`/`listTrucks`/`listGpsDevices` dans `zyloLiquidApi.ts`), pas d'une correction de la pagination elle-même.

## 2. Pourquoi c'est une question de correction, pas que de vitesse

Ce n'est **pas** un problème de latence qui dégrade progressivement l'expérience — c'est une troncature silencieuse. Dès qu'une organisation dépasse 100 lignes sur une de ces entités, les lignes au-delà de la 100e **disparaissent de l'écran sans aucune erreur, aucun indicateur "liste incomplète", aucun total affiché**. Un utilisateur consultant une liste de 150 alertes verra 100 alertes et croira avoir tout vu.

## 3. Entités les plus à risque (par cardinalité plausible)

Classées par probabilité de dépasser 100 lignes en croissance normale d'une organisation, sur la base des fichiers identifiés (`grep -rln "limit: 100" src/modules/zylo-liquid/`) :

| Entité | Fichier(s) | Pourquoi à risque en premier |
|---|---|---|
| Mesures/historique cuve (`HistorySection.tsx`) | `screens/station-admin/HistorySection.tsx` | Écriture continue (télémétrie Holykell, polling 5s côté ingestion) — volume déjà de 17,8K lignes en base à l'échelle actuelle (5 stations, 13 cuves) ; le plus haut débit d'écriture de toute l'application |
| Alertes | `screens/alerts/useAlertsList.ts` | Générées automatiquement par le système (seuils, structurelles) en plus des alertes manuelles — croissance continue, jamais purgée |
| Livraisons (`useDeliveriesList.ts`) | `screens/deliveries/useDeliveriesList.ts` | Une entrée par livraison carburant, récurrente par nature (hebdomadaire/mensuelle par station) |
| Équipements (`EquipmentSection.tsx`) | `screens/station-admin/EquipmentSection.tsx` | Croît avec le nombre de stations et le renouvellement de parc, mais plus lentement que les entités ci-dessus |
| Maintenance (`useMaintenance.ts`, `MaintenanceSection.tsx`) | `screens/maintenance/`, `screens/station-admin/MaintenanceSection.tsx` | Une entrée par intervention — récurrent, croissance continue |
| Fuites (`useLeakEventsList.ts`) | `screens/leaks/useLeakEventsList.ts` | Événementiel, fréquence a priori plus faible mais pas nulle |

Les autres occurrences (prix, produits, fournisseurs, personnel, rapports, quarts/shifts, régulation, réconciliation) ont une cardinalité plausiblement plus stable (bornée par le nombre de stations/employés/produits), donc un risque plus faible à court terme — mais toutes partagent le même défaut structurel : aucune ne signale une troncature.

## 4. Ce qui est en cours en parallèle (vérifié, pas de doublon)

Une session parallèle modifie actuellement `useAlertsList.ts`, `useStationsList.ts`, `useNetworkDashboard.ts` et `zyloLiquidApi.ts` (`git status` frontend, au moment de ce document) — vérification du diff (`git diff src/modules/zylo-liquid/screens/alerts/useAlertsList.ts`) confirme qu'il s'agit de l'adoption de React Query (axe Phase 2 §3.4 : remplacer `useEffect`/`useState` par `useQuery`), **pas** d'une correction de pagination — `limit: 100` reste inchangé dans ce diff. Aucun fichier `docs/architecture/performance/` autre que ceux listés ici ne mentionne la pagination à ce jour. La recommandation ci-dessous reste donc entièrement à implémenter.

## 5. Recommandation

Remplacer `limit: 100` fixe par une vraie pagination serveur, avec une stratégie différente selon le profil de l'entité :

- **Pagination par curseur** (recommandée pour les tables à forte écriture et croissance continue) : mesures/historique cuve, alertes, livraisons, maintenance. Un curseur (ex. `(measuredAt, id)` ou `(createdAt, id)`) reste stable même quand de nouvelles lignes s'insèrent pendant la pagination — contrairement à l'offset, qui décale ou duplique des résultats sous écriture concurrente. S'appuie directement sur l'index déjà posé aujourd'hui pour `TankMeasurement` (`(hkSensorId, measuredAt DESC)`, cf. `database-performance.md` §4).
- **Pagination par offset** (acceptable pour les entités plus petites/stables) : équipements, fournisseurs, personnel, produits, prix — volumes bornés par le nombre de stations/employés, coût de l'offset négligeable à cette échelle.

Dans tous les cas : le serveur doit renvoyer un indicateur explicite de troncature (ex. `hasMore` / curseur suivant, ou total compté) pour que le frontend puisse au minimum signaler "liste incomplète, charger plus" plutôt que de laisser croire que 100 lignes est la totalité.
