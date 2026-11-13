# Environnement de recette : existe-t-il, et que signifie « parcours validé » ?

- **Question** : existe-t-il un environnement de recette distinct (base, backend et frontend déployés) ? Sinon, quelle preuve vaut validation d'un parcours ?
- **Tâches concernées** : T-038a, T-010, T-026, T-047
- **Contexte** : le plan interdit toute opération sur la production (§2), mais parle de « parcours prod vérifié » (REV-S-18). `ci.yml.disabled` lance `alembic upgrade head` puis `pytest` sur une base de service, sans démarrage du backend pour Playwright.
- **Options** :
  - A. Pas de recette : preuve = build de production local sur une base `zylo_tNNN_test` (recommandation pour l'instant).
  - B. Environnement de recette hébergé (base dédiée, backend et frontend déployés), à créer et à financer.
  - C. Utiliser la production pour la recette : rejeté, interdit par le plan.
- **Recommandation vérifiée** : option A. Vérification : le plan §2 interdit les opérations sur la production ; la base de test est garantie par la garde de T-005. Le mot « prod » est remplacé par « build de production local » dans les fiches.
- **État** : En attente de réponse (besoin d'un environnement hébergé à confirmer)
