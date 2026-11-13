# Niveau des contrats import-linter

- **Question** : les contrats d'architecture sont-ils bloquants dès leur introduction, ou en avertissement d'abord ?
- **Tâches concernées** : T-036, T-038b, T-034
- **Contexte** : `.importlinter` contient déjà des contrats (ordre de dix). `import-linter` 2.15 n'a pas de type `acyclic` général : l'acyclicité passe par des contrats `forbidden` par paire (revue REV-A-16).
- **Options** :
  - A. Avertissement seul : rien ne bloque, les violations s'accumulent.
  - B. `forbidden` en erreur, avec une liste d'exceptions datée et réduite à chaque PR (recommandation).
  - C. Pas de contrat supplémentaire : les cycles ARC-005 restent.
- **Recommandation vérifiée** : option B, introduite en avertissement pendant une PR puis passée en erreur. Vérification : le nombre de contrats existants et la version d'`import-linter` sont relevés dans `requirements.txt`.
- **État** : Appliquée (décision du coordinateur, à confirmer)
