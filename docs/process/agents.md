# Agents : rôles et gabarit d'agent d'exécution

- **Statut** : en vigueur (T-040). Définitions réelles : `.claude/agents/*.md` ; procédures : `.claude/skills/*/SKILL.md`.

## Rôles

- **Orchestrateur** : lit la fiche, découpe en lots, délègue, relit les rapports, décide de la livraison. Il ne fusionne pas.
- **Agent d'exécution** : reçoit un lot précis, produit le changement dans son worktree, rend un rapport.

## Gabarit de délégation

Chaque délégation précise :

```text
Tâche : T-NNN (fiche : docs/plans/taches/T-NNN-*.md, à lire en entier)
Dépôt : backend | frontend
Branche : <type>/T-NNN-<sujet>
Worktree : office/worktrees/T-NNN-back (créé par scripts/dev/env_tache.sh creer NNN back)
Base de test : zylo_t<NNN>_test (jamais une autre base)
Ports : selon docs/process/ports.md
Fichiers autorisés : <liste>
Tests attendus : <commandes>
Décision non évidente : la consigner dans docs/questions/<catégorie>/<sujet>.md, ne pas trancher seul
Interdits : ne fusionne pas ; ne migre pas la production ; pas de git reset --hard, stash, --no-verify
Rapport : fichiers modifiés, commandes lancées et résultats, questions ouvertes
```

## Règles pour un agent d'exécution

1. Lire la fiche en entier avant toute modification.
2. Créer le worktree et la base de test ; ne jamais utiliser une base de dev.
3. Ne modifier que les fichiers autorisés. Si un autre fichier doit changer, arrêter et demander.
4. Lancer les tests ciblés, puis les contrôles de [`validation-avant-livraison.md`](../workflows/validation-avant-livraison.md).
5. Rendre un rapport court : ce qui a changé, ce qui a été vérifié, ce qui reste ouvert.

## Agents disponibles

Voir `.claude/agents/` : `architecture`, `iam-permissions`, `backend`, `frontend`, `qualite-tests`, `documentation-recherche`, `revue`. Tous s'exécutent avec le modèle `haiku`.
