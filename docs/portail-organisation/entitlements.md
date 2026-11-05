# Entitlements et modules activés de l'organisation (BE-107)

Route : `GET /api/v1/organizations/{organization_id}/entitlements`.
Implémentation : `app/billing/lecture_router.py` (`list_organization_entitlements`), schéma
`EntitlementsOrganisationResponse` dans `app/billing/schemas.py`.

## Réponse

La réponse est un objet à deux groupes distincts :

| Groupe | Contenu | Critère |
|---|---|---|
| `included` | droits accordés par le plan de l'organisation | `sourceAttribution` = `offre` |
| `addOns` | tous les autres droits | `achat_additionnel`, `essai`, `allocation_admin`, `usage_reel` |

Chaque ligne a la forme `OrganizationEntitlementResponse` : `id`, `moduleCode`, `entitlementCode`,
`scope`, `source`, `state`, `quotaLimit`, `quotaUnit`, `periodStart`, `periodEnd`, `stateVersion`.
L'état (`state`) est calculé à la lecture (`app/billing/entitlements.py::calculer_entitlements`).

## Droits et refus

- Permission : `organization.entitlement.read` (`ORGANIZATION_ENTITLEMENT_READ`), portée organisation.
- Organisation hors portée ou sans appartenance active : 404 `organization_not_found`, aucune donnée.
- Membre sans la permission : 403.
- Pas d'écriture : `POST`, `PATCH` et `DELETE` sur ce chemin répondent 405 et ne modifient rien.

## Écarts avec la fiche BE-107

- Permission : la fiche écrit `entitlement:read`. Le dépôt utilise le format `domaine.entite.action`
  et la permission existante `organization.entitlement.read` (BE-045) est réutilisée.
- Chemin partagé avec BE-045 : la route existait déjà. Sa réponse passe de liste à objet à deux groupes ;
  les tests de BE-045 lisent désormais la clé `included`.
- Modules activés (BE-022) : non exposés par cette route ; la fiche n'en fait pas un critère d'acceptation.
- Add-ons : toute source autre que `offre` est un add-on, y compris essai et allocation admin.

## Tests

`tests/test_be107_entitlements_lecture.py` (CA-1 à CA-4) et `tests/test_be045_entitlements_organisation.py`.
