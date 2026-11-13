# Labels GitHub

- **Statut** : en vigueur (T-016). Les labels sont **proposés**, pas créés : aucune issue ni label n'est créé sur GitHub tant que la visibilité du dépôt n'est pas tranchée (`docs/questions/process/visibilite-depot-requirements.md`).
- **Source** : les colonnes des fiches de docs/plans/taches. `check_plan.py --gh` affiche les commandes `gh` (rien n'est exécuté).

## Familles

| Préfixe | Valeurs | Source dans la fiche | Rôle |
|---|---|---|---|
| `priority:` | `P0`, `P1`, `P2`, `P3` | Priorité | P0 bloquant (sécurité, IDOR, secrets) ; P1 important ; P2 utile ; P3 hygiène |
| `wave:` | `0`, `1`, `2`, `3` | Vague | Jalon de revue humaine. La vague ne décroît jamais le long d'une dépendance |
| `area:` | `iam`, `security`, `zylo-liquid`, `frontend`, `backend`, `socle`, `ci`, `docs`, `process` | Domaine | Domaine fonctionnel |
| `type:` | `security`, `refactor`, `test`, `chore`, `feature`, `docs`, `ci` | Type | Nature du changement |
| `repo:` | `backend`, `frontend` | Dépôt(s) | Dépôt touché ; une tâche « backend et frontend » reçoit les deux |

## Non générés (à créer à la main si utiles)

- `module:zylo-liquid`, `module:zylo-tanker`, `module:socle` : évoqués par le plan, pas portés par les fiches. Non créés par le script.
- `blocked:decision-client` : pour les tâches « en attente de validation client » (`docs/plans/REGISTRE_TACHES.md`, colonne Statut).

## Règles

- Un label par famille au plus, sauf `repo:` (deux possibles).
- Le titre de l'issue commence par l'identifiant : `[T-016] …`.
- Les labels sont recréés avec `--force` (couleur et description mises à jour), jamais supprimés par le script.
