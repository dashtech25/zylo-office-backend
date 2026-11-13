# Demande de support client (BE-118)

Route (domaine support, sous `/api/v1/organizations`) :

- `POST /{organization_id}/support-requests` : ouvre une demande de support pour l'organisation du chemin (201).

Corps : `contexte` (facultatif, objet non secret). Tout autre champ, dont `createdBy` et les pièces jointes, est ignoré et n'est jamais stocké.

Réponse : `id`, `organizationId`, `statut` (`open` à la création), `createdBy` (utilisateur authentifié), `createdAt`.

Événement : `SupportRequestCreated` (version de schéma 1), écrit dans l'outbox dans la même transaction. Son payload ne porte que `supportRequestId` et `statut` ; le contexte reste en base.

Permission : `support.request.create`, accordée au propriétaire à la création de l'organisation (recommandation appliquée : la fiche écrit `support:create`).

## Codes de refus

| Cas | Code HTTP | Code d'erreur |
| --- | --- | --- |
| Session absente ou invalide | 401 | - |
| Permission absente | 403 | `permission_denied` |
| Organisation hors appartenance, inexistante ou mal formée | 404 | `organization_not_found` |
| Mot de passe ou token dans `contexte` | 400 | `secret_context_refused` |

Table : `support_request` (migration `a118c0de0118`, downgrade écrit). Statuts possibles : `open`, `in_progress`, `resolved` ; seul `open` est produit ici.
