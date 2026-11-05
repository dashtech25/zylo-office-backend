# Routes de consultation des notifications (BE-171)

Lecture seule des tables `notification` (BE-169) et `livraison` (BE-170). Aucune table ni
migration ajoutée. Organisation désignée par l'en-tête `X-Organization-Id` (membre actif
requis, sinon refus du socle). Code : `app/notifications/consultation.py`.

## GET /api/v1/notifications

Notifications dont le compte courant est le destinataire, dans l'organisation active.
Tri : `creeAt` décroissant, puis `id`.

| Paramètre | Obligatoire | Remarque |
|---|---|---|
| `statut` | non | `en_attente`, `supprimee`, `envoyee` ou `echec` ; autre valeur : 422 |
| `limit`, `offset` | non | pagination `PaginationParams` |

Réponses : 200 (page `data` / `meta`).

Champs d'une notification : `id`, `eventId`, `categorieCode`, `statut`,
`motifSuppression` (renseigné pour `supprimee` seulement), `creeAt`.

Isolation tenant : une notification dont l'événement source (`outbox_evenement`) est
rattaché à un autre tenant n'apparaît pas. Un événement plateforme (tenant nul) ne
l'exclut pas.

## GET /api/v1/notifications/{notification_id}/livraisons

Résultats de livraison d'une notification, par `tentativeNo` croissant.

Droits (ordre de décision) :

| Cas | Réponse |
|---|---|
| notification absente, d'un autre tenant, ou événement source d'un autre tenant | 404 `NOTIFICATION_NOT_FOUND` |
| sans `notifications.read`, notification du compte courant | 403 `PERMISSION_DENIED` |
| sans `notifications.read`, notification d'un autre destinataire | 404 `NOTIFICATION_NOT_FOUND` |
| avec `notifications.read`, destinataire hors de l'organisation active | 404 `NOTIFICATION_NOT_FOUND` |
| avec `notifications.read` | 200 : liste de livraisons |

Champs d'une livraison : `id`, `canal` (nom opaque), `tentativeNo`, `resultat`,
`codeErreur`, `prochaineTentativeAt`, `creeAt`. Aucun champ de destinataire ni d'adresse.

## Permission

`notifications.read` : déclarée dans `app/notifications/permissions.py`, créée par
`app/notifications/seed.py`. Aucun rôle ne la porte par défaut (QE-PAR-03).
