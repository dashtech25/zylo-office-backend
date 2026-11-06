# Mise à jour du profil organisation (BE-104)

Route : `PATCH /api/v1/organizations/{organization_id}` (`app/identity/router.py`),
logique dans `app/identity/service.py::update_organization`.

Cette route est posée par BE-186 ; BE-104 en fixe le contrat de refus et de
conflit, décrit ci-dessous.

## Corps accepté

| Champ | Rôle |
|---|---|
| `name` | Nom affiché (1 à 255 caractères). Seul champ modifiable : `slug`, `status` et `tenantId` ne le sont pas. |
| `expectedVersion` (ou alias `version`) | Version relue précédemment. Absente : écriture sans condition. |

Tout autre champ du corps donne `400` (code `field_not_allowed`) et ne modifie rien.
La liste est `CHAMPS_PROFIL_ORGANISATION` dans `app/identity/router.py`.

## Réponses

| Cas | Statut | Effet |
|---|---|---|
| Version courante, champ autorisé | 200 | `name` mis à jour, `version` +1, entrée d'audit |
| `expectedVersion` obsolète | 409 (`version_conflict`) | Aucune écriture, aucune trace d'audit |
| Champ non listé | 400 (`field_not_allowed`) | Aucune écriture |
| Sans droit `organization.update` | 403 | Aucune écriture |
| Organisation hors portée (en-tête différent du chemin, ou non membre) | 404 | Aucune écriture |

Le motif interne n'apparaît pas dans la réponse : seul le code et un message
générique sont renvoyés.

## Audit

La modification de `name` (champ sensible) écrit un événement `AuditEvent` d'action
`identity.organization.update`, avec `changes = {"name": {"before", "after"}}`.

## Écarts avec la fiche BE-104

- Droit : la fiche écrit `org:profile:manage`. La route porte déjà
  `organization.update` (décision BE-186 sur la même route, format
  `domaine.entite.action`). Un second code pour la même action aurait créé un doublon :
  `organization.update` est retenu.
- Champs modifiables et champs sensibles (QE-POR-18, non tranchés dans la fiche) :
  `name` seul, qui est aussi le seul champ sensible. Recommandation la plus simple,
  appliquée sans attendre.
- Nom de fonction : la fiche cite `update_organization_profile` ; le service garde le
  nom `update_organization` (posé par BE-186).
- Le rejet des champs inconnus est fait sur le JSON brut dans la route, car le schéma
  Pydantic ignore ces champs et l'erreur de validation standard donne 422, pas 400.
