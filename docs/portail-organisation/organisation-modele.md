# Modèle organisation, tenant, appartenance et invitation (BE-100)

Référence : `implementation-backend/tasks-portail-organisation.md`, section BE-100.
Code : `app/identity/models.py`, migration `be100a0b1c2d`.

## Tables

| Table | Propriétaire | Rôle dans BE-100 |
|---|---|---|
| `organization` | BE-002 | Lue telle quelle, aucune colonne ajoutée. |
| `organization_user` | BE-004 (ex-`organizationUser`) | Renommée, colonne `status` ajoutée (défaut `active`). |
| `tenant` | BE-100 | Créée. Une ligne au plus par organisation. |
| `invitation` | BE-100 | Créée. Destinataire identifié, statut borné. |

## Contraintes

- `organization_user` : unicité sur (`organizationId`, `userId`), héritée de BE-004. La base refuse un second rattachement identique.
- `tenant` : unicité sur `organizationId`. Un second tenant pour une organisation est refusé.
- `invitation.status` : `CHECK` limité à `pending`, `accepted`, `expired`, `revoked` (contrainte `ck_invitation_status`).
- Aucune colonne `parentId` sur ces tables (QE-POR-05).

## Décisions

- Renommage `organizationUser` vers `organization_user` : décision QE-POR-30. Le nom de contrainte `uq_organizationUser_org_user` est conservé.
- `invitation.recipientUserId` identifie l'identité invitée ; seule cette identité accepte (QE-POR-24, appliqué par BE-105).
- `invitation.roleId` est facultatif, comme dans `organizationInvitation` (BE-012).
- Les colonnes utilisent `status`, `createdByUserId` et `userId` pour suivre la convention du code existant.

## Point de vigilance

`organizationInvitation` (BE-012) et `invitation` (BE-100) coexistent. `organizationInvitation` vise une adresse e-mail sans compte ; `invitation` vise une identité existante. Leur fusion éventuelle relève d'une décision à prendre avant BE-105.

## Hors périmètre

- Aucune route : les endpoints du portail arrivent avec BE-102 et suivants.
- La garde de portée est dans BE-101.
- `assert_active_membership` ne lit pas encore `organization_user.status` : la présence de la ligne reste la seule preuve d'accès.
