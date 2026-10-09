# T-034 : Découpe de zylo_liquid/service.py, lot 1 (filet de caractérisation, stations et cuves)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-034-zl-service-lot1` · **Base de test** : `zylo_t034_test` · **Ports** : back 3134
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
`app/modules/zylo_liquid/service.py` fait 15 681 lignes et 504 fonctions. Ce lot extrait les fonctions de stations et de cuves (jaugeage manuel, calibration) dans `stations/` et `tanks/`, sans changer le comportement. Le personnel (T-013, T-020, T-021, T-027) n'est pas dans ce lot.

## Problèmes résolus
- ARC-004 (P1), partie lot 1 seulement

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-005 (confort) ; T-006 (confort : filet de tests local).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py` (extraction, façade de réexport)
- `app/modules/zylo_liquid/stations/service.py`, `tanks/service.py` (créés)
- `app/modules/zylo_liquid/router.py` (imports, sans changement de route)
- `tests/test_zylo_liquid_*` et tests de caractérisation (créés)

## Stratégie
1. Filet : tests de caractérisation sur les fonctions à déplacer, sorties figées sur des cas représentatifs, avant tout déplacement.
2. Une fonction ou un petit groupe à la fois. `service.py` garde une façade qui réexporte les noms existants pendant la transition.
3. Helpers partagés : emplacement décidé à l'avance (`zylo_liquid/common.py`), pour éviter les imports circulaires.
4. `lint-imports` après chaque extraction.
5. Aucun renommage dans la même PR que le déplacement.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique avant et après (mêmes résultats).
- Tests de caractérisation pour chaque fonction déplacée.
- Playwright prod : parcours station et cuve inchangés.

## Critères d'acceptation
- `service.py` diminué des fonctions de stations et de cuves ; façade documentée.
- Aucun changement d'API HTTP.
- `lint-imports` vert.

## Risque et retour arrière
Élevé : fichier central. Retour arrière : revert par extraction (une PR par sous-domaine).

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (créé, carte des sous-domaines).

## Parallélisable avec
T-030 à T-033c (frontend), T-038a. Pas en parallèle de T-027, T-029, T-035a sur `service.py`.
