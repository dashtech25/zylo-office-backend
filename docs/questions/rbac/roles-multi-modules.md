# Un rôle peut-il couvrir plusieurs modules ?

- **Question** : un rôle appartient-il à un seul module (ou au socle transverse), ou peut-il combiner plusieurs modules ? Quel mécanisme porte la portée module ?
- **Tâches concernées** : T-018, T-021, T-022
- **Contexte** : la fiche T-018 d'origine dit « un rôle = un module ou aucun ». `docs/audit/securite-rbac-multitenant.md` §4 présente `Role.moduleCode` nullable comme « global (multi-module, existant) ». `UserRole.resourceId` est un UUID, alors que `Module.code` est une chaîne (IAM-005). Les rôles par défaut zylo_liquid contiennent `CURRENCY_READ` et `GEO_READ`, qui relèvent du socle `shared` (cité par REV-A-03).
- **Options** :
  - A. `Role.moduleCode` nullable : un rôle = un module ou transverse socle ; permissions de socle en liste fermée ; rôle propriétaire explicitement transverse ; backfill explicite et rejouable (recommandation).
  - B. Table `UserModuleAssignment (organisation, utilisateur, module, rôle)` : plus lisible, mais deux sources de vérité dans le moteur RBAC et un refactor large de `rbac/service.py`.
  - C. Rôles multi-modules autorisés : aucune frontière, rejeté.
- **Recommandation vérifiée** : option A. Vérification : `app/shared/permissions.py` existe (vérifié) et sert de liste de socle ; le type du `resourceId` a été relevé dans `app/rbac/models.py` (revue). La validation client est requise avant fusion de T-018 : ce choix change les droits.
- **État** : En attente de réponse (validation client exigée avant fusion)
- **Application provisoire** : appliquée provisoirement le 2026-10-09 (décision du coordinateur : les validations client en attente ne bloquent pas les fusions). Option A fusionnée dans `remy` (`75a1060`, correctifs `c522540`, migration de fusion `b4e1c7d2a9f3`).
