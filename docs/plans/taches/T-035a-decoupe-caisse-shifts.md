# T-035a : Découpe de zylo_liquid/service.py, lot a (caisse et shifts)

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : zylo-liquid · **Type** : refactor
- **Branche suggérée** : `refactor/T-035a-zl-caisse` · **Base de test** : `zylo_t035a_test` · **Ports** : back 3135
- **Dépendances** : T-034, T-027
- **Décisions requises** : aucune

## Objectif
Extraire la caisse et les shifts dans `cash/`, sans changer de comportement. Premier lot de la série T-035a à T-035e, qui s'exécutent en chaîne (une seule branche de travail sur `service.py` à la fois).

## Problèmes résolus
- ARC-004 (P1), suite du lot 1 ; ARC-016 (partie : seuils de caisse regroupés dans un module de constantes)

## Dépendances : justification
- T-034 : modules extraits du lot 1 que ce lot découpe.
- T-027 : colonne chiffrée touchée si la télémétrie l'est.
- Retirées (confort ou CI, pas de prérequis technique) : T-029 (ordre sur `service.py` seulement).

## Fichiers / modules concernés
- `app/modules/zylo_liquid/service.py` (façade transitoire)
- `app/modules/zylo_liquid/cash/` (créé), `cash/constants.py` (seuils, dont `_CASH_FUTURE_TOLERANCE`)

## Stratégie
1. Filet de caractérisation sur les calculs de caisse (tolérances, écarts) avant déplacement.
2. Déplacement par groupes ; façade de réexport.
3. Les tolérances et seuils ne changent pas de valeur.
4. Carte mise à jour dans `architecture-service.md`.

## Tests attendus
- Suite `tests/test_zylo_liquid_*` identique avant et après.
- Caractérisation des calculs de caisse (sorties figées).
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : parcours caisse.

## Critères d'acceptation
- Fonctions de caisse et de shifts déplacées ; façade documentée.
- `lint-imports` vert ; aucun changement d'API HTTP.

## Risque et retour arrière
Élevé pour les calculs de caisse. Retour arrière : revert du lot.

## Livrable documentaire
- `docs/modules/zylo-liquid/architecture-service.md` (carte mise à jour).

## Parallélisable avec
Rien sur `service.py` : chaîne stricte T-035a → T-035e.
