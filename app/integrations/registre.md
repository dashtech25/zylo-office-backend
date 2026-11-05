# Registre des connecteurs (BE-160)

Module : `app/integrations/registre.py` (service) et `app/integrations/models.py` (table `connecteur`, migration `5f1e2a3b4c6d`).

## Portée et rattachement

- `tenant` : `organizationId` renseigné ; visible et modifiable par ce seul tenant.
- `global` : `organizationId` nul ; visible en lecture par tous les tenants ; modifiable seulement avec `est_admin_plateforme=True`.

## Machine d'états

| Depuis | Vers autorisés |
|---|---|
| création | activé, révoqué |
| activé | suspendu, révoqué |
| suspendu | activé, révoqué |
| révoqué | aucun (terminal) |

Toute autre cible renvoie 409 `CONNECTEUR_TRANSITION_INTERDITE` sans écriture.

## Audit

Chaque création, activation, suspension, révocation et reprise de configuration écrit une entrée `audit_event` avec `changes.evenement = "EVT-INT-01"`. Les mutations de tenant passent par `executer_mutation_sensible` (BE-153) ; les globaux par un savepoint avec `sans_organisation=True`.

## Reprise de configuration

`reprendre_configuration` exige `validee=True`, fourni par la validation de BE-155. Sinon 409 `CONNECTEUR_CONFIGURATION_NON_VALIDEE`. Un connecteur révoqué ne reprend rien.

## Points ouverts

- Codes 409 locaux à ajouter au catalogue BE-151 (QE-BE160-01).
- Les routes sont exposées par BE-162 ; `est_admin_plateforme` y est déterminé.
