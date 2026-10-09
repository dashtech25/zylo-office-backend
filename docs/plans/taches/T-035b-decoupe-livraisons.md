# T-035b : Découpe de zylo_liquid/service.py, lot b (livraisons et rapprochements)

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-035b-zl-livraisons` · **Base de test** : `zylo_t035b_test` · **Ports** : back 3135
- **Dépendances** : T-035a
- **Décisions requises** : aucune

## Objectif
Extraire les livraisons et les rapprochements dans `deliveries/`, sans changement de comportement.

## Problèmes résolus
- ARC-004 (P1), suite de la découpe

## Dépendances : justification
T-035a (le lot précédent est fusionné avant de toucher `service.py`).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py`, `app/modules/zylo_liquid/deliveries/` (créé)

## Stratégie
1. Filet de caractérisation sur le rapprochement de livraisons.
2. Déplacement par groupes ; façade ; aucun renommage dans la même PR.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique.
- Caractérisation du rapprochement de livraisons.
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : parcours livraison.

## Critères d'acceptation
- Fonctions de livraisons déplacées ; `lint-imports` vert ; aucune route modifiée.

## Risque et retour arrière
Élevé. Retour arrière : revert du lot.

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (mise à jour).

## Parallélisable avec
Rien sur `service.py`.
