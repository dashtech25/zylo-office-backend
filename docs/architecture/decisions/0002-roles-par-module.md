# ADR 0002 : Rôles et permissions rattachés à un module

- **Date** : 2026-10-09 (T-018 fusionnée dans `remy`, appliquée provisoirement).
- **Statut** : Acceptée ; validation client en attente ([`docs/questions/rbac/roles-multi-modules.md`](../../questions/rbac/roles-multi-modules.md), option A).
- **Source** : [`docs/architecture/securite/roles-par-module.md`](../securite/roles-par-module.md), [`modele-organisations-roles.md`](../securite/modele-organisations-roles.md).

## Contexte

Les rôles étaient transverses. Un rôle `manager` pouvait porter des permissions de plusieurs modules sans lien explicite avec le module activé.

## Décision

Un seul mécanisme : `role.moduleCode` (nullable, clé étrangère vers `module.code`). `NULL` = rôle transverse du socle ; une valeur = rôle propre à ce module. `userRole` garde sa portée existante. Un utilisateur a au plus un rôle par module et par organisation. Le serveur refuse les permissions hors module (422) et la non-élévation (403).

## Conséquences

- Backfill explicite, à la demande : `scripts/backfill_module_roles.py [--dry-run]`. Aucune permission n'est modifiée, aucun droit élargi.
- Retour arrière : le downgrade supprime la colonne ; les rattachements ne sont pas restaurés.
- Limites connues : catalogue de permissions à corriger, rôles `zylo_liquid` avec permissions partagées (voir le document de conception).

## Alternatives écartées

Ajouter une portée « module » à `userRole` : deux mécanismes concurrents, rejeté.
