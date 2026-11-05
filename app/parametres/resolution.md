# Résolution des paramètres (BE-156)

Module : `app/parametres/resolution.py`. Fonction publique : `resoudre_parametre`.

## Ordre de priorité

utilisateur > module > organisation > plateforme > défaut déclaré (QE-PAR-06).

## Résultat

`ResultatParametre(valeur, niveau, absent)` :
- valeur gagnante avec son niveau ;
- `absent=True` si aucun niveau ni défaut ne fournit de valeur (jamais de valeur inventée).

## Conflit

Deux niveaux renseignés de nature JSON différente lèvent `PARAMETRE_CONFLIT` (409).
Hypothèse provisoire : « incompatible » = nature différente (texte, nombre, booléen,
liste, objet, nul). Le code et la règle sont à confirmer en QE.

## Isolation

Chaque niveau est lu avec son identifiant de portée exact (organisation, utilisateur,
module, `PLATEFORME_SCOPE_ID`). Aucune valeur d'une autre organisation n'est lue.

## Points ouverts

- Ordre de priorité (QE-PAR-06).
- Définition de « incompatible » et code du conflit.
- Valeur de `scopeId` pour la plateforme (constante provisoire) et pour le module.
- Prise en compte de la règle d'application (BE-157) : aujourd'hui, dernière version écrite.
