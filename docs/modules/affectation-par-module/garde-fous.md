# Garde-fous de l'affectation par module

Toutes les vérifications ont lieu AVANT toute écriture : une demande refusée ne laisse aucune ligne.

| Garde-fou | Résultat | Code |
|---|---|---|
| Cible membre de l'organisation | 404 | `user_not_member` |
| Compte actif (`User.status = active`) pour affecter ou changer | 409 | `user_not_active` |
| Rôle de l'organisation (sinon 404 par `get_role`) | 404 | `role_not_found` |
| Rôle rattaché à un module (pas le rôle `owner`, transverse) | 422 | `role_not_module_role` |
| Rôle du module demandé (pas celui d'un autre module) | 422 | `role_module_mismatch` |
| Module actif pour une affectation (le retrait reste permis) | 409 | `module_not_active` |
| Permissions du rôle compatibles avec le module | 422 | `permission_module_mismatch` |
| Non-élévation : le demandeur possède chaque permission accordée | 403 | `privilege_escalation_denied` |
| Non-retrait : le demandeur possède chaque permission de l'ancien rôle qu'il retire | 403 | `module_role_removal_denied` |
| Dernier administrateur : le seul détenteur d'une permission `*.manage` du module ne peut être rétrogradé ni retiré | 409 | `last_module_admin` |
| Retrait sans rôle sur le module | 404 | `module_role_not_assigned` |
| Un seul rôle par module et par utilisateur : un changement remplace, il ne cumule pas | - | - |

## Verrou

La ligne d'appartenance de la cible est verrouillée (`FOR UPDATE`) pendant un changement : deux demandes
concurrentes pour le même membre sont sérialisées.

## Audit

Chaque changement effectif écrit une ligne dans `auditLog` :
`rbac.moduleRole.assign` (premier rôle), `rbac.moduleRole.change` (remplacement),
`rbac.moduleRole.unassign` (retrait). Un changement vers le rôle déjà affecté n'écrit rien.

## Hors périmètre

- Le « dernier propriétaire » de l'organisation relève de T-019 (rôle transverse, hors routes par module).
- Le quota de création d'organisation relève de T-019 (valeur fixée par le client).
