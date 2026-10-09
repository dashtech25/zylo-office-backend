# Où versionner les exigences terrain (cahiers métier) ?

- **Question** : les cahiers métier (`docs/requirements/`) sont-ils versionnés dans le dépôt backend, dans un dépôt privé dédié, ou hors dépôt ?
- **Tâches concernées** : T-016, T-001
- **Contexte** : les cahiers contiennent des données terrain. La visibilité du dépôt `origin` n'a pas pu être contrôlée par l'agent (pas d'accès réseau). T-001 demande ce contrôle.
- **Options** :
  - A. Dans le dépôt backend, après contrôle de visibilité et vérification d'absence de secret (recommandation, si le dépôt est privé).
  - B. Dépôt privé dédié : sépare les exigences du code, recommandé si le dépôt backend doit devenir public.
  - C. Hors dépôt : aucune trace versionnée, perte de l'historique des exigences.
- **Recommandation vérifiée** : option A si T-001 confirme que le dépôt est privé ; sinon option B. Vérification : la visibilité est un prérequis de T-016 (contrôle T-001).
- **État** : En attente de réponse (dépend du résultat du contrôle de visibilité)
