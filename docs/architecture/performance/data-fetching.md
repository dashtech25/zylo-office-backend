# Data fetching — Zylo Liquid (Next.js 15 App Router)

Date : 2026-09-11. Fait suite à `phase-1-audit.md` et `phase-2-architecture-decision.md`.
Périmètre : `zylo-office-frontend`, module `src/modules/zylo-liquid/`.

## 1. Pas de fetch côté Server Component

Toutes les pages sous `src/app/zylo-liquid/*/page.tsx` sont de simples ré-exports de composants
`"use client"` (vérifié en Phase 1, §2.2). Aucun Server Component ne fetch de données, aucun
`loading.tsx`, aucun Suspense/streaming.

Ce n'est **pas une architecture choisie** — c'est une limite connue, documentée explicitement en
Phase 2 comme non traitée volontairement : `phase-2-architecture-decision.md` §4, dernier point —
« chantier de réécriture architecturale plus large, avec un gain incertain tant que le vrai goulot
(SQL) n'est pas éliminé. À reconsidérer seulement après mesure que les 4 [5] axes [de l'architecture
hybride] ne suffisent pas. » Autrement dit : le fetch dépend intégralement du client tant que rien
ne prouve que ça devienne le facteur limitant après correction du SQL et adoption de React Query.

## 2. Le pattern React Query établi

Référence : `src/modules/zylo-liquid/screens/station-detail/useStationDetail.ts` et
`src/modules/zylo-liquid/hooks/useNetworkDashboard.ts`.

- **Clé de requête** : un tableau hiérarchique, toujours préfixé `["zylo-liquid", <domaine>, ...]`,
  puis `organizationId` (et `stationId` quand pertinent) en derniers segments — pour que React Query
  distingue naturellement les caches par organisation/station sans logique d'invalidation manuelle.
  Exemples réels :
  - `["zylo-liquid", "station-detail", organizationId, stationId]` (`useStationDetail.ts:75`)
  - `["zylo-liquid", "network-dashboard", "base", organizationId]` (`useNetworkDashboard.ts:167`)
  - `["zylo-liquid", "network-dashboard", "station-states", organizationId, activeStationIds]` (`useNetworkDashboard.ts:176`)
  - `["zylo-liquid", "alerts-list", organizationId, statusFilter, typeFilter, scope.stationId, scope.tankId]` (`useAlertsList.ts:75`)
- **`organizationId`** : gardé optionnel côté hook (`string | null`), la requête est désactivée via
  `enabled: !!organizationId` tant qu'il n'est pas résolu (`useStationDetail.ts:76`) — pas de fetch
  avec un id vide.
- **`loading`/`error` dérivés, jamais stockés en state local** : `loading: !!organizationId &&
  query.isPending`, `error` reconstruit depuis `query.error` (`Error` ou valeur brute convertie en
  string) — voir `useStationDetail.ts:80-85`. Le hook garde l'API historique (`{ loading, error,
  ...data }`) pour ne pas casser les composants appelants pendant la migration.
- **Un seul `queryFn` async par écran, qui parallélise en interne** via `Promise.all` (ex.
  `fetchStationDetail`, `fetchNetworkBase`) plutôt que plusieurs `useQuery` séquentiels.
- **`usePartData`** (`src/modules/zylo-liquid/screens/station-detail/PartState.tsx:40`) est un
  wrapper générique autour de `useQuery` utilisé par les onglets de fiche station (Pompes, Personnel,
  ATG) — c'est le correctif direct du problème #4 de Phase 1 (remount d'onglet = refetch complet).

## 3. Adoption mesurée aujourd'hui

Phase 1 mesurait **4 fichiers sur ~45** en React Query. État actuel (grep `useQuery(` vs
`useEffect(` sous `src/modules/zylo-liquid/`, 2026-09-11) :

- **En React Query (8)** : `useNetworkDashboard.ts`, `useAlertsList.ts`, `useStationsList.ts`,
  `useStationDetail.ts`, `useRegulation.ts`, `useDeliveryFlow.ts`, `useSuppliers.ts`, `useTrucks.ts`
  — plus `PartState.tsx` (`usePartData`, partagé par les onglets Pompes/Personnel/ATG).
- **Encore en `useEffect` + `useState` (22)**, dont : `useCashData.ts` (Caisse), `usePompisteDashboard.ts`,
  `useReportsData.ts`, `useReconciliation.ts`, `useMaintenance.ts`, `useVentes.ts`,
  `useTanksNetwork.ts`, `useTankDetail.ts`, `useStationTrends.ts`, `useExploitation.ts`,
  `useDeliveriesList.ts`, `useDeliveriesInProgress.ts`, `useDeliveryMeasurements.ts`,
  `useLeakEventsList.ts`, `useCaisseEcarts.ts`, `useCredit.ts`, `useApprovisionnement.ts`,
  `useFuelCatalog.ts`, `usePrices.ts`, `useStationFuelProducts.ts`, `useProduits.ts`,
  `useReglementaire.ts`, `useShifts.ts`, `useHolykellSyncStatus.ts` (celui-ci est un polling de
  statut, pas un fetch de page — candidat moins prioritaire).

Priorité de migration (Phase 2 §3.4) : Dashboard, Stations, Alertes — déjà faits — puis les écrans
restants au fil de l'eau, en particulier Caisse (`useCashData.ts`, cause du triple-fetch documenté
en Phase 1 §2.2).

## 4. Ce que ça implique

- Chaque écran encore en `useEffect` a son propre `loading` booléen qui bloque tout le rendu, et
  refetch intégralement à chaque montage (retour d'onglet inclus) — jusqu'à sa migration.
- Migrer un hook = remplacer `useEffect`+`useState` par un seul `useQuery` avec une `queryFn` qui
  parallélise les appels internes, en suivant le même schéma de clé que ci-dessus. Pas de nouvel
  outil, pas de config à changer côté `QueryProvider` (voir `caching.md`).
