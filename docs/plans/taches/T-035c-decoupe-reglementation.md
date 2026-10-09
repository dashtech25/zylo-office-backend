# T-035c : Découpe de zylo_liquid/service.py, lot c (réglementation et déclarations)

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-035c-zl-reglementation` · **Base de test** : `zylo_t035c_test` · **Ports** : back 3135
- **Dépendances** : T-035b
- **Décisions requises** : aucune

## Objectif
Extraire la réglementation et les déclarations dans `regulation/`. Calculs réglementaires : aucune valeur ni tolérance ne change.

## Problèmes résolus
- ARC-004 (P1), suite de la découpe

## Dépendances : justification
T-035b (lot précédent fusionné).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py`, `app/modules/zylo_liquid/regulation/` (créé)

## Stratégie
1. Filet de caractérisation sur les calculs réglementaires et les déclarations (sorties figées).
2. Déplacement par groupes ; façade ; pas de renommage dans la même PR.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique.
- Caractérisation des déclarations (`test_zylo_liquid_declarations.py` inclus).

## Critères d'acceptation
- Fonctions réglementaires déplacées ; `lint-imports` vert ; aucun calcul modifié.

## Risque et retour arrière
Élevé (réglementation). Retour arrière : revert du lot.

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (mise à jour).

## Parallélisable avec
Rien sur `service.py`.
