---
name: validation-avant-livraison
description: Exécute la liste de contrôle avant livraison d'une tâche backend (tests, migrations, ports, fichiers sensibles, documentation, plan).
when_to_use: Quand une tâche est prête à être marquée « À vérifier » ou qu'un lot doit être livré.
allowed-tools: Read Grep Glob Bash
---

# Validation avant livraison

Suivre `docs/workflows/validation-avant-livraison.md` dans l'ordre. Pour chaque contrôle, noter la commande et son résultat.

Commandes :
- `.venv/bin/pytest <fichiers touchés>`, puis `.venv/bin/pytest` si le socle est touché.
- `.venv/bin/alembic upgrade head` sur la base de test du worktree.
- `scripts/check_ports.sh`
- `scripts/dev/controle_fichiers_sensibles.sh --staged`
- `python3 scripts/docs/check_plan.py`
- `scripts/docs/verifier_liens.sh`

Un contrôle rouge bloque la livraison. Rendre un tableau : contrôle, commande, résultat (OK, KO, non lancé et pourquoi).

Ne fusionne pas, ne pousse pas.
