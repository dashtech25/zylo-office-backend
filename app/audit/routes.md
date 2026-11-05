# Routes de consultation du journal d'audit (BE-172)

Lecture seule de la table unique `audit_event` (BE-007). Aucune table ni écriture
ajoutée. Organisation désignée par l'en-tête `X-Organization-Id`.

## GET /api/v1/audit/evenements

Recherche paginée. Tri : `createdAt` décroissant.

| Paramètre | Obligatoire | Correspond à | Remarque |
|---|---|---|---|
| `dateDebut` | oui | `createdAt >=` | datetime ISO 8601 |
| `dateFin` | oui | `createdAt <=` | antérieure à `dateDebut` : 422 |
| `sujetType` | oui | `entityType` | non vide |
| `sujetId` | non | `entityId` | UUID |
| `acteurId` | non | `actorUserId` | UUID |
| `action` | non | `action` | égalité exacte |
| `limit`, `offset` | non | pagination | `PaginationParams` |

Réponses : 200 (page `data` / `meta`), 422 (période ou sujet absent), 403
`permission_denied` (sans `audit.log.view` ni portée visible).

## GET /api/v1/audit/evenements/{event_id}

Détail d'un événement de l'organisation courante.

Réponses : 200, 404 `audit_event_not_found` (inexistant ou autre tenant), 403
`permission_denied` (événement à visibilité restreinte sans `audit.restricted.view`).

## Champs de réponse

`id`, `actorUserId`, `entityType`, `entityId`, `action`, `reason`, `summary`,
`changes`, `scopeResourceType`, `scopeResourceId`, `result`, `request_id`,
`visibility`, `createdAt`.

## Droits et hypothèses

- Permission de lecture : `audit.log.view` (la définition cite `audit.read` ; on
  réutilise le code existant, BE-033).
- Visibilité restreinte (QE-PAR-16, hypothèse) : `visibility = "restreinte"`
  exige `audit.restricted.view`. En recherche, ces événements sont retirés sans
  la permission.

Code : `app/audit/router.py`, `app/audit/consultation.py`, `app/audit/schemas.py`.
