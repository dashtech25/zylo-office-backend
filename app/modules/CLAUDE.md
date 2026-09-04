# app/modules/ — le métier, un dossier par domaine

Voir la directive complète : `/CLAUDE.md` (racine du dépôt).

Un module (`zylo_liquid/`, et demain `crm/`, `stock/`, `accounting/`,
`hr/`, `pos/`) est autonome dans son domaine. Structure de référence — voir
`zylo_liquid/`, déjà en place, à copier à l'identique pour tout nouveau
module :

```text
modules/<domaine>/
├── models.py         # tables SQLAlchemy — camelCase, anglais, commentées
├── schemas.py        # Pydantic request/response
├── service.py        # logique métier + requêtes DB
├── router.py          # endpoints FastAPI (protégés par require_permission())
├── permissions.py      # constantes "domaine.entite.read|manage"
├── algorithms.py        # (si besoin) constantes/algos métier purs
└── seed.py                # enregistrement des permissions au démarrage
```

**Un module ne doit pas dépendre directement d'un autre module métier**
(`zylo_liquid` n'importe pas de futur `app.modules.crm`, et inversement).
Il consomme `core/`, `shared/`, `identity/`, `rbac/` — jamais l'inverse.

Après création d'un module : le brancher dans `app/api/v1/router.py`
(préfixe `/api/v1/<domaine>`), appeler son `seed.py` depuis `app/main.py`,
et le déclarer dans `modules_registry` pour qu'il soit
activable/désactivable par organisation (aucun module ne doit être visible
côté frontend pour une organisation qui ne l'a pas activé).
