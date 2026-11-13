# Exports de données asynchrones (BE-117)

Routes montées sous `/api/v1/organizations/{organization_id}/exports` (QE-POR-09).

| Méthode | Chemin | Effet | Codes de refus |
|---|---|---|---|
| POST | `/exports` | Demande, 202 `export_requested` | 401, 403 `permission_denied`, 404 |
| GET | `/exports/{export}` | Statut ; `lienTelechargement` seulement à `ready` | 401, 403, 404 `export_not_found` |
| GET | `/exports/{export}/download` | Contenu, journalisé | 401, 403, 404, 409 `export_not_ready`, 410 `export_expired` |

## Cycle de vie

- `export_requested` : la demande est acceptée. Le traitement est confié à un traitement de fond
  (`traiter_export`), jamais fait dans la requête.
- `ready` : le contenu (liste des membres de l'organisation) est produit, `expiresAt` = maintenant
  + `EXPORT_EXPIRATION_SECONDS`.
- `expired` : `expiresAt` est atteint. Le téléchargement est refusé en 410 et le contenu est purgé.

## Configuration

Durée de vie lue dans `settings.EXPORT_EXPIRATION_SECONDS` (QE-POR-15). Sans valeur, le traitement
ne produit rien : l'export reste `export_requested`, sans lien ni échéance (CA-5). Aucune durée
n'est codée en dur.

## Droits et isolation

- Permission `data.export`, accordée au propriétaire (OWNER_DEFAULT_PERMISSIONS). Action de la
  politique du portail : `portail.export.demander`, `portail.export.lire`,
  `portail.export.telecharger` (rbac/portee_organisation.py).
- Toute lecture est filtrée par l'organisation du chemin ; un export d'une autre organisation répond
  comme un export absent (404).
- Chaque demande et chaque téléchargement sont journalisés (`data.export.request`,
  `data.export.download`).

## Événements

`ExportRequested` (après commit de la demande), `ExportReady` (après passage à `ready`),
`ExportExpired` (à la première purge). Publiés via `app.shared.events.publish`.

## Écarts avec la fiche

- Permission écrite `data.export` (format `domaine.action`), et non `data:export`.
- Traitement de fond par `BackgroundTasks` : pas de file de travail durable.
- Périmètre unique `membres` ; pas de corps de requête.
- Coexistence avec `export_jobs` (BE-243) et `job` (BE-213), volontairement distinctes.
