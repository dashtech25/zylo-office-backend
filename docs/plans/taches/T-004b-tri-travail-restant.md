# T-004b : Tri du travail en cours restant (lots non bloquants)

- **Statut** : À vérifier (lots 1 et 2 fusionnés dans `remy` le 2026-10-09 ; lots restants non fusionnés) · **Priorité** : P1 · **Vague** : 0 · **Taille** : L · **Dépôt(s)** : backend et frontend · **Domaine** : process · **Type** : chore
- **Branche suggérée** : `wip/<date>-<lot>` par lot · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-004
- **Décisions requises** : aucune

## Objectif
Trier et commiter le reste du travail en cours (zylo_liquid backend, zylo_tanker, design system, écrans) sans bloquer les tâches de la vague 0 et 1. Chaque lot part du tag `base-T004`, est testé et est fusionné par l'orchestrateur seul.

## Problèmes résolus
- DOC-019 (partie restante), REV-A-05 (découpe de T-004).

## Dépendances : justification
- T-004 : le tri porte sur le reste identifié par T-004.

## Règles
- Un lot = un sujet = une branche `wip/<date>-<lot>`. Aucun lot ne contient de `.env*`, dump, `.next/`, `storybook-static/`, `e2e/.auth/`, `test-results/`.
- Un lot qui touche un fichier chaud du plan (`docs/plans/PLAN_REMISE_SUR_PIED.md` §5) est fusionné **avant** que la tâche concernée ne démarre, ou rebasé sur la tâche dans son worktree. Aucune tâche de vague 1 ne démarre sur un fichier dont le lot est non fusionné.
- Le lot Storybook n'existe pas ici : il est traité par T-041.

## Stratégie
1. Lister les lots à partir de `git status --porcelain`, par sujet.
2. Pour chaque lot : `tsc --noEmit` (frontend) ou `pytest` ciblé (backend), puis commit sur `wip/…`.
3. Fusion par l'orchestrateur, après revue du diff, dans l'ordre des fichiers chauds.

## Tests attendus
- Pour chaque lot : résultat de `tsc`/`pytest` ciblé consigné dans la description du lot.

## Critères d'acceptation
- Working tree de `remy` propre à la fin, les lots sont fusionnés ou explicitement reportés par écrit.
- Durée cible indicative : 2 à 4 jours (estimation, non mesurée, à confirmer après T-004).

## Risque et retour arrière
Risque de conflit avec les tâches de vague 1 : traité par la règle des fichiers chauds. Retour arrière : chaque lot est une branche séparée, on peut la retirer sans toucher aux autres.

## Parallélisable avec
Les tâches de vague 0 et 1, sous réserve de la règle des fichiers chauds.

## Réalisation (lot 5, 2026-10-09)
- Fusionnés dans `remy` : `docs/T-004b-tri` (tri du travail en cours), `feat/T-004b-lot-2` (Web Push, backend) et `feat/T-004b-lot-1` (composants graphiques, frontend).
- Revue du lot 2 : le handler `AlertCreated` était synchrone alors que `publish` l'attend ; corrigé (`fix(notifications)`, test ajouté). Écart restant : l'événement est publié avant le commit de `upsert_active_alert` (consigné dans le code).
- Non fusionnés : les autres lots du tri (`wip/…`). Statut à réviser quand ils le seront.
