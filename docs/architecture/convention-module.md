# Convention d'un module métier et checklist d'ajout

- **Statut** : en vigueur ; déjà appliquée à `zylo_liquid` et `zylo_tanker`.
- **Source** : ancien `CLAUDE.md` du backend, sections « Convention d'un module métier » et « Checklist » (détail dans [`regles-claude-md.md`](../process/regles-claude-md.md)).

## Structure d'un module

```text
app/modules/<domaine>/
├── models.py        tables SQLAlchemy : camelCase, anglais, commentées
├── schemas.py       Pydantic (requête, réponse)
├── service.py       logique métier et requêtes : jamais dans le router
├── router.py        endpoints FastAPI : appelle service.py, protège par require_permission()
├── permissions.py   constantes "domaine.entite.read" / "domaine.entite.manage" ; un fichier par domaine
├── algorithms.py    (si besoin) algorithmes purs, testables isolément
├── seed.py          enregistrement des permissions connues (appelé au démarrage)
├── roles_seed.py    (si besoin) rôles par défaut du module, rattachés à moduleCode
└── dev_seed.py      (si besoin) données de démonstration, jamais en production
```

Un module reprend cette structure à l'identique. Les capacités partagées (`files`, `alerts`, `location`, `integrations/`) suivent la même structure, mais au premier niveau de `app/`.

## Checklist d'ajout d'un module ou d'une capacité

1. Package avec `models.py`, `schemas.py`, `service.py`, `router.py`, `permissions.py` (+ `seed.py`, `algorithms.py` si besoin).
2. Toute donnée exposée à un autre module passe par les fonctions publiques de `service.py`. Aucun export de `models.py` au-delà du module.
3. Router branché dans `app/api/v1/router.py` (un import, un `include_router`, préfixe `/api/v1/<nom>`).
4. Permissions enregistrées via `seed.py`, appelé depuis `app/main.py`.
5. Module déclaré dans `modules_registry` (activable par organisation), sauf capacité transverse toujours active (`files`, `alerts`).
6. Contrat `.importlinter` ajouté ou étendu **avant** le premier import inter-modules.
7. Un fait observable par d'autres modules : envisager un événement (`app/shared/events.py`) plutôt qu'un appel direct multiplié. Voir [`appel-direct-ou-evenement.md`](appel-direct-ou-evenement.md).

Décision liée : [ADR 0002](decisions/0002-roles-par-module.md) pour les rôles de module.
