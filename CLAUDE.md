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
    <capacité>/ (files, location, alerts — en cours d'extraction, voir plus bas ;
                 integrations/holykell) = CAPACITÉS PARTAGÉES transverses,
                 pas des modules métier — un domaine métier les CONSOMME,
                 ne les possède jamais
    modules/<domaine>/ = métier — un dossier par module (zylo_liquid, demain crm, stock...)
    api/v1/   = agrégation des routers, versionnage REST

Direction de dépendance stricte :

    modules/<x> → shared/, core/, identity/, rbac/, <capacité>/     (autorisé)
    shared/, core/, <capacité>/ → modules/<x>                        (INTERDIT)
    <capacité> A → <capacité> B (ex. files → alerts)                 (INTERDIT, voir ARCHITECTURE.md)

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

## Architecture : monolithe modulaire, pas de microservices

**Décision actée** (formation d'architecture + migration en cours, voir
`ARCHITECTURE.md` pour le détail complet) : Zylo Office est un **monolithe
modulaire avec événements de domaine en mémoire**. Un seul déploiement, une
seule base Postgres, un seul historique Alembic — mais une discipline de
frontières entre modules aussi stricte que s'ils étaient séparés.
**Pourquoi pas microservices** : un seul VPS, une petite équipe, aucun besoin
de scaler un module indépendamment aujourd'hui — un bus de messages
distribué ou des déploiements séparés seraient un coût d'infrastructure et
d'exploitation disproportionné à la taille actuelle du projet. Le jour où un
vrai besoin de charge mesurée l'exige, l'extraction physique d'un module
reste possible *parce que* les frontières internes sont déjà propres — ce
n'est jamais le point de départ par défaut.

`app/modules/zylo_liquid/` a historiquement absorbé des capacités qui ne lui
appartiennent pas : fichiers, alertes, GPS, intégration Holykell. Elles sont
en cours d'extraction vers des packages de premier niveau (`app/files/`,
`app/location/`, `app/alerts/`, `app/integrations/holykell/`), au même
niveau qu'`identity/`/`rbac/`/`audit/` — **jamais imbriquées dans
`app/modules/`**, même si elles servent aujourd'hui presque exclusivement
`zylo_liquid`. Voir `ARCHITECTURE.md` pour l'état d'avancement de cette
migration phase par phase.

**Règles dures, non négociables :**

1. **Un module n'interroge jamais directement les tables d'un autre module.**
   Toujours via les fonctions publiques de son `service.py` — jamais
   `from app.files.models import Document` puis une requête maison depuis
   `zylo_liquid`. Exemple déjà en place :
   `generate_purchase_order_document` (`app/modules/zylo_liquid/service.py`)
   appelle `app.files.service.create_document`/`create_document_link`, il ne
   construit jamais `Document`/`DocumentLink` lui-même.
2. **Un module métier (zylo_liquid, demain crm/stock) ne possède jamais une
   capacité partagée** (fichiers, alertes, localisation, auth) — il la
   **consomme**. Si un module métier futur a besoin de stocker un fichier ou
   déclencher une alerte, il appelle `app.files.service`/
   `app.alerts.service`, il ne réimplémente rien et ne duplique aucune table.
3. **Toute intégration externe passe par un adaptateur dédié**, jamais un
   appel HTTP/SDK brut mêlé à la logique métier. Ex. Holykell :
   `app/integrations/holykell/client.py` porte le login, les appels HTTP, le
   mapping vers un DTO interne (retry + timeout explicites) ; le code métier
   Liquid (`telemetry_sync.py`) l'appelle, il ne fait jamais lui-même de
   requête HTTP vers l'API Holykell.

**Appel direct (service function) vs événement en mémoire — comment
choisir :**

| | Appel direct (`app.x.service.fn()`) | Événement (`publish("Nom", payload)`) |
|---|---|---|
| Quand | Tu as besoin d'une réponse pour continuer (succès/échec, id créé, URL...) | Tu signales un fait ; zéro, un ou plusieurs modules peuvent réagir, l'émetteur ne les connaît pas |
| Couplage | L'appelant connaît l'API publique de l'appelé | L'appelant ne connaît même pas qui écoute |
| Exemple en place/prévu | `generate_purchase_order_document` → `app.files.service.create_document` (il faut l'id du document créé pour continuer) | `Location` détecte un arrêt non qualifié → publie `TruckStopUnqualified` ; `Alerts` s'y abonne et crée l'alerte, sans que `Location` importe `app.alerts` (voir Phase 5, `app/shared/events.py`) |

En cas de doute : si le code a besoin du retour pour continuer son
traitement dans la même requête, c'est un appel direct. Si c'est "au fait,
ceci vient de se produire" et que le nombre de consommateurs peut varier
sans que l'émetteur ait à changer, c'est un événement.

**`import-linter` fait respecter ces règles techniquement, pas seulement par
convention** — contrats dans `.importlinter` (racine du dépôt), vérifiés en
CI (build en échec si violation). Toujours consulter `.importlinter` avant
d'ajouter un import entre modules : s'il manque un contrat pour un nouveau
module, c'est un signal qu'il faut l'ajouter, pas une permission implicite
d'importer librement. Détail des contrats dans `ARCHITECTURE.md`.

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

## Checklist — ajouter un nouveau module (métier ou capacité)

Même patron que `identity/`/`rbac/`/`audit/`, qu'il s'agisse d'un domaine
métier (`app/modules/<domaine>/`) ou d'une capacité partagée
(`app/<capacité>/`) :

1. Package de premier niveau avec `models.py`/`schemas.py`/`service.py`/
   `router.py`/`permissions.py` (+ `seed.py`, `algorithms.py` si besoin).
2. Toute donnée exposée à d'autres modules passe par des fonctions
   publiques de `service.py` — jamais d'export de `models.py` au-delà du
   module lui-même.
3. Router branché dans `app/api/v1/router.py` (un import + un
   `include_router`, préfixe `/api/v1/<nom>`).
4. Permissions enregistrées via `seed.py`, appelé depuis `app/main.py`.
5. Module déclaré dans `modules_registry` (activable/désactivable par
   organisation) — sauf pour une capacité transverse toujours active
   (ex. `files`, `alerts`).
6. Ajouter/étendre le contrat `.importlinter` correspondant *avant* le
   premier import inter-modules réel (le contrat documente et fait
   respecter la frontière, il ne suit pas après coup).
7. Si le module produit un fait que d'autres pourraient vouloir observer
   sans en dépendre directement (ex. "arrêt camion détecté"), envisager un
   événement (`app/shared/events.py`) plutôt qu'un appel direct multiplié
   vers chaque consommateur potentiel — voir le tableau appel/événement
   ci-dessus.

Détail complet de la migration en cours (quel code bouge, dans quel ordre,
pourquoi) : `ARCHITECTURE.md`.

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
