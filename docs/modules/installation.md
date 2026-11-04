# Installation technique d'un module (BE-047)

Une organisation installe une version publiée d'un module par
`POST /api/v1/organizations/{orgId}/modules/{moduleId}/installations`, avec l'en-tête
`Idempotency-Key` (obligatoire) et le corps `{"moduleVersionId", "stateVersion"}`.
`GET .../installations/{operationId}` relit une opération (résultat incertain).

## Séquence

`not_installed -> preflight -> provisioning -> installed`, journalisée dans
`module_state_transitions` (sujet `tenant_module`, BE-041). En cas d'échec du provisionnement :
`provisioning -> failed` avec `lastErrorCode = MODULE_PROVISIONING_FAILED`. Depuis `failed`, le
passage à `active` est refusé (BE-048 le gérera).

## Refus (sans ligne créée)

| Cas | Code HTTP | Code d'erreur |
|---|---|---|
| Droit `organization.module.install` absent | 403 | `permission_denied` |
| Organisation d'un autre tenant | 404 | `organization_not_found` |
| Version non `published` | 422 | `MODULE_VERSION_NOT_PUBLISHED` |
| Compatibilité différente de `compatible` (BE-044) | 409 | `MODULE_VERSION_INCOMPATIBLE` |
| Prérequis absent du catalogue ou non installé | 409 | `MODULE_PREREQUISITE_MISSING` |
| Installation non retirée déjà présente | 409 | `MODULE_ALREADY_INSTALLED` |

## Rejeu

Le même couple (`Idempotency-Key`, corps) renvoie la réponse initiale avec le même `operationId`
(`core/idempotency`, BE-232). Une clé réutilisée avec un autre corps est refusée.

## Code

- Service : `app/modules_registry/installation.py` (`executer_installation`, `lire_installation_par_operation`).
- Fournisseur d'exécution : protocole `FournisseurProvisionnement` ; `FournisseurSimule` par défaut.
- Table : `module_installations` (migration `be047c1d2e3f`). Index unique partiel : une seule
  installation non `removed` par (organisation, module).
