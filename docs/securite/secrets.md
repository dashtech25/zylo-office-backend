# Secrets : inventaire, injection, rotation et révocation (BE-230)

Document de module. Code : `app/core/secrets.py` (magasin des valeurs),
`app/operator/secrets_models.py` (registre), `app/operator/secrets_service.py` (service).

## Principes

- Le registre `secret_registry` ne contient aucune valeur de secret : nom, propriétaire,
  portée, échéance, dernière rotation, consommateur, caractère obligatoire.
- Les valeurs sont injectées depuis l'environnement au démarrage (`SecretStore.depuis_environnement`).
- Les journaux ne reçoivent jamais une valeur, seulement le nom du secret.
- Échec fermé : un secret obligatoire expiré ou absent empêche le démarrage hors développement
  (`controle_secrets_au_demarrage`, erreur `ConfigurationSecretError`).

## Accès

- Lecture du registre : réservée à l'exploitation (`assert_operator_user`, allowlist
  `OPERATOR_READ_USER_IDS`). Sans droit : 403 `operator_access_denied`.

## Rotation et révocation

- `enregistrer_rotation` remplace la valeur dans le magasin et date `lastRotatedAt`.
- L'ancienne valeur n'est plus conservée : toute signature produite avec elle est refusée
  dès la rotation. Il n'existe pas de fenêtre de tolérance implicite.
- Un nom absent du registre ne peut pas être tourné (404).

## Inventaire

Les secrets réellement déclarés dans `app/core/config.py` sont listés dans
`docs/process/configuration.md`. Le registre en base est alimenté par l'exploitation :
une ligne par secret, sans valeur.
