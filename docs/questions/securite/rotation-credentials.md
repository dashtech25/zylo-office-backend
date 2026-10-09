# Rotation des identifiants exposés ou versionnés

- **Question** : qui fait tourner quels identifiants, à quelle date, et avec quel critère de preuve ?
- **Tâches concernées** : T-001, T-015, T-027, T-008
- **Contexte** : le dump de `backups/` contient des données de la base `zylo_office` (commit `8aea496`). `tests/conftest.py` est suivi et contient un littéral de mot de passe de développement (revue REV-S-03). Un fichier `e2e/.auth/` contenant des jetons de session est présent sur disque (vérifié : le dossier existe, non suivi). Le compte Holykell et le mot de passe de démonstration de `scripts/bootstrap_demo_org.py` sont concernés.
- **Liste à traiter** :
  1. mot de passe de la base `zylo_office` ;
  2. compte externe Holykell ;
  3. mot de passe de démonstration de `scripts/bootstrap_demo_org.py` ;
  4. jetons contenus dans `e2e/.auth/` (à révoquer, puis supprimer du disque) ;
  5. littéraux de développement dans `tests/conftest.py` et `.github/workflows/ci.yml.disabled`, si le même mot de passe sert ailleurs.
- **Options** :
  - A. Rotation par l'opérateur, dès que possible, avec un propriétaire nommé et une date attestée par écrit (sans valeur de secret dans le dépôt).
  - B. Rotation différée après la décision de purge : déconseillé, la fenêtre d'exposition s'allonge.
- **Recommandation vérifiée** : option A. Vérification : `e2e/.auth` est présent et non suivi (contrôle `git status`) ; le littéral de `conftest.py` est suivi (contrôle `git ls-files`). Critère de clôture de T-001 : tableau rempli (identifiant, propriétaire, date, preuve), sans valeur.
- **État** : En attente de réponse (propriétaires et dates à nommer par le client)
