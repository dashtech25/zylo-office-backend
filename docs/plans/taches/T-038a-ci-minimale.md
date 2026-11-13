# T-038a : CI bloquante minimale dès la vague 1

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : ci · **Type** : ci
- **Branche suggérée** : `ci/T-038a-ci-minimale` · **Base de test** : `zylo_t038a_test` · **Ports** : back 3138, front prod 3338
- **Dépendances** : aucune
- **Décisions requises** : `tests/environnement-recette.md`

## Objectif
Une CI bloquante existe dès la vague 1, avant les changements IAM et sécurité. Elle empêche de fusionner une régression, un dump, un port interdit ou un test unitaire cassé. Le contrôle complet (lint, contrats d'architecture, Playwright) est dans T-038b.

## Problèmes résolus
- DOC-001 (CI désactivée), REV-A-09 (CI livrée trop tard), REV-S-18, REV-D-27

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-001 (CI indépendante : `check_no_dumps.sh` est créé ici) ; T-003 (CI indépendante : le job ports est ajouté quand `check_ports.sh` existe) ; T-005 (CI indépendante : base de test par job dans le workflow) ; T-042 (CI indépendante : `test:unit` ajouté quand T-042 est fusionnée).

## Fichiers / modules concernés
- Backend : `.github/workflows/ci.yml` (réactivé, remplace `ci.yml.disabled`), service PostgreSQL 16, base `zylo_t038a_test`
- Frontend : `.github/workflows/frontend.yml` (créé dans le dépôt frontend)
- `tests/known_failures.txt` (créé) : liste versionnée et datée des échecs connus
- `scripts/check_no_dumps.sh` (créé ici), `scripts/check_ports.sh` (créé par T-003 ; le job ports est ajouté par T-038a s'il existe, sinon par T-003)

## Stratégie
1. Job backend : venv, `pytest` en **mode régression** : le job échoue si un test hors de `known_failures.txt` échoue, et aussi si un test listé passe (la liste doit être mise à jour). La liste diminue à chaque tâche de correction (T-006, T-007, T-009, T-010).
2. Job backend : `scripts/check_no_dumps.sh` et `scripts/check_ports.sh`.
3. Job frontend : `npm ci`, `npx tsc --noEmit`, `npm run build` ; l'étape `npm run test:unit` est ajoutée dès que T-042 est fusionnée.
4. Secrets : aucun littéral dans le fichier de workflow ; les valeurs passent par les secrets GitHub (REV-S-03).
5. Versions : Node et Python fixés explicitement dans les workflows.
6. Passage à « pytest complet bloquant » : quand `known_failures.txt` est vide (fin de T-006, T-007, T-009, T-010).

## Tests attendus
- Le workflow passe sur une branche de test.
- Une violation volontaire (dump ajouté, port 3007, test unitaire cassé) fait échouer la CI : preuve consignée dans la PR.

## Critères d'acceptation
- CI verte sur `remy` pour les jobs listés, échec démontré sur les trois violations.
- `known_failures.txt` daté, et chaque entrée référence une tâche.
- Aucun secret dans un fichier versionné.

## Risque et retour arrière
Moyen : une CI bloquante arrête les fusions tant que la liste n'est pas à jour. Retour arrière : désactiver le workflow (fichier renommé) par une PR dédiée, avec décision écrite.

## Livrable documentaire
- `docs/process/ci.md` (créé, jobs réels et leur correspondance avec la documentation).
- `docs/questions/tests/environnement-recette.md`

## Parallélisable avec
T-006, T-007, T-008 (fichiers distincts).
