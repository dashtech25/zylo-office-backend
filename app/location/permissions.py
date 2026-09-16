"""Codes de permission du module Location — valeurs de chaîne inchangées
depuis `app/modules/zylo_liquid/permissions.py` (2026-09-15, extraction
Phase 2) : ce sont ces chaînes exactes qui sont déjà semées dans la table
`permission` et assignées à des rôles existants — les renommer casserait
les affectations de rôles déjà en base. Seul l'emplacement du code Python
bouge, jamais la valeur.

La lecture des positions/arrêts (routes `/trucks/{id}/positions`,
`/trucks/{id}/stops`, `/trucks/live-positions`) reste protégée par
`TRUCK_READ` (module zylo_liquid, pas de permission dédiée ici — éviter
la prolifération, décision actée à l'étape 1 de la mission tracking)."""

GPS_DEVICE_READ = "zyloLiquid.gpsDevice.read"
GPS_DEVICE_MANAGE = "zyloLiquid.gpsDevice.manage"

TRACKING_LOCATION_READ = "zyloLiquid.trackingLocation.read"
TRACKING_LOCATION_MANAGE = "zyloLiquid.trackingLocation.manage"

TRACKING_SETTINGS_MANAGE = "zyloLiquid.trackingSettings.manage"

TRACCAR_CONNECTION_MANAGE = "zyloLiquid.traccarConnection.manage"
