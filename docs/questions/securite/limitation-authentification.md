# Stockage des compteurs de tentatives de connexion

- **Question** : les compteurs de tentatives (limitation de débit et verrouillage) sont-ils stockés dans PostgreSQL ou dans un service dédié (Redis) ?
- **Tâches concernées** : T-012
- **Contexte** : aucune dépendance Redis dans `requirements.txt` ni dans `docker-compose.yml` (vérifié). L'objectif de T-012 est de bloquer le brute force sans créer de déni de service ciblé (REV-S-07).
- **Options** :
  - A. PostgreSQL existant : aucune infrastructure ajoutée, lecture et écriture transactionnelles, latence acceptable pour l'authentification.
  - B. Redis : plus rapide, mais un service de plus à exploiter, sauvegarder et surveiller.
- **Recommandation vérifiée** : option A, avec une limite par IP à l'échelle du proxy. Vérification : absence de Redis dans les fichiers de dépendances et de déploiement (contrôle ci-dessus). Revoir si la charge d'authentification le justifie (mesure à consigner).
- **État** : En attente de réponse (avance sur la recommandation, réversible)
