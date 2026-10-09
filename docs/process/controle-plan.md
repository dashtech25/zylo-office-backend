# Contrôle de cohérence du plan

- **Statut** : en vigueur (T-016). Script : `scripts/docs/check_plan.py` (stdlib Python, sans dépendance).
- **Source** : les fiches de docs/plans/taches (une par tâche). Le registre et la liste d'issues en sont dérivés.

## Commandes

```bash
python3 scripts/docs/check_plan.py            # contrôle seul ; code 1 si erreur
python3 scripts/docs/check_plan.py --generer  # régénère REGISTRE_TACHES.md et ISSUES_A_CREER.md, puis contrôle
python3 scripts/docs/check_plan.py --gh       # affiche les commandes gh à relire (n'exécute rien)
```

## Ce qui est contrôlé

- Dépendances existantes ; vague jamais décroissante le long d'une dépendance ; pas de cycle ; niveau strictement supérieur à celui des dépendances.
- Ports : formule back 3100+n, front dev 3200+n, front prod 3300+n ; ports réservés (3001, 3002, 3055) et interdits (3006, 3007) non utilisés ; pas de collision entre numéros.
- Bases de test : `zylo_tNNN[lettre]_test` uniquement ; jamais `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette`.
- Décisions citées : le fichier de question indiqué dans la fiche existe.
- Registre et issues à jour par rapport aux fiches (sinon « non régénéré »).
- Dans docs/process/, les chemins de docs et de scripts cités entre accents graves existent.

## Limites

- Le script ne lit pas GitHub : il ne sait pas si une issue existe déjà.
- Les labels `module:*` et `blocked:*` ne sont pas générés (voir `labels.md`).
