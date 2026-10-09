# T-032 : Frontend : tokens visuels uniques, sans référence circulaire, suppression de prototype.css

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : refactor
- **Branche suggérée** : `refactor/T-032-tokens` · **Base de test** : `zylo_t032_test` · **Ports** : back 3132, front dev 3232, front prod 3332
- **Dépendances** : T-030, T-031
- **Décisions requises** : `frontend/palette-de-reference.md` (en attente de validation design, à trancher avant le démarrage)

## Objectif
Une seule palette, définie dans `globals.css` sur `:root`, consommée par les composants. Supprimer les redéclarations circulaires du bloc `@theme inline`, `src/modules/zylo-liquid/styles/prototype.css` (403 lignes, 2 `!important`) et les couleurs en dur hors cartes.

## Problèmes résolus
- FRT-004 (P1), FRT-010 (P2), FRT-019 (P3), REV-D-08 (référence circulaire, troisième couche non recensée), REV-D-09 (variante sombre contraire au code)

## Dépendances : justification
T-030 (la coquille porte les tokens de `.zl-shell`), T-031 (même fichiers de pages et de topbar : ordre écrit, pas en parallèle).

## Fichiers / modules concernés
- `src/app/globals.css` (tokens : bloc `:root` et bloc `@theme inline`)
- `src/modules/zylo-liquid/styles/prototype.css` (suppression)
- `src/modules/zylo-liquid/components/ZyloLiquidShell.tsx` (import à retirer), `GasDashboard.tsx`, `TrucksMap.tsx`

## Stratégie
1. Décision de palette avant démarrage (`palette-de-reference.md`) : recommandation `globals.css` (`--color-primary: #3498db`). La sidebar change de couleur de marque (`#5ebcfc` vers `#3498db`) : c'est un changement visuel à valider.
2. Supprimer les déclarations `--color-x: var(--color-x)` du bloc `@theme inline` ; ne garder que les références vers des valeurs non circulaires.
3. Migrer `--brand` et `--ink` vers des tokens existants ; supprimer `prototype.css`.
4. Couleurs de carte (contrainte Mapbox) et `ColorPicker` conservées.
5. Thème clair seul, comme le commentaire de `globals.css` l'indique. Pas de variante sombre dans ce lot.

## Tests attendus
- Contrôle après `next build` : `grep -c -- "--color-[a-z-]*:var(--color-" .next/static/**/*.css` renvoie 0 pour les tokens de `globals.css`.
- Captures de référence avant/après non produites (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) : écarts visuels non contrôlés par test automatisé. Écarts listés et acceptés par le client.
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : navigation et rendu des écrans principaux.
- `tsc`, `build`, `test:unit`.

## Critères d'acceptation
- Aucun fichier CSS hors `globals.css` dans `src/`, sauf exceptions listées.
- Une seule source de couleur pour les composants ; contrôle grep scripté.
- Palette validée par le client.

## Risque et retour arrière
Élevé visuellement. Retour arrière : conserver `prototype.css` jusqu'à validation, puis supprimer.

## Livrable documentaire
- `docs/architecture/frontend/tokens.md` (créé)
- `docs/questions/frontend/palette-de-reference.md`

## Parallélisable avec
T-033a après sa fin (fichiers partagés).
