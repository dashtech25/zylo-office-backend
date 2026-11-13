# Ordre des validations sur une commande d'achat avec fournisseur inactif

- **Question** : quand un fournisseur est inactif et que la commande est incomplète, quelle erreur le client reçoit-il en premier ?
- **Tâches concernées** : T-006
- **Contexte** : le test `test_purchase_order_requires_active_supplier` attend `supplier_inactive`, mais obtient `validation_error` (baseline, groupe B). La commande du test n'a pas de ligne, donc elle est invalide au sens du schéma.
- **Options** :
  - A. Validation de schéma d'abord : le client reçoit `validation_error` ; le test est corrigé pour envoyer une commande complète, puis vérifier `supplier_inactive` (recommandation).
  - B. Contrôle fournisseur d'abord : `supplier_inactive` même si la commande est incomplète ; le test reste tel quel, mais l'API change.
- **Recommandation vérifiée** : option A. Vérification : le test échoue en amont sur le schéma (sortie de la baseline) ; corriger le payload ne retire aucune assertion. L'option B est une modification d'API qui relève d'une décision métier.
- **État** : En attente de réponse (confirmation métier de l'ordre)
