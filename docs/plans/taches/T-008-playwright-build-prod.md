# T-008 : Playwright sur build de production, e2e versionnés, jetons exclus

> **Suspendue le 2026-10-09** : Playwright suspendu par décision du client. Voir `docs/process/decision-playwright-suspendu.md`.

- **Statut** : Suspendue · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : frontend (backend pour le démarrage) · **Domaine** : frontend · **Type** : test
- **Branche suggérée** : `test/T-008-playwright-prod` · **Base de test** : `zylo_t008_test` · **Ports** : back 3108, front prod 3308
- **Dépendances** : T-003, T-005, T-041
- **Décisions requises** : `tests/retention-traces-video.md`

## Objectif
Toute exécution Playwright se fait sur le build de production (`next build` puis `next start`), jamais sur `npm run dev`. La suite est versionnée, et le référentiel pays est créé par le global-setup, sans seed manuel.

## Problèmes résolus
- Baseline section 3 (`npm run dev`, seed manuel), DOC-002 (partie e2e), REV-D-07 (jetons en clair dans `e2e/.auth/`), REV-D-17 (suite non versionnée), REV-D-21 (configuration non reproductible), REV-S-17 (rétention des vidéos)

## Dépendances : justification
T-003 (ports), T-005 (garde de base), T-041 (configuration prod de référence). Les specs sont versionnées par T-004 (lot 1).

## Fichiers / modules concernés
- `playwright.config.ts` : `webServer` = `next start -p 3308` après build ; `baseURL` lu depuis l'environnement ; pas de `dev`
- `e2e/global-setup.ts` : garde T-005, seed pays idempotent, pas d'écriture hors base de test
- `package.json` : script `e2e:prod` (build puis test)
- `e2e/.auth/` : ignoré (T-004) et supprimé du disque ; ses jetons sont à révoquer (`questions/securite/rotation-credentials.md`)

## Stratégie
1. Configuration unique de référence : `playwright.config.ts` = build de production. Supprimer toute référence à `npm run dev` dans les scripts e2e.
2. Global-setup : appelle le seed pays (idempotent) après la garde ; refuse toute base sans suffixe `_test`.
3. Stockage d'état d'authentification dans un répertoire temporaire hors dépôt (jamais dans `e2e/.auth/`).
4. Vidéo : rétention définie par la question `retention-traces-video.md` (recommandation : 7 jours, pas d'archivage des vidéos réussies).

## Tests attendus
- `npm run e2e:prod` passe sur `zylo_t008_test` sans seed manuel, deux exécutions consécutives identiques.
- `git ls-files e2e` contient tous les `*.spec.ts` et `global-setup.ts` ; `git check-ignore e2e/.auth/gerant-setup.json` renvoie une règle.
- Mesure avant/après consignée (sans objectif de 17/27 : la cible n'est pas reproductible, voir REV-D-21).

## Critères d'acceptation
- Aucune occurrence de `npm run dev` dans la configuration e2e.
- Seed pays automatique ; plus d'étape manuelle documentée.
- Fichier `e2e/.auth/` absent du dépôt et du disque.
- `docs/process/tests.md` décrit la procédure e2e prod.

## Risque et retour arrière
Moyen : le build de production révèle des erreurs que le mode dev masquait. Retour arrière : la configuration dev reste dans l'historique ; aucune donnée n'est touchée.

## Livrable documentaire
- `docs/process/tests.md`
- `docs/questions/tests/retention-traces-video.md`

## Parallélisable avec
T-006, T-007, T-011, T-014, T-015 (fichiers distincts).
