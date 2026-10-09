# Capacités transverses : propriétaire et interface publique

- **Date** : 2026-10-09 (T-036).
- **Règle** : une capacité partagée est possédée par son paquet ; un module métier la **consomme** et ne la possède jamais (`ARCHITECTURE.md` §2 et §3.2).
- **Propriétaire fonctionnel** : le dépôt ne désigne aucune personne. Ce document nomme le **propriétaire technique** (le paquet, dont le `service.py` est l'unique point d'entrée). Le propriétaire fonctionnel reste **à désigner** par le coordinateur ; ce point est listé dans `exceptions-importlinter.md` §5.

## 1. `files` (documents)

| Élément | Valeur |
|---|---|
| Paquet | `app/files/` |
| Interface publique | `app/files/service.py` : `create_document`, `create_document_for_trusted_caller`, `create_document_link`, `list_document_links_for_entity`, `count_documents_by_entity`, `get_document_download_url`, `delete_document` |
| Schémas exposés | `app/files/schemas.py` (`DocumentResponse`, `DocumentLinkResponse`, etc.) |
| Permissions possédées | `app/files/permissions.py` : `DOCUMENT_CREATE`, `DOCUMENT_READ`, `DOCUMENT_READ_SENSITIVE`, `DOCUMENT_MANAGE`, `DOCUMENT_DELETE` |
| Données (interdites hors paquet) | `app/files/models.py` : `Document`, `DocumentLink` |
| Consommateurs actuels | `zylo_liquid` (bon de commande PDF : `create_document_for_trusted_caller`, `DocumentResponse`, permissions de seed) |
| Propriétaire technique | le paquet `app/files/` |
| Règles d'usage | voir `files-usage-zylo-liquid.md` |

## 2. `location` (GPS, suivi, arrêts)

| Élément | Valeur |
|---|---|
| Paquet | `app/location/` |
| Interface publique | `app/location/service.py` : GPS (`create_gps_device`, `update_gps_device`, `unassign_gps_device`, `list_gps_devices`, `ingest_truck_position`, `get_or_create_gps_ingest_credential`), positions et arrêts (`list_truck_positions`, `list_vessel_positions`, `list_truck_stops`, `list_vessel_stops`, `run_truck_stop_detection`), suivi (`create_tracking_location`, etc.), commentaires et réconciliations d'arrêts |
| Permissions possédées | `app/location/permissions.py` : `GPS_DEVICE_READ`, `TRACKING_LOCATION_READ`, etc. |
| Données (interdites hors paquet) | `app/location/models.py` : `GpsDeviceAssignment`, `TruckPositionPing`, etc. |
| Dépendances délibérées | `Truck`/`TRUCK_READ` (zylo_liquid) et `Vessel`/`VESSEL_READ` (zylo_tanker) pour les positions et arrêts par véhicule (contrôles `TRUCK_READ` / `VESSEL_READ`). Exception documentée (`exceptions-importlinter.md` §2). |
| Événement publié | `TruckStopUnqualified` (consommé par `alerts`, abonnement dans `app/main.py`) |
| Consommateurs actuels | `zylo_liquid` et `zylo_tanker` ne lisent que les permissions ; `zylo_tanker/dev_seed` écrit dans les tables de `location` (**violation dans le snapshot wip, pas dans base-T004**, voir `exceptions-importlinter.md` §3) |
| Propriétaire technique | le paquet `app/location/` |

## 3. `alerts` (alertes)

| Élément | Valeur |
|---|---|
| Paquet | `app/alerts/` |
| Interface publique | `app/alerts/service.py` : `upsert_active_alert`, `auto_resolve_alert`, `find_alert_in_window`, `list_alerts`, `get_alert`, `acknowledge_alert`, `resolve_alert`, `handle_truck_stop_unqualified` (abonné d'événement) |
| Permissions possédées | `app/alerts/permissions.py` : `ALERT_READ`, `ALERT_ACKNOWLEDGE`, `ALERT_MANAGE` |
| Données (interdites hors paquet) | `app/alerts/models.py` : `Alert` (FK résolues par nom de table, sans import Python) |
| Dépendances délibérées | `Station`/`Tank`/`Truck` (zylo_liquid) et `Vessel` (zylo_tanker) pour les jointures de portée de `list_alerts` et `_get_alert_and_tank`. Exception documentée (`exceptions-importlinter.md` §2). |
| Consommateurs actuels | `zylo_liquid` (appels `upsert_active_alert`, `auto_resolve_alert`, `find_alert_in_window` dans `zylo_liquid/service.py`) ; `zylo_tanker` ne consomme pas `alerts` aujourd'hui |
| Propriétaire technique | le paquet `app/alerts/` |

## 4. `integrations/holykell` (adaptateur télémétrie)

| Élément | Valeur |
|---|---|
| Paquet | `app/integrations/holykell/` |
| Interface publique | `client.py` (login, appels HTTP, DTO `HolykellSensorReading`) |
| Consommateur | `zylo_liquid/telemetry_sync.py` uniquement |
| Propriétaire technique | le paquet `app/integrations/holykell/` |
| Règle | l'adaptateur ne connaît jamais le domaine qu'il sert (`holykell-never-imports-zylo-liquid`) |
