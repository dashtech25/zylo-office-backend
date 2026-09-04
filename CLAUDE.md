# Directive d'architecture backend — Zylo Office

**Zylo Office n'est pas une simple API. C'est le socle d'une plateforme
ERP/CRM modulaire** (zylo_liquid aujourd'hui ; CRM, Stock, Comptabilité,
RH, POS demain). Référence globale : `grande_phases.md` (racine du projet
`zylo-office/`, hors ce dépôt). Le frontend a l'équivalent exact de cette
directive dans `zylo-office-frontend/CLAUDE.md` — même philosophie,
adaptée à FastAPI/SQLAlchemy.

**Avant toute intervention dans ce dépôt, lis cette page en entier.**

## La règle qui prime sur tout

    core/     = fondation transverse — jamais spécifique à un module métier
    shared/   = briques réutilisables par tous les modules, sans logique métier propre
    <domaine>/ (identity, rbac, modules_registry, billing) = domaines du SOCLE, pas des modules métier
    modules/<domaine>/ = métier — un dossier par module (zylo_liquid, demain crm, stock...)
    api/v1/   = agrégation des routers, versionnage REST

Direction de dépendance stricte :

    modules/<x> → shared/, core/, identity/, rbac/     (autorisé)
    shared/, core/ → modules/<x>                        (INTERDIT)

`core/` et `shared/` ne doivent jamais importer depuis `app/modules/`. Si
tu es tenté d'y ajouter quelque chose de spécifique à un module (un type,
une règle métier), c'est qu'il appartient à `modules/<domaine>/`.

## Convention d'un module métier (déjà appliquée à `zylo_liquid/`)

```text
app/modules/<domaine>/
├── models.py       # tables SQLAlchemy — camelCase, anglais, commentées
├── schemas.py       # Pydantic (request/response)
├── service.py        # logique métier, requêtes DB — jamais dans le router
├── router.py          # endpoints FastAPI, appelle service.py, protège avec require_permission()
├── permissions.py      # constantes "domaine.entite.read"/"domaine.entite.manage" — UN fichier par domaine, jamais centralisé
├── algorithms.py        # (si besoin) constantes/algos métier purs, testables isolément
├── seed.py                # enregistrement des permissions connues (appelé au démarrage, voir main.py)
└── dev_seed.py              # (si besoin) données de démonstration, jamais exécuté en prod
```

**Un nouveau module (CRM, Stock...) reprend cette structure à l'identique.**
Puis : router branché dans `app/api/v1/router.py` avec un préfixe
(`/api/v1/<domaine>`), permissions enregistrées via `seed.py` appelé dans
`app/main.py`, module déclaré dans `modules_registry` pour être
activable/désactivable par organisation.

## Séquence obligatoire avant de créer quelque chose

    1. Une fonction/schéma générique existe-t-il déjà dans shared/ ?
    2. Un mécanisme transverse existe-t-il déjà dans core/ ?
    3. Étendre un service/router existant plutôt que le dupliquer
    4. Créer seulement si aucun des points ci-dessus ne convient

Exemples déjà en place à réutiliser : `shared/pagination.py` (Page
générique), `shared/schemas.py` (enveloppes de réponse), `shared/currency*`
et `shared/geo*` (référentiels partagés par tous les modules),
`core/security.py` (`get_current_user`, JWT), `core/errors.py`
(gestionnaire d'exceptions global), `rbac/service.py`
(`require_permission()`).

## Règles de nommage et de contrat

- Tables : **camelCase, en anglais, commentées** (convention imposée dès la
  Phase 3, ne pas dévier).
- Permissions : `"<domaine>.<entite>.<read|manage>"` — jamais une chaîne
  ad hoc, jamais un enum de rôles codé en dur dans un router.
- Réponses API : enveloppe `{data, meta:{total,limit,offset}}` en liste et
  `{error:{code,message,details}}` en erreur (déjà standardisé dans
  `shared/schemas.py`/`core/errors.py`) — ne pas réinventer un format par
  endpoint.
- **Jamais de donnée inventée** : si un champ demandé par une maquette ou
  une spec n'a pas de source réelle en base, il est explicitement absent ou
  marqué comme non disponible — jamais une valeur par défaut plausible mais
  fausse (convention déjà suivie dans tout `zylo_liquid`, voir les
  commentaires `service.py`).

## Méthode de travail

Par domaine cohérent (une famille de modèles/service/router à la fois),
avec vérification après chaque changement significatif :

```bash
.venv/bin/pytest                      # tests
.venv/bin/alembic upgrade head        # migrations à jour
.venv/bin/uvicorn app.main:app --reload --port 3007   # démarrage réel, pas juste une lecture de code
```

Ne pas tout refactoriser en un seul changement énorme. Avant un changement
de grande ampleur, vérifier `git status` : si des fichiers sont déjà
modifiés/non commités par un travail en cours (autre session), rester
chirurgical sur ces fichiers plutôt que de les réécrire entièrement, sauf
instruction explicite contraire de l'utilisateur.
