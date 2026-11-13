# T-035d : Découpe de zylo_liquid/service.py, lot d (ventes et produits)

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-035d-zl-ventes` · **Base de test** : `zylo_t035d_test` · **Ports** : back 3135
- **Dépendances** : T-035c
- **Décisions requises** : aucune

## Objectif
Extraire les ventes et les produits dans `sales/`, sans changement de comportement.

## Problèmes résolus
- ARC-004 (P1), suite de la découpe

## Dépendances : justification
- T-035c : lot précédent : modules extraits à découper ensuite.

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py`, `app/modules/zylo_liquid/sales/` (créé)

## Stratégie
1. Filet de caractérisation sur les ventes.
2. Déplacement par groupes ; façade ; pas de renommage dans la même PR.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique.
- Caractérisation des ventes.

## Critères d'acceptation
- Fonctions de ventes déplacées ; `lint-imports` vert.

## Risque et retour arrière
Moyen. Retour arrière : revert du lot.

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (mise à jour).

## Parallélisable avec
Rien sur `service.py`.
