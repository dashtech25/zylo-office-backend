# T-007 : Droit du rôle manager (décision client, aucun élargissement automatique)

- **Statut** : Planifiée, en attente de décision client · **Priorité** : P2 · **Vague** : 1 · **Taille** : S · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : test
- **Branche suggérée** : `fix/T-007-role-manager` · **Base de test** : `zylo_t007_test` · **Ports** : back 3107
- **Dépendances** : aucune
- **Décisions requises** : `rbac/manager-role-superset.md` (en attente de réponse client, bloque la fusion du changement de droits)

## Objectif
Le test `test_shift_manager_role_rights_and_manager_superset` échoue : le rôle manager par défaut ne contient pas toutes les permissions `zyloLiquid.*.manage` attendues. Cette tâche ne décide pas du droit à la place du client. Elle livre : la question, un rapport en lecture seule des organisations concernées, et le marquage du test comme échec connu.

## Problèmes résolus
- Baseline section 1.1, groupe C ; ARC-016 (partie : permissions dupliquées entre `seed.py` et `roles_seed.py`) ; REV-S-05 (élévation automatique au démarrage) ; REV-A-10

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-005 (confort : test local sur base dédiée).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/roles_seed.py` (`DEFAULT_ROLES`, `seed_default_roles`)
- `app/modules/zylo_liquid/seed.py`
- `tests/test_zylo_liquid_staff_batch.py`
- `tests/known_failures.txt` (entrée datée, lien vers la question)
- `scripts/docs/rapport_roles_manager.sql` (requête en lecture seule, créée)

## Stratégie
1. Question `rbac/manager-role-superset.md` : le manager doit-il être un sur-ensemble du responsable de tour ? Recommandation vérifiée : **ne pas élargir automatiquement** les rôles existants. Le test reste un échec connu jusqu'à la réponse.
2. Rapport en lecture seule : pour chaque organisation, rôle manager et permissions manquantes par rapport au test. Fourni au client.
3. Si la réponse est « oui » : **migration explicite, idempotente, journalisée** (liste des organisations et des permissions ajoutées), jamais un backfill de démarrage. Les backfills de démarrage sont retirés par T-028.
4. Si la réponse est « non » : le test est corrigé pour exprimer la règle validée. Aucune permission n'est retirée d'un rôle existant dans les deux cas.
5. `seed.py` et `roles_seed.py` : une seule source de la liste (ARC-016).

## Tests attendus
- Si « oui » : la migration est rejouable sans effet supplémentaire ; test d'idempotence ; test « aucun rôle existant ne gagne de permission au démarrage ».
- Dans tous les cas : un test unitaire vérifie que chaque rôle par défaut contient les permissions de son périmètre déclaré.

## Critères d'acceptation
- Question consignée avec sa réponse (ou son état « En attente de réponse »).
- Aucun élargissement de droit sans réponse écrite du client.
- Aucune permission retirée d'un rôle existant.

## Risque et retour arrière
Moyen : tout changement de rôle par défaut modifie ce que voient les organisations existantes. Retour arrière : migration inverse documentée (retrait des seules permissions ajoutées, à partir du journal).

## Livrable documentaire
- `docs/questions/rbac/manager-role-superset.md`

## Parallélisable avec
T-006, T-008, T-011 à T-015 (le fichier `roles_seed.py` est lu par T-018 et T-021 : coordination).
