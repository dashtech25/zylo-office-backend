# Migrations hors démarrage du conteneur

- **Question** : les migrations Alembic doivent-elles s'exécuter au démarrage du conteneur ?
- **Tâches concernées** : T-028, T-051
- **Contexte** : `Dockerfile`, ligne 33 : `alembic upgrade head && uvicorn ...` (vérifié). Une migration destructive lancée à chaque démarrage, sans sauvegarde, est un risque de perte de données (REV-S-12).
- **Options** :
  - A. Migration au démarrage (état actuel) : rejeté.
  - B. Job de migration séparé, exécuté une fois par déploiement, et vérification de la révision au démarrage (recommandation).
  - C. Migrations manuelles uniquement : oublis probables.
- **Recommandation vérifiée** : option B. Vérification : la commande `CMD` actuelle et la liste des migrations contenant `drop` ou `TRUNCATE` (constat REV-S-12) justifient la séparation.
- **État** : Appliquée (décision du coordinateur, à confirmer)
