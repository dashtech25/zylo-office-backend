# T-041 : Retrait de Storybook (branche chore/retirer-storybook) et smoke Playwright sur build prod

> **Suspendue le 2026-10-09** : Playwright suspendu par décision du client. Voir `docs/process/decision-playwright-suspendu.md`.

- **Statut** : Suspendue · **Priorité** : P1 · **Vague** : 0 · **Taille** : S · **Dépôt(s)** : frontend · **Domaine** : frontend · **Type** : chore
- **Branche suggérée** : `chore/retirer-storybook` (existante, commit `64c97e1`, worktree `worktrees/frontend-retirer-storybook`) · **Base de test** : aucune · **Ports** : back 3141, front prod 3341
- **Dépendances** : T-004
- **Décisions requises** : aucune

## Objectif
Fusionner dans `remy` le retrait de Storybook déjà réalisé, après vérification. Créer la première configuration Playwright versionnée sur **build de production** (smoke), qui sert de référence à T-008.

## Problèmes résolus
- DOC-017 (gabarit Storybook), FRT-009 et FRT-023 (partie), REV-A-04, REV-D-01, REV-D-04, REV-D-05

## Dépendances : justification
T-004 : la branche doit être recalée sur le tag `base-T004` par merge (pas de réécriture), sinon elle recommit ce que T-004 a déjà posé.

## Contenu de la branche (à vérifier, pas à réécrire)
Attention : la branche déplace `.storybook/mockApi.ts` vers `e2e/mockApi.ts` (rename détecté par `git show --stat`) ; ce fichier est donc un chemin `e2e/` à conserver après la fusion.

Supprime `.storybook/`, `src/stories/` (26 fichiers), 13 `*.stories.*`, `vitest.config.ts`, `vitest.shims.d.ts`, `vitest`, `vite`, `@vitest/*`, `storybook` de `package.json`. Retire aussi les règles `storybook` de `.gitignore` : à réintroduire pour `storybook-static/` et `*storybook.log`, sans quoi les artefacts locaux deviennent visibles.

## Fichiers / modules concernés
- `package.json`, `package-lock.json` (16 064 lignes modifiées sur la branche)
- `.gitignore` (règles `storybook-static` et `*storybook.log` conservées)
- `eslint.config.mjs` (ignorer `.next`, `storybook-static` s'il existe encore)
- `playwright.prod.config.ts` (créé) ; `e2e/smoke-prod.spec.ts` (créé)

## Stratégie
1. Dans le worktree de la branche : `git merge base-T004` (pas de rebase, pas de réécriture). Résoudre les conflits de `package.json` et `package-lock.json` en gardant le retrait.
2. Vérifier : `npm ci`, `npx tsc --noEmit`, `npm run lint` (plus d'erreurs dues à `storybook-static`), `npm run build`.
3. Créer `playwright.prod.config.ts` : `webServer` = `next start -p 3341` après `next build`, `baseURL` lu depuis l'environnement, jamais `npm run dev`.
4. `e2e/smoke-prod.spec.ts` : la page `/login` se rend, aucune erreur console bloquante. Pas de backend requis.
5. Lancer le smoke sur le build de production et consigner le résultat dans la PR.
6. Fusion dans `remy` par l'orchestrateur après T-004.

## Tests attendus
- `npx tsc --noEmit` vert ; `npm run build` vert ; `npm run lint` sans erreur dans `storybook-static` (dossier supprimé du poste, sauvegardé hors dépôt).
- `npx playwright test -c playwright.prod.config.ts` : smoke vert sur build de production (c'est la première configuration versionnée qui autorise un résultat Playwright dans le plan).

## Critères d'acceptation
- `git grep -l -i storybook -- ':!docs' ':!.gitignore' ':!eslint.config.mjs'` vide : seules les règles d'ignore des artefacts locaux subsistent.
- `package.json` sans dépendance Storybook ni Vitest.
- Smoke Playwright vert sur build de production, config versionnée.
- Branche fusionnée dans `remy`, tag `base-T004` toujours ancêtre.

## Risque et retour arrière
Moyen : `package-lock.json` très modifié. Retour arrière : revert du merge, la branche reste intacte.

## Livrable documentaire
- `docs/audit/retrait-storybook.md` : état à la date de fusion (mis à jour).

## Parallélisable avec
T-001, T-002, T-003, T-005.
