# T-033b : Frontend : appels réseau par le client unique et états d'erreur des widgets

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-033b-reseau` · **Base de test** : `zylo_t033b_test` · **Ports** : back 3133, front dev 3233, front prod 3333
- **Dépendances** : T-033a
- **Décisions requises** : aucune

## Objectif
Tous les appels réseau passent par `src/core/api/client.ts` (sauf exceptions documentées). Les widgets du tableau de bord n'affichent plus « vide » quand la requête échoue. Un `escapeHtml` unique.

## Problèmes résolus
- FRT-007 (P2, `fetch` hors client), FRT-008 (P2, `escapeHtml` dupliqué), FRT-011 (P2, erreurs non gérées : 71 `useQuery`, recompte à refaire), REV-D-15 (comptages non reproductibles)

## Dépendances : justification
T-033a (`QueryState` et composants partagés utilisés pour les états d'erreur).

## Fichiers / modules concernés
- `src/core/api/client.ts` (`apiUpload`, `apiFetchBlob`)
- `src/core/api/importTable.ts` (message d'erreur `body.error.message`)
- `src/modules/zylo-liquid/services/liveTruckPositions.ts` (SSE : exception documentée)
- `src/shared/ui/FilePreviewModal.tsx`, `ShareButton.tsx`
- `src/shared/lib/html.ts` (créé, `escapeHtml` unique)

## Stratégie
1. Commande de contrôle : `grep -rn "fetch(" src | grep -v core/api` : liste vide, sauf exceptions listées (SSE, stockage externe).
2. Compter les `useQuery` sans état d'erreur avec une commande reproductible, et corriger les widgets du tableau de bord en premier.
3. Message d'erreur d'import XLSX lu depuis `body.error.message`.

## Tests attendus
- Playwright prod : import XLSX avec message d'erreur correct ; état d'erreur affiché si l'API échoue (interception réseau) ; réessai fonctionne.
- Unitaires : `escapeHtml` (`test:unit`).
- Contrôle `fetch(` vert.

## Critères d'acceptation
- Aucun `fetch` hors client, sauf exceptions documentées.
- Widgets du tableau de bord : état d'erreur distinct de l'état vide.

## Risque et retour arrière
Moyen. Retour arrière : écran par écran.

## Livrable documentaire
- `docs/architecture/frontend/reseau.md` (créé, exceptions).

## Parallélisable avec
Rien sur les mêmes fichiers ; T-033c après T-033b.
