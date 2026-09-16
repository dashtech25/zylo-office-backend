# Architecture backend — Zylo Office

Détail complet de l'architecture "monolithe modulaire" et de la migration en
cours pour y arriver. Les règles courtes à respecter au quotidien sont dans
`CLAUDE.md` (lu automatiquement en début de session) — ce document explique
le "pourquoi" et le "comment" en profondeur, sert de référence quand une
règle du `CLAUDE.md` n'est pas assez précise pour un cas concret.

Source du plan de migration approuvé (hors de ce dépôt, document de
cadrage) : `plan-migration/architecture-migration.md` dans le dépôt
`zylo_liquid_prototype`. Ce fichier-ci en est la traduction opérationnelle
pour ce dépôt, tenue à jour au fil des phases livrées.

## 1. Pourquoi un monolithe modulaire, pas des microservices

Zylo Office tourne aujourd'hui sur un seul VPS, avec une petite équipe.
Découper en microservices maintenant ajouterait :
- un bus de messages distribué (Kafka/RabbitMQ) et son exploitation,
- des déploiements et une observabilité par service,
- de la complexité réseau (retries, timeouts, cohérence éventuelle)

...pour un problème que le projet n'a pas : aucun module n'a besoin de
scaler indépendamment, la charge actuelle tient largement sur une seule
instance. Le coût serait payé tout de suite, le bénéfice (scalabilité
indépendante, déploiement isolé par équipe) n'a pas d'usage réel aujourd'hui.

La réponse retenue après la formation d'architecture (couplage/cohésion,
comparatif des architectures, patrons de communication) : **un seul
déploiement, une seule base Postgres, un seul historique Alembic — mais une
discipline de frontières entre modules imposée et vérifiée techniquement**
(voir §4, `import-linter`). Si un jour un module a un besoin de charge
mesuré (pas supposé) qui justifie une extraction physique, les frontières
propres rendent cette extraction possible sans réécriture — mais ce n'est
jamais le point de départ par défaut, et rien dans ce plan n'anticipe une
telle extraction avant qu'elle soit prouvée nécessaire.

## 2. Trois catégories de packages, jamais mélangées

```
app/
├── core/                    # fondation transverse : sécurité JWT, erreurs globales
├── shared/                  # briques génériques sans logique métier : pagination, devises, geo, storage bas niveau
├── identity/ rbac/ audit/   # SOCLE — comptes, permissions, journal d'audit
├── files/ location/         # CAPACITÉS PARTAGÉES — en cours d'extraction (voir §5)
│   alerts/ integrations/holykell/    même statut : transverses, jamais propriété d'un module métier
├── modules/
│   └── zylo_liquid/         # MÉTIER — logique carburant, un dossier par domaine (demain crm/, stock/...)
└── api/v1/router.py         # agrégation des routers, un include_router par module
```

Différence clé entre "capacité partagée" et "domaine du socle" : le socle
(`identity`/`rbac`/`audit`) définit *qui peut faire quoi* — c'est
transversal à toute action de l'application. Une capacité partagée
(`files`/`location`/`alerts`/`integrations/holykell`) rend un *service
technique* réutilisable par plusieurs modules métier, mais n'a pas de sens
sans qu'un module métier l'utilise (un fichier existe toujours pour quelque
chose : un bon de commande, une facture...). D'où la règle : **un module
métier consomme une capacité partagée, il ne la possède jamais** — c'est
toujours le module métier qui décide *quand* créer un document/une
alerte/un suivi GPS, jamais l'inverse.

## 3. Règles dures

### 3.1 Jamais de requête directe sur les tables d'un autre module

Un module ne fait jamais `from app.files.models import Document` pour
construire une requête SQLAlchemy lui-même. Il appelle une fonction
publique de `app.files.service`.

