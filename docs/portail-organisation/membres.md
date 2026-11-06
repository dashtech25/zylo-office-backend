# Membres de l'organisation du portail (BE-106)

Source : `implementation-backend/tasks-portail-organisation.md`, section BE-106.
Code : `app/identity/membres_portail_router.py` (routes), `app/identity/membres.py` (retrait),
`app/rbac/affectation_membres.py` (changement de rôle), `app/identity/evenements_membres.py` (enveloppes).
Tests : `tests/test_be106_membres_portail.py`.

## Routes

| Méthode et chemin | Portée | Action et permission | Succès |
|---|---|---|---|
| `GET /api/v1/organizations/{organization_id}/members` | `OrgScope` (BE-101) | `portail.membres.lire` ; `organization.members.read` | 200, liste des membres avec leurs rôles |
| `POST /api/v1/organizations/{organization_id}/role-changes` | `OrgScope` | `portail.membre.changer_role` ; `rbac.role.manage` | 200, membre après changement |
| `DELETE /api/v1/organizations/{organization_id}/members/{membership}` | `OrgScope` | `portail.membre.retirer` ; `organization.members.remove` | 204 |

Corps de `role-changes` : `membershipId` (identifiant de `organization_user`, obligatoire) et
`roleIds` (ensemble cible des rôles transverses du membre, liste pouvant être vide).

`{membership}` est l'identifiant de l'appartenance (`organization_user.id`), et non celui de l'utilisateur.

## Codes de refus

| Cas | Statut | Code |
|---|---|---|
| Pas de session | 401 | refus de `get_current_user` |
| Hors appartenance, organisation inconnue ou identifiant mal formé | 404 | `organization_not_found` |
| Membership absent de l'organisation du chemin (y compris celui d'une autre organisation) | 404 | `membership_not_found` |
| Membre sans la permission de l'action | 403 | `permission_denied` |
| Rôle absent de l'organisation | 404 | `role_not_found` |
| Rôle de module proposé | 422 | `module_role_not_allowed` |
| Rôle propriétaire attribué ou retiré par un non-propriétaire | 403 | `owner_assignment_forbidden` |
| Retrait ou rétrogradation du dernier propriétaire actif | 409 | `last_owner` |
| Retrait d'un propriétaire par un non-propriétaire | 403 | `owner_removal_forbidden` |

Un refus n'écrit rien : les contrôles précèdent toute écriture, et le membership reste intact.

## Effets

- Changement de rôle : attributions et retraits de `userRole` dans une seule transaction, une entrée
  d'audit par rôle attribué ou retiré (`rbac.role.assign`, `rbac.role.unassign`), et un événement
  `RoleChanged` dans l'outbox (payload : `organizationId`, `membershipId`, `userId`, `roleIds`,
  `rolesAttribues`, `rolesRetires`). Aucun changement, aucun événement.
- Retrait : suppression de `organization_user` et des `userRole` de l'organisation, une entrée d'audit
  (`identity.member.remove`) et un événement `Removed` dans l'outbox, dans la même transaction.
- Lecture : aucune écriture.

## Écarts avec la fiche

- Permissions : la fiche écrit une seule permission `members:manage`, absente du code. Les permissions
  existantes sont utilisées par action (voir tableau ci-dessus). `rbac.role.manage` est celle que BE-015
  exige déjà pour changer les rôles d'un membre.
- Modèle : la fiche cite une table `membership (role, statut)`. Le code porte l'appartenance dans
  `organization_user` et les rôles dans `userRole`. Aucune migration n'est ajoutée.
- Routes : le chemin `role-changes` suit la fiche ; le corps est `membershipId` plus `roleIds`
  (ensemble cible), et non une paire membre/rôle unique.
- Événements : `RoleChanged` est écrit par `replace_member_roles`, et `Removed` par `remove_member`.
  Ces deux services sont aussi appelés par les routes existantes de BE-014 et BE-015 ; elles émettent
  donc désormais les mêmes événements.
- Segment `current` : `GET /organizations/current/members` et `DELETE /organizations/current/members/{user_id}`
  restent servis par le routeur `/current` (monté avant ce routeur) ; le segment `current` n'atteint
  jamais le routeur du portail.
