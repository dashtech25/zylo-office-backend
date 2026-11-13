# Contribuer au backend

## Branches et worktrees

- Branche de travail commune : `remy`. Une tâche = une branche `<type>/T-NNN-<sujet>` partant de `remy` (ou d'une base déjà fusionnée).
- Un worktree par tâche : `office/worktrees/T-NNN-back` (ports et base de test : [`ports.md`](../process/ports.md), [`git-workflow.md`](../process/git-workflow.md)).

## Commits

- Message en français, sujet court au format `type(portée): résumé`.
- Trailers en fin de message, dans cet ordre :

```text
Co-Authored-By: <modèle> <noreply@anthropic.com>
Claude-Session: <lien de session>
```

- Un sujet par commit. Les tests du commit passent dans le worktree au moment du commit.
- Interdit : `--no-verify`, réécriture d'historique et `git push --force` sans accord écrit.

## Fichiers

- Un fichier de documentation traite un seul sujet. Seuil de longueur : 300 lignes, hors `docs/archive/` (à confirmer : [`docs/questions/process/seuil-taille-docs.md`](../questions/process/seuil-taille-docs.md)).
- Les données sensibles ne sont jamais versionnées : `.env*` (sauf `.env.example`), dumps, clés. Le hook `.githooks/pre-commit` les refuse ; activer une fois par clone : `git config core.hooksPath .githooks`.

## Code

- Le code est documenté par commentaires d'intention : le pourquoi d'une contrainte, un invariant, un piège évité. Pas de commentaire qui paraphrase le code.
- Les docstrings décrivent le contrat (entrées, sorties, erreurs), pas l'implémentation.
- Une décision structurante renvoie à son ADR (`docs/architecture/decisions/`).
- Ajouter une permission : la déclarer dans `permissions.py` et dans `seed.py` du module, sinon `require_permission()` refuse tout le monde.

## Documentation

- Chaque changement de comportement met à jour le document du dossier concerné dans `docs/`.
- Une question sans réponse va dans `docs/questions/<catégorie>/<sujet>.md`, avec une recommandation vérifiée.
- Une demande de revue ou de fusion suit le gabarit [`gabarit-pr.md`](../process/gabarit-pr.md) ; les issues suivent [`gabarit-issue.md`](../process/gabarit-issue.md) et les labels [`labels.md`](../process/labels.md).
