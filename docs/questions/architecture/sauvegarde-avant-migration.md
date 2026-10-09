# Sauvegarde et retour arrière avant migration

- **Question** : qui réalise la sauvegarde avant chaque migration, où est-elle stockée, qui teste la restauration, et quelle révision est en production ?
- **Tâches concernées** : T-028, T-018, T-027, T-037a
- **Contexte** : la sauvegarde est aujourd'hui une « procédure opérateur » sans tâche ni critère. Aucune révision de production n'est consignée. Des migrations contiennent `drop_column`, `drop_table` ou `TRUNCATE` (constat REV-S-12).
- **Options** :
  - A. Sauvegarde chiffrée par l'opérateur avant chaque déploiement, stockée hors dépôt, restauration testée sur base jetable chaque trimestre (recommandation).
  - B. Sauvegarde automatique déclenchée par le job de déploiement : meilleure traçabilité, à mettre en place.
- **Recommandation vérifiée** : option A pour commencer. Vérification : le runbook de T-028 contient les étapes ; la révision de production reste à relever par l'opérateur (lecture seule).
- **État** : Appliquée provisoirement : option A (recommandation vérifiée, mise en œuvre dans docs/operations/deploiement.md). Lieu de stockage des sauvegardes et personne chargée de tester la restauration : à désigner par l'opérateur. Révision de production : à relever par l'opérateur (lecture seule).