**Exemple déjà en place** (Phase 1 terminée) :
`generate_purchase_order_document` dans `app/modules/zylo_liquid/service.py`
appelle `app.files.service.create_document` /
`app.files.service.create_document_link` — il ne construit jamais
`Document`/`DocumentLink` lui-même. C'est le patron à reproduire pour tout
nouveau point d'appel vers `files`, `location`, `alerts` ou
`integrations/holykell`.

### 3.2 Un module métier ne possède jamais une capacité partagée

`zylo_liquid` (et demain `crm`, `stock`...) ne doit jamais redéfinir sa
propre table de documents, sa propre logique d'alerte ou son propre client
HTTP vers un fournisseur externe. S'il a besoin d'un de ces services, il
appelle le `service.py` de la capacité correspondante.

Exception documentée et volontaire : `RegulatoryDocument` reste dans
`zylo_liquid` (pas dans `files`) parce que ce n'est pas un fichier stocké
(pas de `storageReference`) — c'est une donnée métier de conformité
réglementaire par station. La règle n'est pas "tout ce qui contient le mot
document va dans `files`", c'est "un objet qui *est* réellement un fichier
stocké (upload/téléchargement) appartient à `files`".

De même, `Truck`/`Carrier` (le véhicule lui-même, objet métier carburant)
reste dans `zylo_liquid`, seul le suivi GPS (`GpsDevice`,
`TruckPositionPing`, ...) va dans `location`.

### 3.3 Toute intégration externe passe par un adaptateur

Aucun module métier ne doit contenir d'appel `requests`/SDK brut vers un
service externe. Le patron Holykell (Phase 4) :

- `app/integrations/holykell/client.py` : login, appels HTTP, mapping vers
  un DTO interne propre, retry + timeout explicites.
- `app/modules/zylo_liquid/telemetry_sync.py` garde la boucle de
  synchronisation et les données de configuration propres au métier
  (`HolykellAccount`, `HolykellDeviceRegistry`), mais délègue tout le
  HTTP/auth à `holykell.client` au lieu de le faire lui-même.

Avant cette extraction, `telemetry_sync.py` était le code le plus proche
d'un adaptateur mais restait directement couplé aux modèles SQLAlchemy de
Liquid — exactement le problème que l'extraction corrige : le code métier
ne doit jamais avoir à connaître la forme des réponses HTTP d'un
fournisseur externe.

## 4. Appel direct vs événement en mémoire

Deux patrons de communication entre modules, jamais un troisième (pas
d'appel HTTP interne entre modules du même process, pas de queue externe
pour une simple notification interne) :

**Appel direct** (`app.x.service.fn(...)`) — quand l'appelant a besoin
d'une réponse pour continuer son traitement dans la même requête/transaction
(id créé, succès/échec, URL signée...). C'est un couplage assumé et normal :
l'appelant connaît l'API publique de l'appelé.
> Exemple en place : `generate_purchase_order_document` a besoin de l'id du
> `Document` créé pour construire la réponse — appel direct à
> `app.files.service.create_document`.

**Événement en mémoire** (`publish("NomEvenement", payload)`) — quand le
code signale un fait qui vient de se produire, sans savoir ni se soucier de
qui réagit (zéro, un ou plusieurs abonnés, aujourd'hui ou demain). L'émetteur
ne référence jamais le module abonné.
> Exemple prévu (Phase 5) : la détection d'arrêt non qualifié dans
> `location` publie `TruckStopUnqualified` au lieu d'appeler directement
> `app.alerts.service._upsert_active_alert`. `alerts` s'abonne à cet
> événement. `location` n'importe jamais `app.alerts` — si demain un second
> module veut aussi réagir à un arrêt non qualifié (ex. notifications), il
> s'abonne au même événement sans que `location` change une ligne.

Mécanique (Phase 5) : `app/shared/events.py` expose `subscribe(event_name,
handler)` / `publish(event_name, payload)`. Les handlers s'exécutent après
le commit de la transaction qui déclenche l'événement (jamais avant — un
handler ne doit jamais voir un état non committé).

