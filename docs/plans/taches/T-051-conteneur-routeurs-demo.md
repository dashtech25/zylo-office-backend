# T-051 : Conteneur non root, routeur monté une fois, routes de démonstration supprimées

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : chore
- **Branche suggérée** : `chore/T-051-conteneur` · **Base de test** : `zylo_t051_test` · **Ports** : back 3151
- **Dépendances** : T-010
- **Décisions requises** : aucune

## Objectif
Durcir le déploiement : utilisateur non privilégié dans l'image, routeur de localisation monté une seule fois, routes de démonstration supprimées (après que T-010 les a protégées et testées).

## Problèmes résolus
- BCK-013 (P2, conteneur root), BCK-019 (P3, routes de démo), BCK-021 (P3, routeur monté deux fois), REV-A-17 (découpe de T-015)

## Dépendances : justification
- T-010 : routes démo protégées par les gardes avant suppression.
- Retirées (confort ou CI, pas de prérequis technique) : T-015 (même zone (surface API) : pas d'artefact consommé) ; T-028 (`Dockerfile` : ordre de fusion seulement).

## Fichiers / modules concernés
- `Dockerfile` (`USER`, répertoires en lecture seule quand possible)
- `app/api/v1/router.py` (routeur monté deux fois)
- `app/api/v1/endpoints/health.py` (`error-demo`)
- `app/identity/router.py`, `app/modules_registry/router.py` (routes démo)

## Stratégie
1. Ordre : T-010 (routes protégées), T-028 (Dockerfile), puis cette tâche.
2. Utilisateur dédié, `USER` non root, répertoires d'écriture explicites (volumes).
3. Monter `location_router` une seule fois ; documenter le besoin zylo-tanker dans le README d'API.
4. Supprimer les routes démo après vérification qu'aucun client (frontend, e2e) ne les appelle (`grep`).

## Tests attendus
- Build de l'image et `docker run` avec utilisateur non root (si Docker disponible ; sinon vérification statique consignée).
- Test : les routes démo renvoient 404.
- Test : chaque routeur est monté une seule fois (inventaire des routes sans doublon).
- Suite pytest : aucun nouvel échec.

## Critères d'acceptation
- Image exécutée sans root ; `USER` présent dans le `Dockerfile`.
- Surface API sans route de démonstration.
- Aucun routeur monté deux fois.

## Risque et retour arrière
Moyen : un conteneur non root ne peut plus écrire dans un volume existant (vérifier les droits avant déploiement). Retour arrière : revert du `USER`.

## Livrable documentaire
- `docs/architecture/securite/surface-api.md` (complété).

## Parallélisable avec
T-016, T-017 (fichiers distincts).
