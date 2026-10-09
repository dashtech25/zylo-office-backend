# T-018 : Rôles et permissions par module, un seul mécanisme (Role.moduleCode nullable)

- **Statut** : Planifiée, en attente de validation client · **Priorité** : P1 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-018-roles-par-module` · **Base de test** : `zylo_t018_test` · **Ports** : back 3118
- **Dépendances** : T-007, T-010, T-019, T-036
- **Décisions requises** : `rbac/roles-multi-modules.md` (recommandation appliquée, validation client requise avant fusion)

## Objectif
Donner au RBAC la notion de module : `Role.moduleCode` nullable, un rôle appartient à une organisation et, s'il a un module, à ce module. Un même utilisateur peut recevoir des rôles différents selon le module, pour une même organisation. Un seul mécanisme : pas de portée de module sur `userRole`.

## Problèmes résolus
- IAM-005 (P1), étapes 4 et 5 de la priorité n°1, ARC-016 (partie), REV-A-03 (quatre conditions), REV-A-12 (unicité NULL), REV-S-13 (rôles existants non rattachés), REV-S-24 (retour arrière)

## Dépendances : justification
T-007 (décision sur le rôle manager, sans quoi les rôles par défaut ne sont pas stables), T-010 (isolation), T-019 (garde-fous, dont le retrait du dernier propriétaire), T-036 (registre de seeders, sans quoi `modules_registry/service.py` reçoit du code de seed).

## Décision de modèle (les quatre conditions)
1. **Un seul mécanisme** : `Role.moduleCode`. La portée module de `userRole` (`resourceType = 'module'`) n'est pas adoptée : `UserRole.resourceId` est un UUID, `Module.code` est une chaîne.
2. **Permissions de socle partagées** : liste fermée (`CURRENCY_READ`, `GEO_READ`, etc.) dans `app/shared/permissions.py`. Un rôle de module peut les contenir sans être rejeté.
3. **Rôle propriétaire explicite** : `owner` est transverse et reçoit les permissions de chaque module activé (`grant_module_permissions_to_owner`). C'est une exception déclarée, pas une règle générale.
4. **Backfill réel et explicite** : migration de données rejouable, qui rattache chaque rôle par défaut à son module (liste explicite, testée). Les rôles personnalisés sont listés dans un rapport en lecture seule, et tranchés avec le client : aucune bascule silencieuse. Pas de backfill au démarrage (T-028).

Contrainte à l'écriture : `update_role_permissions` et `assign_role` refusent une permission dont le module ne correspond pas au rôle (sauf liste de socle).

## Fichiers / modules concernés
- `app/rbac/models.py` (`Role.moduleCode`), migration additive (colonne nullable, index)
- `app/rbac/service.py` (`user_has_permission` filtré par module, `assign_role`, `update_role_permissions`)
- `app/rbac/router.py`, `app/modules_registry/service.py` (seed des rôles du module via le registre de T-036)
- `app/modules/zylo_liquid/roles_seed.py` (rattachement des rôles par défaut ; T-007 déjà fusionné)

## Stratégie
1. Question `rbac/roles-multi-modules.md` : recommandation (un rôle = un module ou transverse socle), alternative documentée (`UserModuleAssignment`), coût expliqué.
2. Requête de détection des doublons `userRole` avant migration. Contrainte d'unicité avec `NULLS NOT DISTINCT` (PostgreSQL 16 déployé dans la CI), ou index uniques partiels.
3. Migration additive ; backfill explicite et journalisé.
4. Pas de changement de droit pour les organisations existantes sans rapport validé.

## Tests attendus
- Matrice écrite à la main : un utilisateur a `zyloLiquid.*.manage` via un rôle LQ et `zyloTanker.*.read` via un rôle TK, sans accès croisé.
- Refus d'écriture d'une permission de module dans un rôle d'un autre module ; acceptation des permissions de socle.
- Test de contrainte d'unicité sur (utilisateur, organisation, rôle, portée NULL).
- `alembic upgrade head` puis `downgrade -1` sur base jetable. Le downgrade supprime `moduleCode` : les données qu'il contenait ne sont pas restaurées (écrit dans la fiche).
- Non-régression : `tests/test_rbac*.py`, `tests/test_modules.py`.

## Critères d'acceptation
- Matrice utilisateur × module × action passe.
- Migration additive, rejouable ; rapport des rôles personnalisés produit.
- Validation client consignée avant fusion.
- Section « Retour arrière » dans `docs/architecture/securite/roles-par-module.md`.

## Risque et retour arrière
Élevé : moteur central. Retour arrière : désactiver le filtre module par configuration ; le downgrade de migration est documenté comme non restaurant.

## Livrable documentaire
- `docs/architecture/securite/roles-par-module.md` (créé)
- `docs/questions/rbac/roles-multi-modules.md`

## Parallélisable avec
T-020, T-023 (fichiers distincts) ; séquencer avec T-019 sur `rbac/service.py`.
