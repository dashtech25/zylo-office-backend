# Validation avant livraison

Liste de contrôle à passer, dans l'ordre, avant de marquer une tâche « À vérifier ». Chaque case qui échoue bloque la livraison.

## Code (backend)

- [ ] `.venv/bin/pytest tests/<fichiers touchés>` vert, puis `.venv/bin/pytest` complet quand le changement touche le socle (rbac, auth, identity, core).
- [ ] `.venv/bin/alembic upgrade head` sur une base de test ; `alembic downgrade -1` testé si une migration est ajoutée.
- [ ] `scripts/check_ports.sh` : aucun port interdit (3006, 3007).
- [ ] `scripts/dev/controle_fichiers_sensibles.sh --staged` : aucun dump, `.env` ou clé dans l'index.
- [ ] `import-linter` vert (contrats de `.importlinter`) quand un import entre packages change.
- [ ] Aucun secret ni valeur de clé dans le diff, les journaux ou les réponses d'API.

## Documentation

- [ ] `python3 scripts/docs/check_plan.py` vert (fiches cohérentes, registre régénéré).
- [ ] `scripts/docs/verifier_liens.sh` : zéro lien cassé.
- [ ] `scripts/docs/generer_index.sh` relancé si des fichiers ont été ajoutés ou déplacés.
- [ ] Chaque règle retirée d'un `CLAUDE.md` a une destination.
- [ ] Décision durable prise : ADR créée ; question tranchée reportée.

## Process

- [ ] Commits en français, un sujet par commit, trailers `Co-Authored-By` et `Claude-Session` présents.
- [ ] Fiche de tâche à jour (statut « À vérifier », dépendances, décisions).
- [ ] Aucune fusion, aucun push, aucune issue créée sans accord écrit.

Limite connue : la CI est désactivée (`ci.yml.disabled`, DOC-001). Ces contrôles sont donc manuels tant que la CI n'est pas réactivée (T-038a).
