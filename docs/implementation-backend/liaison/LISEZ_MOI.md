# Liaison intermédiaire / orchestrateur

- Rapports de 30 min : `rapports/AAAA-MM-JJ-HHMM.md`, 8 sections numérotées (règle dans `.claude/skills/intermediaire-liaison/SKILL.md`).
- `reset_compteur.sh <rapport>` : remet le compteur à zéro si le rapport est valide (présent, moins de 2 min, 8 sections). Sinon écrit `FAUX_RESET` dans `journal.log`.
- `surveillance.sh` : boucle sans modèle, à lancer en arrière-plan. Retard > 35 min ou FAUX_RESET récent : crée `RELANCE.flag` (1er échec), puis `ALERTE.txt` et sortie code 2 (2e échec).
- `RELANCE.flag` : demande à l'intermédiaire un rapport immédiat ; il le supprime après le reset.
- `compteur.txt` : date epoch du dernier reset valide. `echecs.txt` : nombre d'échecs consécutifs.
- `ALERTE.txt` : présent = l'orchestrateur doit intervenir.
- `journal.log` : historique des resets, refus et échecs.
