# Demande et statut de vérification d'organisation (BE-103)

Routes (domaine organisation, sous `/api/v1/organizations`) :

- `GET /{organization_id}/verification` : statut du dernier cas de l'organisation du chemin, ou `null` s'il n'en existe aucun (200).
- `POST /{organization_id}/verification` : dépose une demande ; le cas est créé en `verification_pending` (201). Corps vide : tout champ, dont `statut`, est refusé en 422.

Réponse d'un cas : `id`, `organizationId`, `statut`, `createdAt`, `updatedAt`. Le motif interne (`motifInterne`) n'est jamais renvoyé.

Permissions (accordées au propriétaire à la création de l'organisation, via `OWNER_DEFAULT_PERMISSIONS`) :

- `organization.verification.read` (action `portail.verification.lire`) ;
- `organization.verification.submit` (action `portail.verification.deposer`).

## Codes de refus

| Cas | Code HTTP | Code d'erreur |
| --- | --- | --- |
| Session absente ou invalide | 401 | - |
| Permission absente (membre sans rôle) | 403 | `permission_denied` |
| Organisation hors appartenance, inexistante ou mal formée | 404 | `organization_not_found` |
| Champ non prévu dans le corps du dépôt (ex. `statut`) | 422 | validation |

## Table

`verification_case` (migration `b103c0de0103`, downgrade écrit) : `id`, `organizationId` (FK `organization.id`, index), `statut` contraint à `verification_pending`, `verification_required`, `verified`, `rejected`, `motifInterne` (texte, nullable), `createdAt`, `updatedAt`.

## Écarts et décisions (QE-POR-01, QE-POR-07)

- Politique de dépôt et de lecture NON DÉFINIE : seul le propriétaire reçoit les deux permissions. La recommandation « Owner ou Admin » n'est pas appliquée au rôle Admin dans ce lot.
- Aucune route ne fixe `verified` ni `rejected` : la décision est interne et hors de ce lot. Le client ne peut donc pas s'accorder le statut.
- Un second dépôt pendant qu'un cas est en attente n'est ni refusé ni fusionné (politique non définie).
- Codes de refus conformes à la fiche (401, 403, 404). Le refus d'un corps non prévu est 422, comme le reste de l'API.
