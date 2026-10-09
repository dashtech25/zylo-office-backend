# Migrations de schéma et scripts de données

## Règles

- Une modification de schéma = une révision Alembic (`alembic revision -m "..."`), dans `alembic/versions/`. Le downgrade est écrit et testé.
- Les migrations ne s'exécutent pas au démarrage de l'application (décision en attente : [`migrations-au-demarrage.md`](../questions/architecture/migrations-au-demarrage.md) ; tâche T-028).
- Une migration additive est préférée : nouvelle colonne nullable, puis remplissage, puis contrainte.
- Un script de données ne modifie rien sans `--dry-run` préalable. Il est idempotent et affiche des compteurs, jamais de valeur sensible.

## Procédure

1. Sauvegarde : `./scripts/backup.sh` (dump local ; le dump n'est jamais versionné).
2. Sur une base de test (`zylo_t<NNN>_test`) : `alembic upgrade head`, puis `alembic downgrade -1`, puis `alembic upgrade head`.
3. Script de données, si besoin, en deux temps :
   - `--dry-run` : compte ce qui serait modifié, n'écrit rien ;
   - exécution réelle, sans l'option destructive (ex. `--effacer-clair` pour le chiffrement Holykell, uniquement sur accord écrit).
4. Vérification après exécution : lecture d'un échantillon, contrôle de synchronisation le cas échéant.

## Exemples réels

- Rôles par module : `scripts/backfill_module_roles.py [--dry-run]` (ADR 0002).
- Chiffrement Holykell : `scripts/chiffrer_mots_de_passe_holykell.py --dry-run`, puis sans option, puis `--effacer-clair` après accord écrit (ADR 0005, [`secrets.md`](../architecture/securite/secrets.md)).

## Retour arrière

Voir [`retour-arriere.md`](retour-arriere.md). Une migration qui supprime des données n'a pas de downgrade complet : le noter dans sa révision et dans la fiche de tâche.
