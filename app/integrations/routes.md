# Routes des connecteurs (BE-162)

Code : `app/integrations/router.py`. Registre sous-jacent : `app/integrations/registre.py` (BE-160).
Montées sous `/api/v1`. Organisation courante : en-tête `X-Organization-Id`.

| Méthode et chemin | Droit | Réussite | Erreurs |
|---|---|---|---|
| `GET /connecteurs` | `integrations.read` | `200` liste (tenant et globaux) | `403` PERMISSION_DENIED |
| `POST /connecteurs` | `integrations.manage` | `201`, état `création` | `403` PERMISSION_DENIED |
| `POST /connecteurs/{id}/transitions` | `integrations.manage` | `200` | `409` CONNECTEUR_TRANSITION_INTERDITE ; `404` hors tenant |
| `PUT /connecteurs/{id}/configuration` | `integrations.manage` | `200` (aujourd'hui inatteignable) | `409` CONNECTEUR_CONFIGURATION_NON_VALIDEE |

Corps : `POST` `{"nom"}` ; transition `{"cible": "activé" | "suspendu" | "révoqué"}` ;
configuration `{"version": int >= 1}`.

Réponse : `id`, `nom`, `portee`, `etat`, `versionConfiguration`, `createdAt`, `updatedAt`.
Aucun champ de secret ni de configuration brute.

Points ouverts :
- QE-BE162-01 : `require_permission` renvoie `permission_denied` (minuscules) ; la route
  utilise `exiger_permission` pour respecter le code `PERMISSION_DENIED` de la définition.
  Recommandation appliquée ; à unifier dans `app/rbac` si la convention change.
- QE-BE162-02 : aucun validateur de configuration de connecteur. `validee` vaut `False`,
  donc le PUT refuse toujours (échec fermé). Recommandation : brancher le validateur
  quand il existe.
- QE-BE162-03 : la route ne crée que des connecteurs de portée `tenant`.
