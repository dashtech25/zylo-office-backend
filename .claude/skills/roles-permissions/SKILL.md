---
name: roles-permissions
description: Vérifie la cohérence des rôles, permissions et gardes de route d'un module avec le modèle IAM documenté.
when_to_use: Quand une route, une permission, un rôle de module ou une affectation est ajoutée ou modifiée.
allowed-tools: Read Grep Glob Bash
---

# Rôles et permissions

Référence : `docs/architecture/securite/modele-organisations-roles.md`, ADR 0002.

1. Lister les permissions déclarées : `permissions.py` du module.
2. Vérifier leur enregistrement dans `seed.py` (sinon `require_permission()` refuse tout, y compris au propriétaire).
3. Vérifier chaque route : `grep -n "require_permission\|dependencies=" app/<module>/router.py`.
4. Vérifier le rôle par défaut (`roles_seed.py`) : ne contient que des permissions du module ou du socle partagé.
5. Régénérer la matrice si les routes ont changé : `.venv/bin/python scripts/dev/generer_matrice_autorisation.py`. Ne jamais l'éditer à la main.
6. Lancer les tests IAM : `.venv/bin/pytest tests/test_rbac.py tests/test_rbac_module_roles.py`.

Rapport : permissions sans enregistrement, routes sans garde, rôles hors règle, résultat des tests.
