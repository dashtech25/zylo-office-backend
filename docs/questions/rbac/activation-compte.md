# Comment le titulaire d'un compte créé par un administrateur accède-t-il à son compte ?

- **Question** : par quel canal le titulaire reçoit-il l'accès à un compte créé par un propriétaire ou un administrateur, sans que le créateur connaisse le secret ?
- **Tâches concernées** : T-021, T-049, T-026
- **Contexte** : aujourd'hui le mot de passe temporaire est renvoyé une fois au créateur (IAM-007). Le créateur peut alors se connecter comme le titulaire avant lui (REV-S-06). Il n'existe ni service d'envoi d'e-mail ni invitation.
- **Options** :
  - A. Compte `pending` et lien d'activation à usage unique, envoyé par e-mail via un fournisseur que le client choisit (recommandation). En attendant, la création est désactivée par configuration.
  - B. Mot de passe temporaire affiché au créateur : rejeté, le créateur connaît le secret.
  - C. Code affiché au créateur et remis de vive voix : même défaut que B.
  - D. Affichage au créateur, compte bloqué jusqu'au choix du mot de passe par le titulaire via un jeton distinct : risque résiduel, à accepter explicitement.
- **Recommandation vérifiée** : option A, avec la création désactivée tant que l'envoi n'est pas configuré. Vérification : `User.status` accepte déjà `pending` (`app/identity/models.py`, ligne 27, revue REV-A-06) ; aucun fournisseur d'e-mail n'est présent dans le dépôt.
- **État** : En attente de réponse (fournisseur d'e-mail et validation des droits)
