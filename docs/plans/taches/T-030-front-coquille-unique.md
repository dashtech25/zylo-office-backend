# T-030 : Frontend : une seule coquille de navigation (ModuleShell et CoreProviders)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-030-coquille-unique` · **Base de test** : `zylo_t030_test` · **Ports** : back 3130, front dev 3230, front prod 3330
- **Dépendances** : T-008, T-011, T-042
- **Décisions requises** : aucune

## Objectif
Trois coquilles (`AppShell`, `ZyloLiquidShell`, `ZyloTankerShell`) réécrivent la sidebar, l'en-tête, le menu mobile et la déconnexion. Les fusionner en un `ModuleShell` paramétré par une configuration de navigation. La pile de providers devient `CoreProviders`, utilisée par tous les layouts.

## Problèmes résolus
- FRT-002 (P1), FRT-016 (P2, menu mobile), FRT-021 (P3), FRT-015 (partie : tanker sans providers)

## Dépendances : justification
T-008 (parcours prod pour valider la navigation), T-011 (routes nettoyées), T-042 (tests unitaires de la configuration de navigation). Bloque T-031, T-032 et T-033a.

## Fichiers / modules concernés
- `src/core/layout/ModuleShell.tsx`, `src/core/layout/CoreProviders.tsx` (créés)
- `src/core/layout/AppShell.tsx` (supprimé en fin de migration)
- `src/modules/zylo-liquid/components/ZyloLiquidShell.tsx`, `src/modules/zylo-tanker/components/ZyloTankerShell.tsx` (configuration seulement)
- `src/app/(app)/layout.tsx`, `src/app/zylo-liquid/layout.tsx`, `src/app/zylo-tanker/layout.tsx`

## Stratégie
1. Capture de référence avant migration (tableau de bord, une station, une cuve, un écran tanker, critère de sortie REV-D-30) : non produite, Playwright suspendu (voir `docs/process/decision-playwright-suspendu.md`).
2. `ModuleShell` écrit à côté des trois coquilles, puis migrée une coquille après l'autre (pas de flag de production).
3. Menu mobile : fermeture à la touche Échap (FRT-012 : focus traité par T-033c).
4. Les composants de navigation n'appellent pas `fetch`. Pas de style de layout en ligne.
5. Un seul élément `module-nav` (`data-testid`) pour la navigation de module ; le fil d'Ariane est compté séparément (T-031).

## Tests attendus
- Unitaires : configuration de navigation de chaque module (`test:unit`).
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : navigation entre deux pages de chaque zone ; déconnexion ; menu mobile ; un seul `module-nav` par page.
- Captures de référence avant/après : écarts visuels listés et acceptés.
- `tsc`, `build`.

## Critères d'acceptation
- Une seule implémentation de sidebar et d'en-tête.
- Le tanker a les mêmes providers que zylo-liquid.
- Tests de navigation verts sur build prod.

## Risque et retour arrière
Élevé : une coquille cassée bloque tout le produit. Retour arrière : garder l'ancienne coquille jusqu'à la fin, supprimer en dernier.

## Livrable documentaire
- `docs/architecture/frontend/coquille.md` (créé)
- `docs/process/frontend-screens.md` (mis à jour)

## Parallélisable avec
T-034 (backend). Pas en parallèle de T-031 et T-032 sur les mêmes fichiers (ordre écrit dans le plan §5).
