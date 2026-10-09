# T-006 : Corriger les 21 tests pytest en échec (payloads et cascades)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : test
- **Branche suggérée** : `fix/T-006-pytest-payloads` · **Base de test** : `zylo_t006_test` · **Ports** : back 3106
- **Dépendances** : aucune
- **Décisions requises** : `zylo-liquid/ordre-validation-fournisseur.md`

## Objectif
Faire passer les groupes A (12 tests, HTTP 422 `body.lines` requis) et B (9 tests en cascade, `KeyError: 'id'`) de la baseline, sans affaiblir un contrôle de sécurité ni une assertion.

## Problèmes résolus
- Baseline `baseline-tests.md` section 1.1, groupes A et B.

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-005 (confort : tests exécutés en local sur `zylo_t006_test`).

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

## Parallélisable avec
T-007, T-008, T-011 à T-015 (pas de fichier commun hors tests zylo_liquid).
