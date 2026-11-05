# Approbation des changements de paramètres sensibles (BE-159)

Module : `app/parametres/approbation.py` (logique), `app/parametres/approbation_routes.py` (routes).
Table : `approbation_parametre` (migration `159b5e0a7c31`).

## Principe

Un paramètre dont la définition porte `sensitive = true` ne s'applique jamais directement.
Un `PUT /api/v1/parametres/organisation/{org}/{cle}` sur ce paramètre crée une demande en attente
et renvoie `202` avec `id` et `statut = en_attente`. La valeur active ne change pas.

## Cycle de vie

| Décision | Statut obtenu | Écriture | Audit |
|---|---|---|---|
| `approuver` | `approuvé` | nouvelle version appliquée (`setting_value`) | `EVT-SET-01` (application) et `EVT-SET-02` (décision) |
| `rejeter` | `rejeté` | aucune | `EVT-SET-02` |

Une demande tranchée ne change plus jamais de statut : toute nouvelle décision renvoie `409 VERSION_CONFLICT`.

## Routes

- `GET /api/v1/approbations/{demande_id}` : demandeur, ou détenteur de `settings.approve`.
- `POST /api/v1/approbations/{demande_id}/decisions` : corps `{"decision": "approuver" | "rejeter", "motif": "..."}`.
  Permission `settings.approve`.

## Droits et erreurs

- Demander : `parametres.setting.apply` (403 sinon).
- Décider : `settings.approve` (403 sinon) ; approbateur distinct du demandeur (403 sinon).
- Hors tenant ou demande inconnue : 404 (`TENANT_MISMATCH`), réponse identique dans les deux cas.
- Décision sur demande tranchée : 409 `VERSION_CONFLICT`, rien n'est écrit.
- Paramètre non sensible passé à la demande : 422 `SCHEMA_INVALID`.

## Concurrence

La demande est lue avec `FOR UPDATE` avant contrôle du statut : deux décisions concurrentes
sont sérialisées et la seconde reçoit 409.

## Hypothèses à confirmer

Voir les points QE-PAR-02 (routes), QE-PAR-03 (permission `settings.approve`), QE-PAR-06
(interdiction de l'auto-approbation) dans `implementation-backend/tasks-parametres-notifications-audit.md`.
Le drapeau `sensitive`, qui masque aussi les valeurs dans l'audit (BE-154), sert ici de critère
d'approbation : à trancher.
