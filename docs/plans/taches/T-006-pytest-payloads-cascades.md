# T-006 : Corriger les 21 tests pytest en échec (payloads et cascades)

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : test
- **Branche suggérée** : `fix/T-006-pytest-payloads` · **Base de test** : `zylo_t006_test` · **Ports** : back 3106
- **Dépendances** : T-005 (dépendance **levée** par décision du coordinateur, 2026-10-09). Garde-fou à la place : tout lancement pytest exporte `TEST_DATABASE_URL` vers `zylo_t006_test` et vérifie que la variable est définie ; `tests/conftest.py` n'est pas modifié (T-002 et T-005 le touchent). Sans ce garde-fou, le repli de `conftest.py` pointe sur `zylo_office_test`, que `_wipe()` vide à chaque session.
- **Décisions requises** : `zylo-liquid/ordre-validation-fournisseur.md` (option A appliquée : le test envoie une commande complète ; confirmation métier toujours en attente)

## Objectif
Faire passer les groupes A (12 tests, HTTP 422 `body.lines` requis) et B (9 tests en cascade, `KeyError: 'id'`) de la baseline, sans affaiblir un contrôle de sécurité ni une assertion.

## Problèmes résolus
- Baseline `baseline-tests.md` section 1.1, groupes A et B.

## Dépendances : justification
T-005 (base dédiée). Ne dépend pas de T-002 (la configuration de test est déjà posée par T-005).

## Fichiers / modules concernés
- `tests/test_zylo_liquid_approvisionnement.py`, `test_zylo_liquid_declarations.py`, `test_zylo_liquid_delivery_flow.py`, `test_zylo_liquid_purchase_order_document.py`, `test_zylo_liquid_tracking_business_flows.py`, `test_zylo_liquid_reconciliation_engine.py`
- `app/modules/zylo_liquid/schemas.py` seulement si l'API doit être corrigée (à éviter).

## Stratégie
1. Groupe A : ajouter une ligne valide dans les payloads (`lines` requis par le schéma). Ne pas rendre `lines` optionnel : une commande vide serait acceptée sans décision métier.
2. Groupe B : la cascade disparaît quand la création réussit ; chaque fixture crée l'entité avec le même payload.
3. `test_purchase_order_requires_active_supplier` (attend `supplier_inactive`, obtient `validation_error`) : le test est corrigé pour envoyer un payload complet. Si la décision de la question montre que l'ordre métier est différent, le cas devient un critère propre (correction d'API, avec sa question).
4. Retirer la ligne correspondante de `tests/known_failures.txt` à chaque test corrigé.

## Tests attendus
- `pytest tests/test_zylo_liquid_*.py` : les 21 tests passent sur `zylo_t006_test`.
- Suite complète : aucun nouvel échec ; `known_failures.txt` ne contient plus les 21 tests.

## Critères d'acceptation
- 21 tests verts, sans assertion supprimée (contrôle `git diff` : aucune ligne `assert` retirée).
- Si l'API change : une question déposée, et le critère de ce cas est rédigé à part.

## Risque et retour arrière
Faible si l'on corrige les tests. Élevé si l'on modifie l'API sans décision. Retour arrière : revert.

## Livrable documentaire
- `docs/audit/baseline-tests.md` (statut « corrigé par T-006 »).

## Compte des tests (écart fiche / baseline)
- La fiche et le registre annoncent 21 tests (groupes A et B). La baseline (`docs/audit/baseline-tests.md`) en compte 22 : les 21 mêmes plus le test du rôle manager (`test_shift_manager_role_rights_and_manager_superset`, groupe C). Référence retenue : la baseline (22).
- Le test du rôle manager n'existe pas à `base-T004` : il n'est présent que dans le commit de snapshot `a7329ec` (branche `wip/2026-10-08-snapshot-backend`, non fusionnée). Il n'est donc ni corrigé ni marqué ici ; il relève de T-004b (tri du WIP) et de T-007 (décision client, `rbac/manager-role-superset.md`). Aucun droit du rôle manager n'a été modifié.
- `tests/known_failures.txt` mentionné par la fiche n'existe pas dans le dépôt : rien à retirer.

## Parallélisable avec
T-007, T-008, T-011 à T-015 (pas de fichier commun hors tests zylo_liquid).
