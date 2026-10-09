# T-005 : Environnement de test isolé par tâche et garde de base

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 0 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : ci · **Type** : chore
- **Branche suggérée** : `chore/T-005-env-taches` · **Base de test** : `zylo_t005_test` · **Ports** : back 3105, front dev 3205, front prod 3305
- **Dépendances** : T-004
- **Décisions requises** : aucune

## Objectif
Une commande crée l'environnement d'une tâche : venv, base PostgreSQL dédiée, référentiel pays et devises. Aucune base partagée entre tâches, et une garde empêche de vider une base qui n'est pas une base de test.

## Problèmes résolus
- ARC-015 (`.venv` cassé, `lint-imports` absent), baseline section 0 (wipe global, seed manuel), DOC-025 (partie environnements), REV-S-15 (base partagée par défaut), REV-D-18 (base partagée avec pytest)

## Dépendances : justification
T-004. Prérequis de T-006, T-008, T-010, T-028, T-034 et de toute tâche qui touche la base.

## Fichiers / modules concernés
- `tests/conftest.py` : garde commune (pytest) ; `TEST_DATABASE_URL` **sans valeur par défaut** (échec si absente)
- `e2e/global-setup.ts` : même garde, côté Playwright (le même module de vérification est partagé)
- `scripts/dev/create_task_db.sh` (créé) ; `docs/process/environnement-taches.md` (créé)
- `.venv` (non versionné, recréé) ; `.env.local` par worktree (non versionné)

## Stratégie
1. Nom de base accepté : `zylo_t<NNN>[a-z]?_test` uniquement. Hôte et port dans une liste autorisée. Refus si la base cible ressemble à une base de développement (`zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette`), quel que soit le port.
2. `create_task_db.sh <TID>` : crée la base, applique `alembic upgrade head`, lance le seed idempotent du référentiel (`scripts/seed_world_reference_data.py`).
3. Recréer `.venv` avec `python3.13 -m venv`, `pip install -r requirements.txt`, vérifier `lint-imports` (contrats existants KEPT).
4. Documenter la procédure par worktree : venv, `npm ci`, variables, ports (T-003).

## Tests attendus
- Garde : nom interdit lève une erreur ; `zylo_t005_test` accepté ; `zylo_office` refusé même sur un autre port (test explicite).
- Garde : `TEST_DATABASE_URL` absente : échec, pas de valeur par défaut.
- Script : exécution sur base jetable, `alembic current` au head.
- `lint-imports` : contrats KEPT.
- `pytest tests/test_rbac.py` vert sur la base dédiée.

## Critères d'acceptation
- Une seule commande crée l'environnement d'une tâche.
- Impossible de vider une base interdite, par pytest (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`).
- Le seed pays n'est plus relancé à la main.

## Risque et retour arrière
Élevé si la garde est mal écrite : `conftest.py` fait aujourd'hui un `TRUNCATE ... CASCADE` sur toutes les tables de `TEST_DATABASE_URL`. Retour arrière : revert ; tant que la garde n'est pas fusionnée, aucune tâche ne lance pytest sur une base partagée.

## Livrable documentaire
- `docs/process/environnement-taches.md`

## Parallélisable avec
T-001, T-002, T-003 (séquencé avec T-002 sur `conftest.py`).
