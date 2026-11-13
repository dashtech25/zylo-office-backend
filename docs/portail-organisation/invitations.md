# Invitations d'organisation (BE-105)

Source : `implementation-backend/tasks-portail-organisation.md`, section BE-105.
Code : `app/identity/invitations_portail.py` (service), `app/identity/invitations_portail_router.py` (routes).
Tests : `tests/test_be105_invitations_portail.py`.

## Routes

| Méthode et chemin | Portée | Permission ou règle | Succès |
|---|---|---|---|
| `POST /api/v1/organizations/{organization_id}/invitations` | `OrgScope` (BE-101) | action `portail.invitation.creer`, permission `organization.members.invite` | 201, invitation `pending` |
| `POST /api/v1/organizations/{organization_id}/invitations/{invitation}/accept` | session seule (le destinataire n'est pas encore membre) | identité égale au destinataire | 200, invitation `accepted` |

Corps de création : `recipientUserId` (obligatoire) et `roleId` (facultatif).

## Codes de refus

| Cas | Statut | Code |
|---|---|---|
| Pas de session | 401 | pas de code métier (refus de `get_current_user`) |
| Hors appartenance, organisation inconnue ou identifiant mal formé | 404 | `organization_not_found` |
| Membre sans `organization.members.invite` | 403 | `permission_denied` |
| Rôle absent de l'organisation | 404 | `role_not_found` |
| Rôle Owner proposé (QE-POR-04) | 403 | `owner_role_forbidden` |
| Destinataire inexistant ou supprimé | 404 | `user_not_found` |
| Destinataire déjà membre | 409 | `already_member` |
| Invitation déjà ouverte pour ce destinataire | 409 | `invitation_already_pending` |
| Acceptation par une autre identité | 403 | `invitation_recipient_mismatch` |
| Invitation absente de l'organisation | 404 | `invitation_not_found` |
| Invitation `expired`, `revoked` ou `accepted` | 409 | `invitation_not_open` |
| Invitation `pending` dont l'échéance est passée | 409 | `invitation_expired` |

Un refus ne modifie jamais le statut de l'invitation et n'écrit aucune ligne.

## Effets

- Création : ligne `invitation` (`status = pending`, `expiresAt = maintenant + USER_INVITATION_TTL_HOURS`,
  `createdByUserId` = membre qui invite), événement `MemberInvited` écrit dans l'outbox, entrée d'audit.
- Acceptation : appartenance `organization_user` (BE-004) créée si absente, rôle proposé attribué dans
  l'organisation (`userRole`, sans portée ressource) s'il existe, statut `accepted`, événement
  `InvitationAccepted`, entrée d'audit. Le tout dans une seule transaction.

## Écarts avec la fiche (recommandations appliquées)

- Permission : la fiche écrit `members:manage`, qui n'existe pas dans le code. Le format
  `domaine.entite.action` (CLAUDE.md) et la permission d'invitation déjà seedée
  (`organization.members.invite`, QE-SOC-06) sont retenus.
- Destinataire : désigné par `recipientUserId` (identité existante), conformément à la colonne
  `invitation.recipientUserId` de BE-100 (QE-POR-24). Pas d'envoi par adresse e-mail dans ce lot.
- Table : aucune migration. La table `invitation` (colonnes `status`, `roleId`, `expiresAt`,
  `createdByUserId`) est créée par BE-100.
- Durée : `USER_INVITATION_TTL_HOURS` (valeur de configuration existante), sans nouveau réglage.
- Noms d'événements : `MemberInvited` (fiche) ; `InvitationAccepted` pour l'acceptation (la fiche ne le nomme pas).
- Acceptation d'une invitation `pending` échue : refusée en 409 sans passer le statut à `expired`
  (la mise à jour de statut relève d'un traitement d'échéance, hors de ce lot).
- Ne pas confondre avec `organizationInvitation` (BE-012, invitation par adresse e-mail) ni avec
  `userInvitation` (activation d'un compte créé par une organisation).
