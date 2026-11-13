# Validation des paramètres (BE-155)

Module : `app/parametres/validation.py`. Registre `REGISTRE` des paramètres déclarés.

## Règle de déclaration

Chaque paramètre est déclaré avec une règle (`RegleValeur`) et un effet
(`EFFETS_PARAMETRE`). Sans règle ou sans effet valide, la déclaration est refusée
(`ValueError`). Une clé ne peut être déclarée qu'une fois.

## Types de règle

| valueType     | Accepte                                  | Options                       |
|---------------|------------------------------------------|-------------------------------|
| booleen       | `bool`                                   | aucune                        |
| entier        | `int` (hors `bool`)                      | minimum, maximum              |
| decimal       | `int` ou `float` (hors `bool`)           | minimum, maximum              |
| texte         | `str`                                    | longueurMaximum               |
| enumeration   | `str` présent dans valeursAdmises        | valeursAdmises (obligatoire)  |

## Refus

`REGISTRE.valider(cle, valeur)` lève `AppError` `SCHEMA_INVALID`, statut 422, dans
deux cas : clé absente du registre, ou valeur hors règle. Le message ne contient
jamais la valeur refusée.

## Points ouverts

- Effets : `immediat`, `prochain_cycle`, `redemarrage` sont provisoires (QE-PAR-04).
- Code HTTP de SCHEMA_INVALID : 422 repris du catalogue (QE-PAR-01).
