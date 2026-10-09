# Règles dures de la frontière entre modules

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

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
