# Clé de chiffrement du mot de passe Holykell, sauvegarde et suppression de l'ancienne colonne

- **Question** : où vit la clé de chiffrement, qui la sauvegarde, et quand l'ancienne colonne en clair est-elle supprimée ?
- **Tâches concernées** : T-027, T-002
- **Contexte** : le mot de passe du compte Holykell est stocké en clair dans `holykellPassword` (`app/modules/zylo_liquid/models.py`, ligne 74 ; vérifié par la revue). Si la clé est perdue, les comptes deviennent inutilisables.
- **Options** :
  - A. Variable d'environnement dédiée, obligatoire hors développement, avec sauvegarde de la clé hors dépôt et test de restauration (recommandation).
  - B. Gestionnaire de secrets : plus sûr, à mettre en place plus tard.
  - C. Service de clés managé (KMS) : dépendance d'infrastructure, hors périmètre actuel.
- **Suppression de la colonne en clair** : tâche séparée, non planifiée. Elle exige un accord écrit du commanditaire, une période d'observation et une sauvegarde vérifiée.
- **Recommandation vérifiée** : option A ; suppression différée. Vérification : T-002 déclare la variable et impose sa présence hors développement ; T-027 contient le test de restauration.
- **État** : En attente de réponse (sauvegarde de la clé à confier à une personne nommée)
