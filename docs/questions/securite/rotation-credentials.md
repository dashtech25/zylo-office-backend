# Rotation des identifiants exposés ou versionnés

- **Question** : qui fait tourner quels identifiants, à quelle date, et avec quel critère de preuve ?
- **Tâches concernées** : T-001, T-015, T-027, T-008
- **Contexte** :
  - le dépôt `dashtech25/zylo-office-backend` est **public** (contrôle `gh repo view`, 2026-10-08, voir `purge-historique-dump.md`) ;
  - le dump `backups/zylo_office_20260831_180729.sql.gz` contient des données de la base `zylo_office` ; il est dans l'historique (commit `8aea496`) et retiré de l'index par T-001 (commit `8f2a72b`) ;
  - `tests/conftest.py` (ligne 6) est suivi et contient un littéral de mot de passe de développement, masqué ici ; le même littéral figure dans `.github/workflows/ci.yml.disabled` (vérifié par `grep` sur le dépôt) ;
  - des jetons de session de tests (`gerant-setup.json`, `fixture-data.json`) étaient dans `e2e/.auth/` ; T-004 les a déplacés dans `sauvegarde-T004-2026-10-08/artefacts-frontend/e2e-auth/` (hors dépôt, non suivis). Ils restent sur disque tant qu'ils ne sont pas révoqués et supprimés ;
  - `scripts/bootstrap_demo_org.py` (suivi) contient un mot de passe de démonstration (2 occurrences de `password`/`mot_de_passe` à vérifier par la personne qui fait la rotation) ;
  - le compte externe Holykell est concerné (voir `chiffrement-cle-holykell.md`).
- **Liste à traiter** (tableau à compléter par le client ; aucune valeur de secret ne figure dans ce dépôt) :

| # | Identifiant | Où il apparaît | Propriétaire | Date cible | Preuve attendue |
|---|---|---|---|---|---|
| 1 | Mot de passe du rôle `zylo_office` (base) | littéral `tests/conftest.py` ligne 6, `.github/workflows/ci.yml.disabled` ; à vérifier si le mot de passe figure aussi dans le dump (nom de fichier `zylo_office_...`, contenu non lu) | à nommer (client) | à fixer (client) | attestation écrite de rotation, sans valeur |
| 2 | Compte externe Holykell | `docs/questions/securite/chiffrement-cle-holykell.md` ; présence dans le dump à vérifier par le propriétaire | à nommer (client) | à fixer (client) | attestation écrite, test de connexion réussi par le propriétaire |
| 3 | Mot de passe de démonstration de `scripts/bootstrap_demo_org.py` | script suivi | à nommer (client) | à fixer (client) | attestation écrite ; script modifié pour ne plus porter de valeur |
| 4 | Jetons de session de `e2e-auth/` | `sauvegarde-T004-2026-10-08/artefacts-frontend/e2e-auth/` (hors dépôt) | à nommer (client) | à fixer (client) | révocation attestée, puis suppression du disque |
| 5 | Littéraux de développement `tests/conftest.py` et `.github/workflows/ci.yml.disabled` | suivis | à nommer (client) | à fixer (client) | attestation que le mot de passe est rotaté (1) ; littéraux remplacés par une variable d'environnement |

- **Options** :
  - A. Rotation par l'opérateur, dès que possible, avec un propriétaire nommé et une date attestée par écrit (sans valeur de secret dans le dépôt).
  - B. Rotation différée après la décision de purge : déconseillé, la fenêtre d'exposition s'allonge, et le dépôt est public.
- **Recommandation vérifiée** : option A, en priorité absolue. Vérifications : dépôt public (`gh repo view`) ; `tests/conftest.py` ligne 6 suivi (`git ls-files`) ; dump présent dans l'historique (`git log --all -- backups/`) ; dossier de jetons hors dépôt (`sauvegarde-T004-2026-10-08/artefacts-frontend/e2e-auth/`, `e2e/.auth` absent de l'arbre de travail frontend).
- **Critère de clôture de T-001** : tableau rempli (identifiant, propriétaire, date, preuve), sans aucune valeur de secret, et attestation de la rotation par le propriétaire.
- **État** : En attente de réponse (propriétaires et dates à nommer par le client). Aucune rotation n'a été faite par l'agent (pas d'accès aux systèmes).
