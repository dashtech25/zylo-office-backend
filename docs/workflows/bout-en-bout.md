# Workflow de bout en bout : de la réception d'une tâche à la livraison

- **Statut** : en vigueur (T-017). S'applique à chaque tâche de `docs/plans/taches/`.
- **Règle centrale** : rien n'est fusionné ni poussé sans accord écrit. La livraison est un commit sur la branche de tâche, prêt à relire.

| Étape | Entrée | Action | Sortie | Contrôle |
|---|---|---|---|---|
| 1. Réception | fiche `T-NNN-*.md` | lire la fiche en entier, vérifier dépendances, base, ports, décisions requises | tâche acceptée ou bloquée | `python3 scripts/docs/check_plan.py` |
| 2. Analyse | fiche, documents liés, code concerné | relire le code réel (`grep`, `git log`) avant d'écrire | liste des fichiers touchés | les preuves sont citées par chemin:ligne |
| 3. Décision | point non tranché | ouvrir `docs/questions/<catégorie>/<sujet>.md` avec une recommandation vérifiée, puis avancer sur cette recommandation | question consignée | état « En attente de réponse » |
| 4. Plan | analyse | stratégie en étapes dans la fiche ; ordre des lots ; tests attendus | plan validé dans la fiche | relecture par un second agent (revue) |
| 5. Délégation | plan | confier un lot à un agent d'exécution selon le gabarit de [`agents.md`](../process/agents.md) | rapport de l'agent | fichiers autorisés et tests précisés |
| 6. Implémentation | plan | worktree dédié : `scripts/dev/env_tache.sh creer <NNN> back` ; un sujet par commit | commits en français | pas de `git stash`, `reset --hard`, `--no-verify` |
| 7. Tests locaux | code | `pytest` ciblé puis suite complète ; contrôles de ports et de fichiers sensibles | résultats consignés | [`validation-avant-livraison.md`](validation-avant-livraison.md) |
| 8. Revue | commits de la tâche | revue d'architecture, de sécurité (IAM), de tests | constats classés, corrigés ou consignés | agent `revue`, skills `revue-securite` et `audit-architectural` |
| 9. Documentation | changements | mettre à jour le dossier concerné dans `docs/` ; ADR si décision durable ; index régénéré | docs à jour, liens vérifiés | `scripts/docs/verifier_liens.sh` |
| 10. Livraison | branche de tâche | fiche passée à « À vérifier » ; `check_plan.py --generer` si la fiche change | branche prête, rapport de livraison | accord écrit avant fusion ou push |

## Points de sortie

- Blocage (dépendance absente, décision manquante) : arrêter l'étape 3 et consigner la question ; ne pas contourner.
- Échec d'un contrôle : corriger, relancer le contrôle, ne pas passer à l'étape suivante avec un contrôle rouge.
- Statut d'une fiche : « Terminée » seulement après vérification du client. Jusque-là : « À vérifier ».

## Procédures liées

- Contribution : [`contribution.md`](contribution.md)
- Migration : [`migration.md`](migration.md)
- Déploiement : [`deploiement.md`](deploiement.md)
- Retour arrière : [`retour-arriere.md`](retour-arriere.md)
