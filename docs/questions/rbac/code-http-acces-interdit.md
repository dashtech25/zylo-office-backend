# Code HTTP en cas d'accès à une organisation étrangère

- **Question** : un accès inter-organisations répond-il par 403 ou par 404 ?
- **Tâches concernées** : T-010, T-047
- **Contexte** : la revue (REV-S-04) et l'audit (IAM-001) décrivent des routes qui acceptent un en-tête étranger. Un 403 révèle qu'une ressource existe dans une autre organisation.
- **Options** :
  - A. 404 uniforme pour « inexistant » et « interdit » (recommandation) : aucune énumération d'identifiants.
  - B. 403 pour « interdit » : plus explicite pour le débogage, mais révèle l'existence.
- **Recommandation vérifiée** : option A, appliquée par la dépendance `get_current_organization_id` (`app/rbac/service.py`, T-010), et testée par T-047. Le refus de droits au sein de la même organisation reste un 403.
- **État** : Appliquée (sur recommandation, à valider par le client)
