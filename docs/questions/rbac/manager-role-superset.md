# Le rôle manager doit-il contenir toutes les permissions du responsable de tour ?

- **Question** : le rôle manager doit-il être un sur-ensemble du responsable de tour (shift manager) ? Si oui, faut-il l'appliquer aux organisations existantes ?
- **Tâches concernées** : T-007, T-018
- **Contexte** : le test `test_shift_manager_role_rights_and_manager_superset` échoue (baseline, groupe C). Le démarrage applique aujourd'hui `backfill_default_role_permissions` à chaque processus, qui ajoute des permissions aux rôles existants (`app/main.py`, lignes 105 à 109, vérifié). Tout changement de `DEFAULT_ROLES` élargit donc les droits de toutes les organisations, sans validation.
- **Options** :
  - A. Oui : migration explicite, idempotente, journalisée, après un rapport des organisations et permissions concernées (accord écrit requis).
  - B. Non : le test est corrigé pour exprimer la règle validée. Aucun droit n'est retiré.
  - C. Pas de changement sur les rôles existants : un rôle supplémentaire (par exemple superviseur) est créé pour les nouvelles organisations, sur demande.
- **Recommandation vérifiée** : ne rien élargir tant que le client n'a pas répondu ; si le besoin est réel, préférer C. Vérification : le backfill de démarrage est bien à l'origine d'un élargissement possible (constat ci-dessus).
- **État** : En attente de réponse (décision de droits du client)
