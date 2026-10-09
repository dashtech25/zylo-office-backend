# T-031 : Frontend : un seul fil d'Ariane et des pages de délégation

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-031-fil-ariane` · **Base de test** : `zylo_t031_test` · **Ports** : back 3131, front dev 3231, front prod 3331
- **Dépendances** : T-030
- **Décisions requises** : aucune

## Objectif
Un seul fil d'Ariane, celui de `PageHeader`. La topbar n'affiche plus de libellé de page. Chaque `page.tsx` de `src/app/` devient une ligne de délégation (`export { default } from "…"`) vers un écran, sauf exceptions listées.

## Problèmes résolus
- FRT-003 (P1), ARC-013 (P2), DOC-008 (P2), REV-D-10 (double fil d'Ariane, sélecteur instable), REV-D-14 (périmètre des 53 pages)

## Dépendances : justification
- T-030 : coquille unique dans laquelle la topbar est fusionnée.

## Fichiers / modules concernés
- `src/modules/zylo-liquid/components/ZyloLiquidShell.tsx` (libellé de topbar, lignes 182 à 186 et 247 à 256)
- `src/shared/ui/PageHeader.tsx` (`breadcrumbLabel` obligatoire ou valeur par défaut, `data-testid="breadcrumb"`)
- `src/modules/zylo-liquid/screens/station-detail/StationDetailScreen.tsx` (sans `breadcrumbLabel`, ligne 306-309), `tank-detail/TankDetailScreen.tsx`
- Les 53 `page.tsx` de `src/app/` : liste dans la fiche, avec la cible d'écran de chacune

## Stratégie
1. Tableau des 53 pages : cible d'écran, ou exception (`layout`, `loading`, `error`, route handlers, pages publiques restant hors module : `tarification`, `produits`, `login`, `register`, `essai-gratuit`, `communaute`, `aide`).
2. Forme de la ligne : `export { default } from "…"`, telle que `src/app/CLAUDE.md` la prescrit.
3. Pages `zylo-liquid/*` (« coming soon », 8 à 10 lignes) : délégation à un écran dédié.
4. Script de contrôle : aucune `page.tsx` de plus d'une ligne hors exceptions listées ; échoue sinon.

## Tests attendus
- Playwright prod : un seul fil d'Ariane par page, `getByTestId('breadcrumb')` présent exactement une fois sur les pages de détail ; navigation station vers cuve.
- Script de contrôle vert.
- Unitaires : `breadcrumbLabel` par défaut (`test:unit`).

## Critères d'acceptation
- Un fil d'Ariane par page ; la topbar n'a pas de libellé de page.
- Toutes les pages de `src/app/` sont des lignes de délégation, ou une exception listée.

## Risque et retour arrière
Moyen : déplacer la logique change les imports et peut casser des routes dynamiques (`[roleId]`). Retour arrière : page par page.

## Livrable documentaire
- `docs/architecture/frontend/pages-et-fil-ariane.md` (créé, tableau des 53 pages).

## Parallélisable avec
T-032 (fichiers distincts en principe) ; T-033a après T-031 sur `PageHeader` si modifié.
