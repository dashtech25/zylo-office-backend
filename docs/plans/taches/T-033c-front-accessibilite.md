# T-033c : Frontend : accessibilité des éléments interactifs et des overlays

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-033c-a11y` · **Base de test** : `zylo_t033c_test` · **Ports** : back 3133, front dev 3233, front prod 3333
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
Les éléments interactifs sont utilisables au clavier, les overlays gèrent le focus, les onglets sont navigables. Les règles d'accessibilité sont des contrôles, pas des souhaits.

## Problèmes résolus
- FRT-012 (P2, accessibilité), FRT-022 (P3, overlays)

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-033b (ordre de fusion : pas d'artefact consommé).

## Fichiers / modules concernés
- `src/shared/ui/Modal.tsx`, `Tabs.tsx`
- `src/modules/zylo-tanker/screens/pumps/PumpsScreen.tsx`, `tanks/TanksScreen.tsx` (onglets)
- Menu mobile de `ModuleShell` (T-030)

## Stratégie
1. Focus : piégé dans les modales, restauré à la fermeture ; Échap ferme.
2. Onglets : navigation par flèches et touches de l'onglet.
3. Règle ESLint `jsx-a11y` si elle est compatible avec la configuration ; sinon contrôle Playwright (`getByRole`).
4. La protection CSRF et la règle ESLint sur `fetch` restent des hypothèses signalées : elles ne sont pas revendiquées par cette tâche.

## Tests attendus
- Playwright prod : onglets au clavier ; Échap ferme la modale ; focus restauré.
- Unitaires : logique de focus si extraite (`test:unit`).

## Critères d'acceptation
- Les parcours clavier listés dans la fiche passent.
- Aucun overlay sans fermeture au clavier.

## Risque et retour arrière
Faible. Retour arrière : revert par composant.

## Livrable documentaire
- `docs/architecture/frontend/accessibilite.md` (créé).

## Parallélisable avec
Rien sur les mêmes fichiers.
