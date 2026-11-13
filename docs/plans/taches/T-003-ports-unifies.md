# T-003 : Table de ports unique, allocation par worktree, CORS configurable

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 0 · **Taille** : S · **Dépôt(s)** : backend et frontend · **Domaine** : docs · **Type** : chore
- **Branche suggérée** : `docs/T-003-ports-unifies` · **Base de test** : aucune · **Ports** : aucun (la tâche définit la table)
- **Dépendances** : aucune
- **Décisions requises** : `architecture/ports-canoniques.md` (appliquée, à confirmer)

## Objectif
Une seule table de ports, référencée partout, et une règle d'allocation par worktree qui rend les collisions impossibles. `CORS_ORIGINS` devient configurable par environnement, pour que chaque worktree déclare son port.

## Table retenue
| Usage | Backend | Frontend dev | Frontend prod (Playwright) |
|---|---|---|---|
| Checkout principal (hors worktree) | 3002 | 3001 | 3055 |
| Worktree de la tâche T-NNN (n = NNN) | 3100+n | 3200+n | 3300+n |
| Conteneur Docker | 3002 (interne) | — | 3003 (port de conteneur, documenté à part) |
| Interdits | 3006, 3007 | | |

Unicité : pour n entre 1 et 51, les plages 3101–3151, 3201–3251 et 3301–3351 ne contiennent ni 3001, ni 3002, ni 3003, ni 3055. Les tâches à lettre (T-033a, T-035b…) partagent le numéro n et s'exécutent en chaîne, jamais en parallèle.

## Problèmes résolus
- DOC-002 (P1), DOC-003 (P2), ARC-014 (P2), BCK-024 (P3), DOC-025 (partie ports), REV-S-16 (ports et CORS), REV-A-20 (ports Playwright et worktrees), REV-D-26

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-004 (base de départ : `remy` à jour).

## Fichiers / modules concernés
- Backend : `docs/process/ports.md` (créé, table unique), `README.md`, `CLAUDE.md` (3007 vers 3002), `app/core/config.py` (valeur `PORT` et `CORS_ORIGINS` configurable), `.env.example`, `scripts/check_ports.sh` (créé)
- Frontend : `README.md`, `.env.local.example`, `src/core/api/client.ts` (repli 3007 vers 3002), `playwright.config.ts` (commentaire et port de référence)

## Stratégie
1. Rédiger `docs/process/ports.md` (backend, qui fait foi) avec la table, la règle d'allocation et la liste des ports interdits. Les README renvoient vers ce fichier, sans recopier la table.
2. Aligner chaque source sur la table, un fichier par commit.
3. `CORS_ORIGINS` lu depuis l'environnement, liste explicite de méthodes et d'en-têtes. Chaque worktree positionne son origine.
4. `scripts/check_ports.sh` : échoue si 3006 ou 3007 apparaissent dans les fichiers de configuration. Il est branché en CI par T-038a.

## Tests attendus
- `scripts/check_ports.sh` : aucune occurrence interdite.
- Démarrage manuel du backend sur 3002 et du frontend sur 3001 (`curl /api/v1/health`).
- Préflight CORS depuis le port d'un worktree de test : réussi après configuration de `CORS_ORIGINS`.

## Critères d'acceptation
- Une table de ports, référencée par les README, sans recopie.
- Aucune contradiction entre README, `package.json`, `.env*`, `config.py`, `client.ts`, `CLAUDE.md`, `playwright.config.ts`.
- Règle d'allocation et unicité documentées.

## Risque et retour arrière
Faible pour le code, moyen pour les habitudes locales. Retour arrière : revert, les anciens ports restent fonctionnels.

## Livrable documentaire
- `docs/process/ports.md` (backend)
- `docs/questions/architecture/ports-canoniques.md`

## Parallélisable avec
T-001, T-002 (séquencé sur `config.py`), T-005.
