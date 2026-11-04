# Gates qualité serveur

Le gate local enchaîne les contrôles serveur et écrit un rapport par révision de source.
Il est exécuté à la main (la CI est désactivée, DOC-001).

## Commande

```bash
python3 scripts/qualite/gates.py                 # révision git HEAD
python3 scripts/qualite/gates.py --revision REV  # identifiant explicite
```

Code de sortie : 0 si le verdict est vert, 1 sinon.

## Fichiers

| Fichier | Rôle |
|---|---|
| `scripts/qualite/gates.py` | Exécution, seuils, validation des exceptions, rapport |
| `scripts/qualite/gates.toml` | Seuils (`[seuils]`) et étapes (`[[etape]]`) |
| `scripts/qualite/exceptions.toml` | Exceptions de lint ou de test |
| `scripts/qualite/rapports/<revision>.json` | Rapport d'une révision |

## Règles

- Un seuil absent de `gates.toml` fait échouer le chargement ; aucune valeur n'est codée.
- Une exception sans `date` ou sans `responsable` est refusée et fait échouer le gate.
- Une étape en échec est relancée `relances_flaky` fois ; une étape qui réussit après
  relance est signalée « instable » dans le rapport.
- Le rapport est écrit même en cas d'échec ; son `verdict` vaut `vert` ou `rouge`.

## Points restants

- Couverture, lint et typage ne sont pas encore mesurés par le gate (valeurs NON DÉFINIES,
  QE-EXP-13).
- Le workflow CI actif reste à créer ; il dépend de la levée de DOC-001.
