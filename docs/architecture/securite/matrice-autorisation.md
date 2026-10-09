# Matrice d'autorisation (T-023)

Généré par `scripts/dev/generer_matrice_autorisation.py` : ne pas éditer à la main.
Source : les dépendances FastAPI des routes (`tests/route_inventory.py`).

## Permission -> routes

| Permission | Routes |
|---|---|
| `billing.subscription.manage` | `POST /api/v1/billing/organizations/{organization_id}/subscriptions` |
| `identity.organization.manage` | `GET /api/v1/modules/organizations/{organization_id}/zylo-liquid/protected-demo`<br>`PATCH /api/v1/organizations/{organization_id}`<br>`GET /api/v1/organizations/{organization_id}/protected-demo` |
| `identity.user.manage` | `POST /api/v1/organizations/{organization_id}/users`<br>`PATCH /api/v1/organizations/{organization_id}/users/{user_id}`<br>`POST /api/v1/organizations/{organization_id}/users/{user_id}/invitation` |
| `modules.module.manage` | `POST /api/v1/modules/organizations/{organization_id}/activate`<br>`POST /api/v1/modules/organizations/{organization_id}/deactivate` |
| `rbac.grant.manage` | `POST /api/v1/rbac/organizations/{organization_id}/grants`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/grants/{grant_id}`<br>`GET /api/v1/rbac/organizations/{organization_id}/users/{user_id}/grants` |
| `rbac.role.manage` | `POST /api/v1/rbac/organizations/{organization_id}/module-roles`<br>`POST /api/v1/rbac/organizations/{organization_id}/module-roles/assignments`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/module-roles/assignments/{assignment_id}`<br>`GET /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/members`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role`<br>`PUT /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role`<br>`GET /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role-preview`<br>`POST /api/v1/rbac/organizations/{organization_id}/roles`<br>`PUT /api/v1/rbac/organizations/{organization_id}/roles/{role_id}/permissions`<br>`POST /api/v1/rbac/organizations/{organization_id}/user-roles`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/user-roles/{assignment_id}` |
| `shared.currency.manage` | `POST /api/v1/currencies`<br>`PATCH /api/v1/currencies/{currency_id}` |
| `shared.currency.read` | `GET /api/v1/currencies` |
| `shared.exchangeRate.manage` | `POST /api/v1/exchange-rates` |
| `shared.exchangeRate.read` | `GET /api/v1/exchange-rates` |
| `shared.geo.read` | `GET /api/v1/cities`<br>`GET /api/v1/countries` |
| `zyloLiquid.alert.acknowledge` | `POST /api/v1/zylo-liquid/alerts/{alert_id}/acknowledge` |
| `zyloLiquid.alert.manage` | `PATCH /api/v1/zylo-liquid/alerts/{alert_id}` |
| `zyloLiquid.alert.read` | `GET /api/v1/zylo-liquid/alerts/{alert_id}` |
| `zyloLiquid.cash.read` | `GET /api/v1/zylo-liquid/cash/network-summary`<br>`GET /api/v1/zylo-liquid/cash/stations/{station_id}`<br>`GET /api/v1/zylo-liquid/cash/tanks/{tank_id}` |
| `zyloLiquid.delivery.read` | `GET /api/v1/zylo-liquid/deliveries-in-progress`<br>`GET /api/v1/zylo-liquid/deliveries/{delivery_id}` |
| `zyloLiquid.fuelProduct.manage` | `POST /api/v1/zylo-liquid/fuel-products`<br>`PATCH /api/v1/zylo-liquid/fuel-products/{fuel_product_id}` |
| `zyloLiquid.fuelProduct.read` | `GET /api/v1/zylo-liquid/fuel-products`<br>`GET /api/v1/zylo-liquid/fuel-products/{fuel_product_id}` |
| `zyloLiquid.holykellAccount.read` | `GET /api/v1/zylo-liquid/holykell-accounts`<br>`GET /api/v1/zylo-liquid/holykell-accounts/{account_id}/sync-status` |
| `zyloLiquid.leakEvent.read` | `GET /api/v1/zylo-liquid/leak-events/{leak_event_id}` |
| `zyloLiquid.priceHistory.create` | `PATCH /api/v1/zylo-liquid/prices/{price_id}` |
| `zyloLiquid.priceHistory.read` | `GET /api/v1/zylo-liquid/prices/{price_id}` |
| `zyloLiquid.pump.manage` | `POST /api/v1/zylo-liquid/pumps`<br>`PATCH /api/v1/zylo-liquid/pumps/{pump_id}` |
| `zyloLiquid.pump.read` | `GET /api/v1/zylo-liquid/pumps/{pump_id}` |
| `zyloLiquid.station.manage` | `POST /api/v1/zylo-liquid/stations`<br>`PATCH /api/v1/zylo-liquid/stations/{station_id}`<br>`POST /api/v1/zylo-liquid/stations/{station_id}/deactivate`<br>`POST /api/v1/zylo-liquid/stations/{station_id}/reactivate` |
| `zyloLiquid.station.read` | `GET /api/v1/zylo-liquid/network/snapshot`<br>`GET /api/v1/zylo-liquid/network/summary`<br>`GET /api/v1/zylo-liquid/stations/{station_id}`<br>`GET /api/v1/zylo-liquid/stations/{station_id}/current-state` |
| `zyloLiquid.stationFuelProduct.manage` | `POST /api/v1/zylo-liquid/station-fuel-products`<br>`PATCH /api/v1/zylo-liquid/station-fuel-products/{association_id}` |
| `zyloLiquid.stationFuelProduct.read` | `GET /api/v1/zylo-liquid/station-fuel-products` |
| `zyloLiquid.tank.manage` | `POST /api/v1/zylo-liquid/tanks`<br>`PATCH /api/v1/zylo-liquid/tanks/{tank_id}` |
| `zyloLiquid.tank.read` | `GET /api/v1/zylo-liquid/tanks/{tank_id}`<br>`GET /api/v1/zylo-liquid/tanks/{tank_id}/current-state`<br>`GET /api/v1/zylo-liquid/tanks/{tank_id}/measurements` |
| `zyloLiquid.tankCalibration.manage` | `PUT /api/v1/zylo-liquid/tanks/{tank_id}/calibration-points` |
| `zyloLiquid.tankCalibration.read` | `GET /api/v1/zylo-liquid/tanks/{tank_id}/calibration-points` |
| `zyloLiquid.tankSensorMapping.manage` | `POST /api/v1/zylo-liquid/tank-sensor-mappings`<br>`POST /api/v1/zylo-liquid/tank-sensor-mappings/{mapping_id}/close` |
| `zyloLiquid.tankSensorMapping.read` | `GET /api/v1/zylo-liquid/tank-sensor-mappings` |

## Routes sans permission ni appartenance

- `GET /`
- `POST /api/v1/auth/activate`
- `POST /api/v1/auth/change-password`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/register`
- `GET /api/v1/billing/plans`
- `POST /api/v1/billing/plans`
- `POST /api/v1/export/docx`
- `POST /api/v1/export/xlsx`
- `GET /api/v1/health`
- `GET /api/v1/health/error-demo`
- `POST /api/v1/import/xlsx`
- `GET /api/v1/modules`
- `GET /api/v1/notifications/vapid-public-key`
- `GET /api/v1/organizations`
- `POST /api/v1/organizations`
- `GET /api/v1/storage/local/{storage_reference}`
- `PATCH /api/v1/users/{user_id}`
- `POST /api/v1/zylo-liquid/gps/ingest`
- `POST /api/v1/zylo-tanker/gps/ingest`
