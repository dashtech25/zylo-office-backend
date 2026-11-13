# Garde de portée organisation (BE-101)

Code : `app/rbac/portee_organisation.py`. Tests : `tests/test_be101_garde_portee.py`.
Définition : `implementation-backend/tasks-portail-organisation.md`, section BE-101.

## Règle

Toute route `/api/v1/organizations/{organization_id}/...` du portail :

1. résout sa portée (`OrgScope`) par `require_org_scope`, depuis le **chemin** seul ;
2. vérifie la session (401) puis l'appartenance active à cette organisation (404) ;
3. passe, si elle agit, par `exiger_action(action)` : l'action doit figurer dans
   `POLITIQUE_PORTAIL` (sinon 403 `policy_denied`), et l'utilisateur doit avoir la
   permission associée (sinon 403 `permission_denied`).

L'identifiant d'organisation envoyé dans l'en-tête `X-Organization-Id` ou dans le corps
est un sélecteur non fiable : il n'est pas lu par la garde et ne modifie pas la portée.

## Réponses

| Cas | Statut | Code |
|---|---|---|
| Pas de session ou jeton invalide | 401 | `authentication_required` (via `get_current_user`) |
| Organisation étrangère, inexistante, supprimée ou identifiant mal formé | 404 | `organization_not_found` (corps identique) |
| Action absente de la politique | 403 | `policy_denied` |
| Permission absente pour l'action | 403 | `permission_denied` |

## Politique

`POLITIQUE_PORTAIL` (dictionnaire action -> permission) est vide à la livraison de BE-101 :
toute action est refusée par défaut. Chaque tâche de route du portail (BE-102 et suivantes)
inscrit son action et sa permission. Aucune permission n'est accordée implicitement.

## Décisions

- Code 404 pour toute ressource hors portée, y compris identifiant mal formé (QE-POR-01).
- Refus de la politique distinct du refus de permission (`policy_denied` / `permission_denied`),
  pour distinguer une route non inscrite d'un droit manquant.
- Distinct de BE-009 (`app/rbac/guards.py`) : pas de lecture d'en-tête, pas de comparaison
  chemin/en-tête, politique propre au portail (QE-POR-27).
