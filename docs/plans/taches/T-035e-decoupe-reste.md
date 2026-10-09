# T-035e : Découpe de zylo_liquid/service.py, lot e (reste) et seuil de taille

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-035e-zl-reste` · **Base de test** : `zylo_t035e_test` · **Ports** : back 3135
- **Dépendances** : T-035d
- **Décisions requises** : aucune

## Objectif
Extraire le reste des fonctions. Fermer la découpe : `service.py` ne contient plus que la façade de réexport, ou une justification écrite pour le reliquat.

## Problèmes résolus
- ARC-004 (P1), fin de la découpe

## Dépendances : justification
T-035d (lot précédent fusionné).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py`, sous-paquets existants, éventuellement `common/`

## Stratégie
1. Inventaire des fonctions restantes (script, dans la PR).
2. Déplacement ; suppression de la façade pour les lots fermés.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique.
- `lint-imports` vert.

## Critères d'acceptation
- `service.py` inférieur à 2 000 lignes, **ou** un reliquat listé fonction par fonction avec sa justification (critère mesurable, REV-S-23).
- Les cinq lots a à e fusionnés, chacun vert.

## Risque et retour arrière
Moyen. Retour arrière : revert du lot.

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (carte finale).

## Parallélisable avec
Rien sur `service.py`.
