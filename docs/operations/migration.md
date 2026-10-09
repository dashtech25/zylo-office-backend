# Migrations de schéma

- **Statut** : en vigueur depuis T-028 (branche `chore/T-028-T-051-migrations-conteneur`).
- **Règle** : le conteneur ne migre jamais. Il ne lance que uvicorn. Le démarrage vérifie
  seulement que la base est à la révision attendue et refuse de démarrer sinon.

## Commandes

Toutes se lancent depuis `/app` dans le conteneur, ou depuis la racine du dépôt avec le venv.

| Commande | Effet | Écrit ? |
|---|---|---|
| `python -m app.cli verifier-revision` | Compare la base à la tête Alembic. Code 1 si différent. | Non |
| `python -m app.cli migrer --dry-run` | Liste les révisions à appliquer et les destructives. | Non |
| `python -m app.cli migrer` | Applique `alembic upgrade head`. Refuse si une migration destructive est en attente. | Oui |
| `python -m app.cli migrer --confirmer-destructives --sauvegarde <fichier>` | Applique aussi les migrations destructives, après sauvegarde. | Oui |
| `python -m app.cli seed` | Enregistre modules et permissions connus. Idempotent. | Oui |
| `python -m app.cli backfill` | Répare les permissions du rôle `owner` seulement. Idempotent. | Oui |

Ordre à respecter à chaque déploiement : `migrer`, puis `seed`, puis `backfill`, puis démarrage du conteneur
(voir `docs/operations/deploiement.md`).

## Migrations destructives

La liste est dans `app/core/migrations.py` (`REVISIONS_DESTRUCTIVES`). Un test (`tests/test_migrations_conteneur.py`)
refait le balayage de `upgrade()` et échoue si une migration destructive n'y figure pas.

Au moment de T-028 :

| Révision | Ce qu'elle détruit |
|---|---|
| `139b3a1a96cb` | colonnes de livraison |
| `7ffb9473d45e` | `TRUNCATE` de `zyloLiquidFuelProduct` (ne jamais rejouer sur une base avec données) |
| `82fd37bd908f` | une colonne (seuils d'alarme cuve) |
| `c4d5e6f7a8b9` | colonnes vestigiales des prix carburant |

Les `drop_table` de `1047562d0691`, `00e30f42d09d` et `0240c128e5de` sont dans `downgrade()` : elles ne sont pas
appliquées par `migrer`, seulement par un retour arrière manuel (voir `docs/operations/retour-arriere.md`).

Procédure obligatoire avant une migration destructive en production :

1. Sauvegarder la base (voir `docs/operations/deploiement.md`, étape 2). Le fichier doit exister et ne pas être vide.
2. Lancer `python -m app.cli migrer --dry-run` et relire la liste.
3. Lancer `python -m app.cli migrer --confirmer-destructives --sauvegarde <chemin du fichier>`.

Sans l'option de confirmation, `migrer` s'arrête avec le code 2 et ne lance rien. La garde ne s'applique pas à une base
sans aucune table (création depuis zéro).

## Création d'une base de test

Sur une base dédiée uniquement, par exemple `zylo_t<NNN>_test` :

```bash
DATABASE_URL=postgresql+asyncpg://<role>@<hote>/zylo_t<NNN>_test .venv/bin/python -m app.cli migrer
```

Ne jamais pointer ces commandes vers `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid` ou `zylo_recette`.
