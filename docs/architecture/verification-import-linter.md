# Vérification à chaque phase et contrats import-linter

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

## 6. Vérification à chaque phase

1. Suite de tests backend (`pytest`) verte avant de committer.
2. Contrat `import-linter` de la phase passe en CI.
3. Test manuel de bout en bout de la fonctionnalité déplacée (ex. Phase 1 :
   upload + téléchargement d'un document ; Phase 2 : carte Camions + flux
   SSE toujours fonctionnels ; Phase 3 : création/acquittement d'une
   alerte ; Phase 4 : synchronisation Holykell toujours opérationnelle).
4. Un commit par phase — chaque phase doit pouvoir être déployée et
   vérifiée en production indépendamment des suivantes.

## 7. `import-linter` — ce qu'il fait et ne fait pas

Contrats définis dans `.importlinter` (racine du dépôt), exécutés en CI :
un import qui viole un contrat fait échouer le build, indépendamment de la
relecture humaine. C'est ce qui transforme les règles de ce document d'une
convention (facile à oublier sous pression) en contrainte vérifiée.

10 contrats en place (Phases 0-6, voir `.importlinter`) :
- `identity-rbac-not-reachable-from-internals` — `zylo_liquid` ne peut
  jamais importer `app.identity.security`/`app.rbac.security` (détails
  internes), seulement leurs points d'entrée publics.
- `zylo-liquid-files-through-service-only` / `files-never-imports-zylo-liquid`
  — `zylo_liquid` n'accède à Files que via `app.files.service`, jamais
  `app.files.models` ; Files ne dépend jamais de `zylo_liquid`.
- `zylo-liquid-location-through-service-only` — même règle pour Location.
- `location-never-imports-zylo-liquid-logic` — Location peut importer
  `app.modules.zylo_liquid.models`/`permissions` (dépendance délibérée et
  documentée : `Truck`/`TRUCK_READ`, voir §5 et la docstring de
  `app/location/service.py`), mais jamais son `service.py`/`router.py`/
  `schemas.py` — Location ne dépend jamais de la logique métier ou des
  routes de zylo_liquid, seulement de ses types.
- `zylo-liquid-location-alerts-through-service-only` — ni `zylo_liquid` ni
  `location` ne lisent `app.alerts.models` directement, seulement
  `app.alerts.service` (même règle que Files/Location).
- `alerts-never-imports-zylo-liquid-logic` — Alertes peut importer
  `app.modules.zylo_liquid.models` (dépendance délibérée et documentée :
  `Station`/`Truck`/`Tank` pour les jointures de portée de `list_alerts`/
  `_get_alert_and_tank`, voir la docstring de `app/alerts/service.py`),
  mais jamais son `service.py`/`router.py`/`schemas.py`. Alerts et
  Location sont donc, à ce stade, les deux seules capacités où la
  dépendance va dans les deux sens ; Files reste strictement à sens
  unique.
- `alerts-models-no-zylo-liquid-location-import` — contrairement à
  `app/alerts/service.py`, `app/alerts/models.py` n'importe RIEN de
  `zylo_liquid`/`location` : les FK d'`Alert` sont résolues par nom de
  table au moment du mapper configure (même mécanisme que
  `app/location/models.py` vers `zyloLiquidTruck.id`), jamais par un
  import Python.
- `holykell-never-imports-zylo-liquid` — `app.integrations.holykell` ne
  dépend jamais de `zylo_liquid` : l'adaptateur ne doit jamais connaître le
  domaine qu'il sert. Pas de contrat symétrique "zylo_liquid n'accède à
  Holykell que via son service public" comme pour Files/Location/Alerts :
  Holykell n'expose qu'un seul fichier public
  (`app.integrations.holykell.client` : login, appels HTTP, DTO
  `HolykellSensorReading`), pas de `models.py` séparé à protéger — il n'y a
  encore rien d'autre à cacher derrière.
- `capabilities-never-import-each-other` (Phase 6, `type = independence`)
  — Files/Location/Alertes/Holykell ne s'importent jamais entre elles, ni
  directement ni indirectement. Seul type de contrat `import-linter` conçu
  pour ce besoin précis : les 9 contrats précédents ne protègent chacun
  qu'un sens `zylo_liquid`<->capacité, jamais capacité<->capacité. Un
  `ignore_imports` documenté dans `.importlinter` élimine un faux positif
  transitif réel (chaque routeur de capacité dépend de
  `app.modules_registry.service` pour `require_module_active`, qui importe
  paresseusement `zylo_liquid.roles_seed` au moment de l'activation du
  module — rien à voir avec une capacité qui en atteint une autre).

Migration terminée (Phases 0-6) — plus de contrats "prévus" en attente.
Le prochain contrat à écrire sera celui du prochain module qui s'extrait,
suivant exactement le même patron que ci-dessus (jamais une nouvelle
convention à inventer).

Ce qu'`import-linter` ne vérifie pas (à garder en tête, ce ne sont pas des
trous dans l'outil mais des limites connues) : il ne vérifie ni la
cohérence des schémas Pydantic entre modules, ni qu'un événement publié a
bien au moins un abonné cohérent, ni les requêtes SQL brutes qui
contourneraient un ORM (aucun cas connu aujourd'hui). La revue de code reste
nécessaire pour ces aspects.
