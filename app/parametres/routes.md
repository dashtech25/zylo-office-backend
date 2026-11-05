# Routes des paramètres (BE-158)

Module : `app/parametres/routes.py`. Préfixe : `/api/v1/parametres`. Tenant : en-tête
`X-Organization-Id` (contexte serveur). Seule la portée `organisation` est servie.

| Méthode | Chemin | Permission | Succès | Erreurs principales |
|---|---|---|---|---|
| GET | `/{scope_kind}/{scope_id}` | `settings.read` | 200, liste `cle`, `valeur`, `source`, `version` | 403, 404 hors tenant, 409 PARAMETRE_CONFLIT |
| PUT | `/{scope_kind}/{scope_id}/{cle}` | `parametres.setting.apply` | 200, `cle`, `version` | 403, 404, 409 VERSION_CONFLICT, 422 |
| POST | `/{scope_kind}/{scope_id}/{cle}/restaurations` | `parametres.setting.apply` | 200, `cle`, `version` | 403, 404, 409, 422 (version source inconnue) |

En-tête optionnel `X-Expected-Version` : version appliquée attendue. Un écart renvoie 409
sans écriture. Le corps d'écriture exige `reason` non vide. Un paramètre `sensitive` est
masqué (`[masqué]`) dans la liste.

Points ouverts : QE-PAR-02 (forme des routes, nom de l'en-tête), QE-PAR-03 (nom de la
permission d'écriture ; la définition cite `settings.write`, BE-157 emploie
`parametres.setting.apply`). Détail des contrôles : docstring de `app/parametres/routes.py`.
