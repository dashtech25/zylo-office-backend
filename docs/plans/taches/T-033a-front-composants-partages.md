# T-033a : Frontend : composants partagés (Table, Tabs, Modal, QueryState, graphiques)

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-033a-partages` · **Base de test** : `zylo_t033a_test` · **Ports** : back 3133, front dev 3233, front prod 3333
- **Dépendances** : T-030, T-032
- **Décisions requises** : `frontend/bibliotheque-graphiques.md` (recommandation : ECharts)

## Objectif
Un `Table`, un composant de tendance, `Tabs`, `Modal` et `QueryState` (chargement, erreur avec réessai, vide) partagés, utilisés à la place des variantes locales. Les trois graphiques convergent vers une bibliothèque de référence.

## Problèmes résolus
- FRT-005 (P2, tableaux bruts), FRT-006 (P2, trois graphiques), FRT-014 (remplacé par le catalogue), ARC-011 (P2), ARC-012 (P2, `TrucksMap` importé par un autre module)

## Dépendances : justification
- T-030 : coquille unique.
- T-032 : tokens utilisés par les composants partagés.
- Retirées (confort ou CI, pas de prérequis technique) : T-042 (confort : tests unitaires) ; T-043 (confort : catalogue mis à jour en parallèle).

## Fichiers / modules concernés
- `src/shared/ui/Table.tsx`, `Tabs.tsx`, `Modal.tsx`, `QueryState.tsx` (créé)
- `src/modules/zylo-liquid/components/TrendChart.tsx`, `dashboard/DashboardStockTrendChart.tsx`, `src/modules/zylo-tanker/components/EChartsTrendChart.tsx`
- `TrucksMap` déplacé dans `src/shared/` (sortie de `zylo-tanker`)

## Stratégie
1. Ajouter les variantes à `shared/ui` avant de migrer les usages (pas de duplication).
2. Migrer par module, un écran par commit.
3. Tableaux bruts : liste des exemptions dans l'annexe de la fiche (nom de fichier et raison) ; contrôle `grep -rl "<table" src | grep -v shared/ui` échoue hors liste.
4. Mettre à jour le catalogue (T-043) pour chaque composant créé ou déplacé.

## Tests attendus
- Unitaires : composants partagés (`test:unit`), logique de `QueryState`.
- Playwright prod : écrans migrés, rendu inchangé sur les captures de référence.
- Contrôle `<table` : liste vide hors exemptions.

## Critères d'acceptation
- Aucun `<table>` brut hors `shared/ui` hors liste d'exemptions datée.
- Catalogue à jour (contrôle de T-043 vert).
- Un seul graphique de référence (ECharts ou décision contraire écrite).

## Risque et retour arrière
Moyen : remplacement dans de nombreux écrans. Retour arrière : écran par écran.

## Livrable documentaire
- `docs/architecture/frontend/composants-partages.md` (créé)
- `docs/questions/frontend/bibliotheque-graphiques.md`

## Parallélisable avec
T-033b et T-033c après leur chaîne (T-033b puis T-033c).
