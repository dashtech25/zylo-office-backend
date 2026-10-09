# Rôles et permissions par module (T-018)

Statut : implémenté sur `feat/T-018-roles-par-module`, en attente de validation client avant fusion
(`docs/questions/rbac/roles-multi-modules.md`, option A).

## 1. Modèle

- `role.moduleCode` (nullable, FK vers `module.code`, index). `NULL` = rôle transverse du socle
  (ex. `owner`, rôles personnalisés existants). Une valeur = rôle propre à ce module.
- Un seul mécanisme : aucune portée module n'est ajoutée à `userRole`. `userRole` garde sa portée
  existante (organisation entière ou ressource précise).
- Permissions au format `domaine.entite.action` (trois segments, vérifié par
  `rbac/module_policy.py::is_valid_permission_code`). Actions recommandées : `read`, `create`,
  `update`, `delete`, `validate`, `export`, `manage`.
- Socle partagé : liste fermée `SHARED_PERMISSION_CODES` (`app/shared/permissions.py`). Un rôle de
  module peut la contenir sans être rejeté.

## 2. Règles d'écriture (serveur, toujours)

1. Un rôle de module ne contient que les permissions de son module ou du socle partagé
   (`permission_module_mismatch`, 422). S'applique à la création de rôle de module, à la mise à jour
   standard des permissions et à l'affectation.
2. Un utilisateur ne reçoit au plus qu'un rôle par module et par organisation
   (`module_role_already_assigned`, 409).
3. Affectation : cible membre de l'organisation (404 sinon), module actif (409 sinon), rôle de
   l'organisation uniquement (404 pour un rôle d'une autre organisation), non-élévation : le
   granter doit posséder chaque permission du rôle (403).
4. Le rôle `owner` reste transverse et reçoit les permissions de chaque module activé
   (`grant_module_permissions_to_owner`). C'est une exception déclarée.

## 3. Flux d'affectation

1. Le module est activé pour l'organisation (`POST /modules/organizations/{id}/activate`). Les rôles
   par défaut sont créés avec `moduleCode` renseigné.
2. Un gestionnaire (`rbac.role.manage`) crée un rôle de module :
   `POST /rbac/organizations/{id}/module-roles`.
3. Il l'affecte à un membre : `POST /rbac/organizations/{id}/module-roles/assignments`.
4. Il retire l'affectation : `DELETE /rbac/organizations/{id}/module-roles/assignments/{assignmentId}`.
5. Droits effectifs par module : `GET /rbac/organizations/{id}/users/{userId}/module-rights`
   (soi-même, ou `rbac.role.manage`). Un module inactif liste ses rôles et aucune permission.

Chaque route vérifie d'abord que le chemin `organization_id` égale l'en-tête `X-Organization-Id`
(sinon 403 `organization_mismatch`).

## 4. Règles de résolution

Une seule fonction décide : `rbac/service.py::user_has_permission` (deny prioritaire, refus par
défaut). `rbac/module_rights.py::user_has_module_permission` l'enveloppe et exige en plus :

1. la permission appartient au module, ou au socle partagé ;
2. le module est actif pour l'organisation (`is_module_active`) ;
3. le moteur central accorde l'accès.

Une permission inconnue, hors module ou module inactif donne `False` sans erreur (pas de sondage de
codes par message d'erreur).

## 5. Backfill explicite (rôles existants)

- Migration `a7d3c1e9f024` : ajoute la colonne, l'index et la FK. Elle ne modifie aucune ligne.
- `scripts/backfill_module_roles.py [--dry-run]` : à lancer à la demande, jamais au démarrage.
  Il rattache les rôles par défaut (liste explicite issue des `roles_seed`) dont aucune permission
  n'appartient à un autre module. Il liste en `conflicts` les rôles à arbitrer, en `customRoles` les
  rôles personnalisés, sans les modifier.
- Idempotent : un rôle déjà rattaché est ignoré. Aucune permission n'est modifiée, aucun droit
  n'est élargi (rôle manager compris).

## 6. Retour arrière

- Désactiver le contrôle par module : les chemins existants (`user_has_permission`) ne dépendent pas
  de `moduleCode`. Les routes `module-roles` peuvent être retirées du routeur sans effet sur le reste.
- Downgrade `e2f3a4b5c6d7` : supprime la colonne `role.moduleCode`. Les rattachements qu'elle
  contenait ne sont pas restaurés : les rôles redeviennent transverses. Les lignes `role`,
  `rolePermission` et `userRole` sont conservées (testé dans `tests/test_rbac_module_roles.py`).

## 7. Limites connues

- `permission.moduleCode` des permissions seedées par `zylo_liquid` vaut `zylo_liquid`, y compris
  pour les capacités partagées (alertes, fichiers, localisation). Les règles de module s'appuient
  sur cette valeur telle quelle ; corriger le catalogue est une décision distincte.
- Les rôles par défaut `zylo_liquid` contiennent encore `shared.currency.read` et `shared.geo.read`.
  Les retirer changerait les droits des utilisateurs existants : non appliqué, à trancher.
- Un utilisateur ne peut recevoir qu'un rôle par module, comme demandé. Un cumul éventuel demanderait
  une décision distincte.

## 8. Affectation par module (T-022)

- Routes de membre par module : `GET .../modules/{code}/members`, `PUT .../modules/{code}/users/{userId}/role`,
  `DELETE .../modules/{code}/users/{userId}/role`, `GET .../modules/{code}/users/{userId}/role-preview`.
- Flux, résolution et garde-fous : `docs/modules/affectation-par-module/`.
- Le remplacement d'un rôle est atomique ; le dernier administrateur du module ne peut pas être retiré (409).
