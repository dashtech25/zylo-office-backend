# Purge de l'historique git du dump de base de données

- **Question** : faut-il réécrire l'historique git pour retirer `backups/zylo_office_20260831_180729.sql.gz`, et quelle est la visibilité réelle du dépôt `origin` ?
- **Tâches concernées** : T-001 (question créée et rattachée), T-027, T-015
- **Contexte** : le fichier est suivi depuis le commit `8aea496` (vérifié : `git log --all -- backups`). `origin` pointe sur GitHub. L'agent n'a pas accès au réseau : la visibilité du dépôt (public ou privé) n'est pas vérifiée. Retirer le fichier de l'index ne supprime pas les copies déjà clonées.
- **Options** :
  - A. Conserver l'historique, faire tourner les identifiants (voir `rotation-credentials.md`), et garder le dépôt privé. Pas de réécriture, pas de rupture pour les clones existants.
  - B. Réécrire l'historique (`git filter-repo`) puis force-push. Casse les clones et les branches de travail, et ne supprime pas les copies déjà téléchargées.
  - C. Si le dépôt est public : considérer le contenu comme publié, faire tourner les identifiants immédiatement, puis décider de A ou de B.
- **Recommandation vérifiée** : option A, avec la règle suivante : considérer le contenu du dump comme compromis. Vérification : le fichier est dans l'historique (commit `8aea496`), donc retirer l'index ne suffit pas. Si la visibilité est publique, traiter comme une fuite immédiate (option C). Aucune réécriture sans accord écrit du commanditaire ; l'agent ne prend pas cette décision.
- **État** : En attente de réponse (visibilité à consigner, décision du commanditaire)
