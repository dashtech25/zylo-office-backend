# Module Zylo Tanker (supervision de navires)

- **Statut** : en cours. Périmètre actuel : référentiel minimal des navires et suivi GPS. La gestion des cuves est l'étape suivante, hors périmètre à ce stade.
- **Code** : `app/modules/zylo_tanker/` ; capacité GPS partagée `app/location/` ; routes montées sous `/api/v1/zylo-tanker`.
- **Déclaration** : module `zylo_tanker` enregistré dans le registre des modules (`app/modules_registry/seed.py`), activable par organisation.
- **Tests** : `tests/test_zylo_tanker_module.py`, `tests/test_zylo_tanker_vessel_tracking.py`, `tests/test_zylo_tanker_destination_eta.py`.

## Contenu du module

| Fichier | Rôle |
|---|---|
| `models.py` | `Vessel` : équivalent côté navire de `zyloLiquidTruck`, cible des clés étrangères du suivi GPS |
| `schemas.py`, `service.py`, `router.py` | CRUD minimal de `Vessel`, destination du navire (`PUT`/`DELETE /vessels/{id}/destination`) |
| `permissions.py` | `zyloTanker.vessel.read`, `zyloTanker.vessel.manage` |
| `roles_seed.py` | un rôle par défaut : `zylo_tanker_operator` |
| `seed.py` | enregistrement des permissions connues (sans cette liste, `require_permission()` refuse, y compris au propriétaire) |

## Routes

- Module : `GET /ping`, `POST` et `GET /vessels`, `GET /vessels/{id}`, `PUT`/`DELETE /vessels/{id}/destination`.
- Suivi, partagé avec `zylo_liquid` (`app/location/router.py`, monté une seconde fois sous le préfixe `/zylo-tanker`) : boîtiers GPS, connexion Traccar, lieux de tracking, réglages, secret d'ingestion, webhook `POST /gps/ingest`, positions courantes des navires (`GET /vessels/current-positions`), arrêts navire et réconciliation (`/vessel-stop-reconciliations`, `/vessel-stops/{id}/comments`).

## Règles propres au module

- Aucune table de `zylo_liquid` n'est lue directement : le module passe par les services publics.
- Les routes de suivi sont gardées par permission (`app/location/permissions.py`) et par le module actif.
- Ordre des routers : `app/api/v1/router.py` monte le suivi **avant** le CRUD `Vessel`, sinon `GET /vessels/{id}` intercepte `GET /vessels/current-positions`.

## Interface

- Frontend : `zylo-office-frontend/src/modules/zylo-tanker/` (écrans de consommation, tableau de bord, documents, localisation, pompes, supervision, cuves) et route `src/app/zylo-tanker/`. Ces écrans sont décrits dans le dépôt frontend.

## Questions ouvertes

- Gestion des cuves navire : rôles plus fins, à concevoir (hors périmètre actuel).
- Statut des écrans frontend : à confirmer avec le dépôt frontend (T-039).

Décision liée : [ADR 0002](../../architecture/decisions/0002-roles-par-module.md). Découpage général : [`docs/architecture/packages.md`](../../architecture/packages.md).
