# Modèle organisations, utilisateurs, rôles et permissions par module

- **Statut** : décrit l'état du code (fusionné dans `remy` le 2026-10-09, T-018 et T-022 « à vérifier »). Source des règles d'écriture : [`roles-par-module.md`](roles-par-module.md).

## 1. Entités

| Entité | Table (camelCase) | Rôle |
|---|---|---|
| Organisation | `organization` | Périmètre de données : toute ressource appartient à une organisation |
| Utilisateur | `user` | Identité globale, authentifiée par JWT |
| Rattachement | `organizationUser` | Un utilisateur est membre d'une ou plusieurs organisations |
| Module | `module` | Capacité activable par organisation (`zylo_liquid`, `zylo_tanker`) ; enregistrée dans `modules_registry` |
| Activation | `organizationModule` (registre) | Un module actif pour une organisation |
| Rôle | `role` | Ensemble de permissions. `moduleCode` nul = rôle transverse du socle (ex. `owner`) ; renseigné = rôle d'un module |
| Permission | `permission` | Code `domaine.entite.action` (trois segments, vérifié par `rbac/module_policy.py`) |
| Affectation | `userRole` | Lie un utilisateur à un rôle, avec une portée (organisation entière ou ressource) |

Un seul mécanisme : aucune portée « module » n'est ajoutée à `userRole`. Le rattachement à un module passe par `role.moduleCode` ([ADR 0002](../decisions/0002-roles-par-module.md)).

## 2. Permissions

- Format : `domaine.entite.action`. Actions recommandées : `read`, `create`, `update`, `delete`, `validate`, `export`, `manage`.
- Socle partagé : liste fermée `SHARED_PERMISSION_CODES` (`app/shared/permissions.py`). Un rôle de module peut la contenir.
- Matrice permission → routes : [`matrice-autorisation.md`](matrice-autorisation.md), générée par `scripts/dev/generer_matrice_autorisation.py`. Ne pas éditer à la main.

## 3. Règles de décision

1. Une seule fonction décide : `rbac/service.py::user_has_permission`. Refus par défaut ; un refus explicite l'emporte.
2. `rbac/module_rights.py::user_has_module_permission` enveloppe cette fonction et exige en plus : la permission appartient au module ou au socle ; le module est actif pour l'organisation ; le moteur central accorde l'accès.
3. Permission inconnue, hors module ou module inactif : `False`, sans message distinct (pas de sondage des codes).
4. Le chemin `organization_id` de chaque route doit égaler l'en-tête `X-Organization-Id` (sinon 403 `organization_mismatch`).

## 4. Cycle de vie d'un utilisateur dans un module

1. Activation du module pour l'organisation : les rôles par défaut du module sont créés (`roles_seed`).
2. Un gestionnaire (`rbac.role.manage`) crée ou affecte un rôle de module.
3. Un utilisateur reçoit au plus un rôle par module et par organisation (409 sinon).
4. Non-élévation : le gestionnaire doit posséder chaque permission du rôle qu'il affecte (403 sinon).
5. Le propriétaire (`owner`) est transverse et reçoit les permissions de chaque module activé : exception déclarée.
6. Le dernier administrateur d'un module ne peut pas être retiré (409).

Détail des flux : [`docs/modules/affectation-par-module/`](../../modules/affectation-par-module/flux.md) et [`docs/architecture/securite/creation-utilisateurs.md`](creation-utilisateurs.md).

## 5. Points non tranchés

- `permission.moduleCode` des capacités partagées (alertes, fichiers, localisation) vaut `zylo_liquid` : corriger le catalogue est une décision distincte.
- Les rôles par défaut `zylo_liquid` contiennent encore `shared.currency.read` et `shared.geo.read`. Les retirer changerait des droits existants.
- Cumul de rôles de module : non autorisé ; un cumul demande une décision. Voir [`docs/questions/rbac/roles-multi-modules.md`](../../questions/rbac/roles-multi-modules.md).
