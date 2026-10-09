# Table de ports canonique et allocation par worktree

- **Question** : quelle table de ports fait foi, et comment allouer les ports aux tâches lancées en parallèle ?
- **Tâches concernées** : T-003, T-008, T-038a
- **Contexte** : trois schémas coexistaient : `config.py`, `Dockerfile` et `.env.example` sur 3002 ; `package.json` sur 3001 ; `playwright.config.ts` sur 3055 (vérifié, ligne 6) ; le plan prévoyait 3300+n pour la production et la baseline utilisait 3007.
- **Options** :
  - A. Table de T-003 : checkout principal 3002 / 3001 / 3055, worktrees 3100+n / 3200+n / 3300+n, ports interdits 3006 et 3007 (recommandation).
  - B. Un seul port par service, sans allocation par worktree : collisions probables dès deux tâches en parallèle.
- **Recommandation vérifiée** : option A. Vérification : pour n de 1 à 51, les plages allouées ne contiennent ni 3001, ni 3002, ni 3003, ni 3055 (contrôle par `scripts/docs/check_plan.py`).
- **État** : Appliquée (décision du coordinateur, à confirmer)
