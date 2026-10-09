# Agents Claude Code et CLAUDE.md du frontend

- **Question** : les agents `.claude/agents/` et les skills `.claude/skills/` du frontend, ainsi que son `CLAUDE.md` consolidé, sont-ils livrés dans la tâche T-040 ou dans une tâche frontend dédiée ?
- **Tâches concernées** : T-040 (« backend et frontend »), T-039 (docs frontend).
- **Contexte** : T-040 couvre les deux dépôts. Le dépôt frontend a son propre dépôt git, son propre `CLAUDE.md` (dont l'arborescence est obsolète, DOC-007) et son propre `src/app/CLAUDE.md` (règle « page = 1 ligne » non respectée, DOC-008). Cette branche ne touche que le backend.
- **Options** :
  - A. Créer une branche `docs/T-040-agents-frontend` dans le dépôt frontend, avec un worktree dédié ;
  - B. Attendre T-039 (arborescence frontend) pour ne pas réécrire deux fois ;
  - C. Limiter T-040 au backend.
- **Recommandation vérifiée** : option B. T-040 déclare T-039 comme dépendance ; vérification dans la fiche `docs/plans/taches/T-040-agents-skills-claude-code.md` (ligne « Dépendances »). Écrire le `CLAUDE.md` frontend avant T-039 le ferait réécrire.
- **État** : En attente de réponse. Backend traité dans cette branche ; frontend non traité.
