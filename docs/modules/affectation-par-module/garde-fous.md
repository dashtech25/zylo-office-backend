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

## Projection de l'accès effectif au catalogue

`GET /api/v1/modules/organizations/{organization_id}` conserve `status` comme état d'installation et ajoute trois champs d'accès calculés côté serveur :

- `accessState` : `not_configured`, `active`, `inactive`, `expired`, `blocked` ou `unknown`;
- `canActivate` : même décision d'entitlement que la garde d'activation;
- `canOpen` : entitlement autorisé **et** installation `active` ou `trial`.

Le dashboard et le launcher doivent filtrer par `canOpen`, pas déduire l'accès de `status`. Le catalogue peut proposer l'activation seulement si `canActivate=true`; une installation active mais restreinte reste désinstallable.

**Compatibilité existante, non décision commerciale :** uniquement en l'absence de toute ligne `SubscriptionEntitlement`, la garde conserve l'accès legacy. L'API expose `accessState=not_configured` et `canActivate=true` pour refléter exactement ce comportement; cela ne signifie pas qu'un plan, un paiement ou un droit commercial est configuré. Toute ligne explicite mais inconnue, ou associée à un statut d'abonnement non reconnu, échoue désormais de manière fermée (`unknown`, `canActivate=false`). La sélection retient l'entitlement le plus récent dont `startsAt` est déjà atteint; une ligne future ne masque donc pas un entitlement en vigueur. Si seules des lignes futures existent, l'accès reste refusé jusqu'à leur date d'effet.

**Recommandation à arbitrer avant les paiements réels :** établir les entitlements explicites des offres et la règle de transition des organisations legacy; ensuite seulement évaluer le passage à un refus par défaut pour les modules payants. Cette projection ne change pas Q-04/Q-05 et n'active aucun débit.
