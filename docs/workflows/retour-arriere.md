# Retour arrière

Trois niveaux, à traiter séparément : le code, le schéma, les données.

## 1. Code

- Annuler par un nouveau commit (`git revert <commit>`) sur la branche de tâche.
- Interdit sans accord écrit : `git reset --hard`, `git push --force`, réécriture de `remy`.
- Un changement de comportement derrière un module peut être désactivé en désactivant le module pour l'organisation (`modules_registry`), sans toucher au code.

## 2. Schéma (Alembic)

- `alembic downgrade -1` pour revenir à la révision précédente. Chaque révision doit avoir un downgrade écrit.
- Points d'attention connus :
  - rôles par module (ADR 0002) : le downgrade supprime `role.moduleCode` ; les rattachements ne sont pas restaurés ;
  - chiffrement Holykell (ADR 0005) : après `--effacer-clair`, le downgrade exige la clé, sinon il échoue sans rien modifier.

## 3. Données

- Restauration depuis une sauvegarde : `./scripts/restore.sh backups/<fichier> <base_cible>`. Toujours dans une base cible nouvelle, jamais par écrasement d'une base réelle sans accord écrit.
- Les dumps sont hors dépôt (`backups/` ignoré par git).
- Après restauration : vérifier les migrations (`alembic current`) et les comptes chiffrés (lecture d'un compte).

## Décision

Qui décide du retour arrière : le commanditaire, par écrit, pour tout ce qui touche la production. Consigner l'incident et la décision dans la fiche de tâche et, si la cause est une décision de conception, dans une question de `docs/questions/`.
