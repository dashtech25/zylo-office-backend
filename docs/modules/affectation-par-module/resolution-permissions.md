# Résolution des permissions par module

Une seule fonction décide : `app/rbac/service.py::user_has_permission` (deny prioritaire, refus par défaut).
`app/rbac/module_rights.py::user_has_module_permission` l'enveloppe et exige, dans l'ordre :

1. le module est actif pour l'organisation (`active` ou `trial`) ;
2. la permission existe dans le catalogue et appartient au module, ou au socle partagé
   (`SHARED_PERMISSION_CODES` dans `app/shared/permissions.py`) ;
3. le moteur central accorde la permission à l'utilisateur dans l'organisation.

Une permission inconnue, hors module ou module inactif donne `False` sans erreur : un appelant ne peut pas
sonder le catalogue par le message d'erreur.

## Droits effectifs listés

`effective_rights_by_module` liste, par module du catalogue, les rôles de module de l'utilisateur et ses
permissions. Un module inactif liste ses rôles mais aucune permission. Le socle partagé est listé à part,
pour ne pas laisser croire qu'un rôle de module l'a accordé.

## Propriétaire

Le rôle `owner` est transverse (`moduleCode` NULL). Il reçoit les permissions de chaque module activé
(`grant_module_permissions_to_owner`) : exception déclarée dans `docs/architecture/securite/roles-par-module.md`.
Les routes par module ne peuvent ni l'affecter ni le retirer.

## Prévisualisation

`previsualiser_changement_module` applique les mêmes vérifications que l'écriture, sans rien écrire.
Un refus métier (403, 409, 422) est renvoyé dans `refusal`, pas levé ; une cible inexistante reste une erreur 404.