**Règle de décision courte** : besoin du retour pour continuer → appel
direct. Simple signal, nombre de consommateurs variable → événement. Dans le
doute, commencer par un appel direct (plus simple, plus traçable) et ne
migrer vers un événement que lorsqu'un deuxième consommateur réel apparaît
— ne pas anticiper des abonnés hypothétiques.

## 5. État de la migration (mise à jour au fil des phases livrées)

Le code vit aujourd'hui presque entièrement dans
`app/modules/zylo_liquid/` (models.py, service.py, router.py de plusieurs
milliers de lignes). La migration extrait les capacités qui ne lui
appartiennent pas, une phase à la fois, chacune livrable et vérifiable
indépendamment (jamais un gros commit unique) :

| Phase | Contenu | Statut |
|---|---|---|
| 0 | Outillage : `import-linter` + premier contrat minimal, intégré CI | fait — `8020c61` |
| 1 | Extraire `app/files/` (`Document`/`DocumentLink`, déjà découplés par `linkedEntityType`/`linkedEntityId` texte libre, pas de FK stricte) | fait — `8020c61` |
| 2 | Extraire `app/location/` (GPS : `GpsDevice`, `TruckPositionPing`, détection d'arrêt...) — FK stricte conservée vers `zyloLiquidTruck.id`, URLs `/api/v1/zylo-liquid/...` gardées stables côté frontend | fait — `8020c61` |
| 3 | Extraire `app/alerts/` (`Alert`, FK strictes conservées vers station/truck/tank/product — pas de redesign de schéma dans cette phase) | fait — `74e772c` |
| 4 | Extraire `app/integrations/holykell/` (client HTTP + DTO), supprimer `scripts/sync_holykell_live.py` (legacy, déjà remplacé par la boucle en process) | — |
| 5 | `app/shared/events.py` (`subscribe`/`publish`), premier cas d'usage réel : `TruckStopUnqualified` (location → alerts) | — |
| 6 | Étendre les contrats `import-linter` à tous les nouveaux modules, CI bloquante sur violation | — |

Note : Phases 1 et 2 ont été livrées dans un même commit (`8020c61`,
2026-09-15) — travail enchaîné sans commit intermédiaire entre les deux.
Phase 3 et suivantes reprennent la règle « un commit par phase ».

Mettre à jour la colonne Statut quand une phase est livrée (référencer le
commit). Ne pas commencer une phase avant que la précédente soit vérifiée
en production (voir §6).

Décisions déjà actées à ne pas rouvrir sans besoin prouvé :
- Pas de découplage polymorphe complet d'`Alert` (suppression des FK) —
  option future si un vrai besoin de séparation totale apparaît.
- Pas d'extraction physique en microservice d'aucun module — seulement sur
  charge mesurée, jamais par défaut (voir §1).
- Frontend : aligner les mêmes frontières côté Next.js (un écran qui a
  besoin de `files` et `zylo_liquid` appelle deux endpoints distincts) —
  après stabilisation du backend, hors périmètre de ce document.

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

8 contrats en place (Phases 0-3, voir `.importlinter`) :
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

Contrats prévus à mesure que Phases 4-6 avancent (à ajouter dans
`.importlinter` au moment de chaque extraction, pas après coup) :
- `app.integrations.holykell` ne s'importe jamais directement avec
  `app.alerts`/`app.location`/`app.files`, ni ne remonte vers
  `app.modules.zylo_liquid`.

Ce qu'`import-linter` ne vérifie pas (à garder en tête, ce ne sont pas des
trous dans l'outil mais des limites connues) : il ne vérifie ni la
cohérence des schémas Pydantic entre modules, ni qu'un événement publié a
bien au moins un abonné cohérent, ni les requêtes SQL brutes qui
contourneraient un ORM (aucun cas connu aujourd'hui). La revue de code reste
nécessaire pour ces aspects.
