# T-022 : Affecter un utilisateur à un module avec ses droits propres (API)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-022-affectation-module` · **Base de test** : `zylo_t022_test` · **Ports** : back 3122
- **Dépendances** : T-018, T-019, T-021
- **Décisions requises** : aucune (dépend de T-018, validé par le client)

## Objectif
Dans une organisation, l'administrateur choisit un utilisateur de l'organisation, choisit un module activé, et lui attribue des rôles propres à ce module. Un utilisateur non membre ne peut recevoir aucun droit.

## Problèmes résolus
- Étapes 3, 4 et 5 de la priorité n°1, IAM-004 (cible d'attribution)

## Dépendances : justification
T-018 (rôles par module), T-019 (appartenance), T-021 (création d'utilisateurs). Ce modèle est le seul mécanisme : `userRole` n'a pas de portée module.

## Fichiers / modules concernés
- `app/rbac/router.py` (`PUT /organizations/{id}/modules/{code}/users/{userId}/roles`)
- `app/rbac/service.py` (`assign_role` : appartenance active, module actif, rôle du même module)
- `app/modules_registry/service.py` (module actif requis)
- `tests/test_module_assignment.py` (créé)

## Stratégie
1. Préconditions : utilisateur membre actif, module actif pour l'organisation, rôle du même module.
2. Lecture des affectations par utilisateur et par module (pour T-025).
3. Audit à chaque affectation.
4. Aucune affectation implicite (au premier accès) : interdite.

## Tests attendus
- Utilisateur affecté au module A (lecture) et au module B (gestion) : droits différents vérifiés.
- Non-membre : 422 ; module inactif : 409 ; rôle d'un autre module : 422.
- Affectation tracée dans l'audit.
- Cross-tenant : 404 (T-047).

## Critères d'acceptation
- Matrice utilisateur × module × organisation passe.
- Aucune affectation sans appartenance ni module actif.

## Risque et retour arrière
Moyen : un module inactif rend l'affectation sans effet. Retour arrière : revert de la route.

## Livrable documentaire
- Complément de `docs/architecture/securite/roles-par-module.md`.
- `docs/modules/socle/affectation-modules.md` (créé, contrat d'API).

## Parallélisable avec
T-023, T-049 (fichiers distincts).
