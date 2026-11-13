# Matrice d'autorisation (T-023)

Généré par `scripts/dev/generer_matrice_autorisation.py` : ne pas éditer à la main.
Source : les dépendances FastAPI des routes (`tests/route_inventory.py`).

## Permission -> routes

| Permission | Routes |
|---|---|
| `audit.export` | `POST /api/v1/audit/exports`<br>`GET /api/v1/audit/exports/{job_id}`<br>`GET /api/v1/audit/exports/{job_id}/telechargement` |
| `billing.invoice.read` | `GET /api/v1/organizations/current/invoices`<br>`GET /api/v1/organizations/current/invoices/{invoice_id}` |
| `billing.subscription.manage` | `POST /api/v1/billing/organizations/{organization_id}/invoices`<br>`POST /api/v1/billing/organizations/{organization_id}/invoices/{invoice_id}/payment-attempts`<br>`POST /api/v1/billing/organizations/{organization_id}/subscriptions` |
| `billing.subscription.read` | `GET /api/v1/organizations/current/entitlements`<br>`GET /api/v1/organizations/current/subscription` |
| `identity.organization.manage` | `GET /api/v1/modules/organizations/{organization_id}/zylo-liquid/protected-demo`<br>`POST /api/v1/organizations/current/closure`<br>`POST /api/v1/organizations/current/reactivation`<br>`POST /api/v1/organizations/current/suspension`<br>`PATCH /api/v1/organizations/{organization_id}`<br>`GET /api/v1/organizations/{organization_id}/protected-demo` |
| `identity.user.manage` | `POST /api/v1/organizations/{organization_id}/users`<br>`PATCH /api/v1/organizations/{organization_id}/users/{user_id}`<br>`POST /api/v1/organizations/{organization_id}/users/{user_id}/invitation` |
| `modules.module.manage` | `POST /api/v1/modules/organizations/{organization_id}/activate`<br>`POST /api/v1/modules/organizations/{organization_id}/deactivate`<br>`PUT /api/v1/organizations/current/modules/{module_id}/activation` |
| `organization.audit.read` | `GET /api/v1/organizations/{organization_id}/module-audit` |
| `organization.entitlement.allocate` | `POST /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations` |
| `organization.entitlement.read` | `GET /api/v1/organizations/{organization_id}/entitlements` |
| `organization.entitlement.revoke` | `DELETE /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations/{user_id}` |
| `organization.members.invite` | `GET /api/v1/organizations/current/invitations`<br>`POST /api/v1/organizations/current/invitations` |
| `organization.members.read` | `GET /api/v1/organizations/current/members` |
| `organization.members.remove` | `DELETE /api/v1/organizations/current/members/{user_id}` |
| `organization.module.activate` | `POST /api/v1/organizations/{organization_id}/modules/{module_id}/activation`<br>`POST /api/v1/organizations/{organization_id}/modules/{module_id}/deactivation` |
| `organization.module.install` | `POST /api/v1/organizations/{organization_id}/modules/{module_id}/installations`<br>`GET /api/v1/organizations/{organization_id}/modules/{module_id}/installations/{operation_id}` |
| `organization.module.read` | `GET /api/v1/organizations/{organization_id}/modules/{module_id}`<br>`GET /api/v1/organizations/{organization_id}/modules/{module_id}/permissions` |
| `organization.module.uninstall` | `DELETE /api/v1/organizations/{organization_id}/modules/{module_id}/installation` |
| `organization.module.upgrade` | `POST /api/v1/organizations/{organization_id}/modules/{module_id}/upgrades` |
| `organization.settings.update` | `PUT /api/v1/organizations/current/settings` |
| `rbac.grant.manage` | `POST /api/v1/organizations/current/members/{user_id}/grants`<br>`DELETE /api/v1/organizations/current/members/{user_id}/grants/{grant_id}`<br>`POST /api/v1/rbac/organizations/{organization_id}/grants`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/grants/{grant_id}`<br>`GET /api/v1/rbac/organizations/{organization_id}/users/{user_id}/grants` |
| `rbac.role.manage` | `PUT /api/v1/organizations/current/members/{user_id}/roles`<br>`GET /api/v1/organizations/current/roles`<br>`GET /api/v1/organizations/current/roles/{role_id}`<br>`GET /api/v1/organizations/{organization_id}/modules/{module_code}/access-evaluation`<br>`POST /api/v1/rbac/organizations/{organization_id}/module-roles`<br>`POST /api/v1/rbac/organizations/{organization_id}/module-roles/assignments`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/module-roles/assignments/{assignment_id}`<br>`GET /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/members`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role`<br>`PUT /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role`<br>`GET /api/v1/rbac/organizations/{organization_id}/modules/{module_code}/users/{user_id}/role-preview`<br>`POST /api/v1/rbac/organizations/{organization_id}/roles`<br>`PUT /api/v1/rbac/organizations/{organization_id}/roles/{role_id}/permissions`<br>`POST /api/v1/rbac/organizations/{organization_id}/user-roles`<br>`DELETE /api/v1/rbac/organizations/{organization_id}/user-roles/{assignment_id}` |
| `shared.currency.manage` | `POST /api/v1/currencies`<br>`PATCH /api/v1/currencies/{currency_id}` |
| `shared.currency.read` | `GET /api/v1/currencies` |
| `shared.exchangeRate.manage` | `POST /api/v1/exchange-rates` |
| `shared.exchangeRate.read` | `GET /api/v1/exchange-rates` |
| `shared.geo.read` | `GET /api/v1/cities`<br>`GET /api/v1/countries` |
| `zyloLiquid.alert.acknowledge` | `POST /api/v1/zylo-liquid/alerts/{alert_id}/acknowledge` |
| `zyloLiquid.alert.manage` | `PATCH /api/v1/zylo-liquid/alerts/{alert_id}` |
| `zyloLiquid.alert.read` | `GET /api/v1/zylo-liquid/alerts`<br>`GET /api/v1/zylo-liquid/alerts/{alert_id}` |
| `zyloLiquid.carrier.manage` | `POST /api/v1/zylo-liquid/carriers`<br>`PATCH /api/v1/zylo-liquid/carriers/{carrier_id}` |
| `zyloLiquid.carrier.read` | `GET /api/v1/zylo-liquid/carriers` |
| `zyloLiquid.cash.read` | `GET /api/v1/zylo-liquid/cash/network-summary`<br>`GET /api/v1/zylo-liquid/cash/stations/{station_id}`<br>`GET /api/v1/zylo-liquid/cash/tanks/{tank_id}` |
| `zyloLiquid.cashCollection.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/closing-cash` |
| `zyloLiquid.cashCollection.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/closing-cash` |
| `zyloLiquid.cashSummary.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/cash-adjustments` |
| `zyloLiquid.cashSummary.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/cash-summary` |
| `zyloLiquid.commercialAccount.manage` | `POST /api/v1/zylo-liquid/authorizations`<br>`POST /api/v1/zylo-liquid/commercial-accounts`<br>`PATCH /api/v1/zylo-liquid/commercial-accounts/{account_id}`<br>`POST /api/v1/zylo-liquid/drivers`<br>`POST /api/v1/zylo-liquid/vehicles` |
| `zyloLiquid.commercialAccount.read` | `GET /api/v1/zylo-liquid/commercial-accounts` |
| `zyloLiquid.declaration.lock` | `POST /api/v1/zylo-liquid/delivery-declarations/{declaration_id}/lock`<br>`POST /api/v1/zylo-liquid/incident-declarations/{declaration_id}/lock`<br>`POST /api/v1/zylo-liquid/leak-test-declarations/{declaration_id}/lock`<br>`POST /api/v1/zylo-liquid/manual-gauging-declarations/{declaration_id}/lock`<br>`POST /api/v1/zylo-liquid/quality-check-declarations/{declaration_id}/lock`<br>`POST /api/v1/zylo-liquid/shift-cash-declarations/{declaration_id}/lock` |
| `zyloLiquid.delivery.read` | `GET /api/v1/zylo-liquid/deliveries`<br>`GET /api/v1/zylo-liquid/deliveries-in-progress`<br>`GET /api/v1/zylo-liquid/deliveries/{delivery_id}` |
| `zyloLiquid.deliveryDeclaration.create` | `POST /api/v1/zylo-liquid/delivery-declarations`<br>`POST /api/v1/zylo-liquid/delivery-declarations/correct-lines`<br>`PATCH /api/v1/zylo-liquid/delivery-declarations/{declaration_id}` |
| `zyloLiquid.deliveryDeclaration.read` | `GET /api/v1/zylo-liquid/delivery-declarations` |
| `zyloLiquid.document.create` | `POST /api/v1/zylo-liquid/document-links`<br>`POST /api/v1/zylo-liquid/documents` |
| `zyloLiquid.document.delete` | `DELETE /api/v1/zylo-liquid/documents/{document_id}` |
| `zyloLiquid.document.read` | `GET /api/v1/zylo-liquid/documents/by-entity`<br>`GET /api/v1/zylo-liquid/documents/counts-by-entity`<br>`GET /api/v1/zylo-liquid/documents/{document_id}/download-url` |
| `zyloLiquid.equipment.manage` | `POST /api/v1/zylo-liquid/equipment`<br>`PATCH /api/v1/zylo-liquid/equipment/{equipment_id}` |
| `zyloLiquid.equipment.read` | `GET /api/v1/zylo-liquid/equipment` |
| `zyloLiquid.fuelProduct.manage` | `POST /api/v1/zylo-liquid/fuel-products`<br>`PATCH /api/v1/zylo-liquid/fuel-products/{fuel_product_id}` |
| `zyloLiquid.fuelProduct.read` | `GET /api/v1/zylo-liquid/fuel-products`<br>`GET /api/v1/zylo-liquid/fuel-products/{fuel_product_id}` |
| `zyloLiquid.gpsDevice.manage` | `POST /api/v1/zylo-liquid/gps-devices`<br>`PATCH /api/v1/zylo-liquid/gps-devices/{gps_device_id}`<br>`POST /api/v1/zylo-liquid/gps-devices/{gps_device_id}/unassign`<br>`GET /api/v1/zylo-liquid/gps-ingest-credential`<br>`POST /api/v1/zylo-liquid/gps-ingest-credential/regenerate`<br>`POST /api/v1/zylo-tanker/gps-devices`<br>`PATCH /api/v1/zylo-tanker/gps-devices/{gps_device_id}`<br>`POST /api/v1/zylo-tanker/gps-devices/{gps_device_id}/unassign`<br>`GET /api/v1/zylo-tanker/gps-ingest-credential`<br>`POST /api/v1/zylo-tanker/gps-ingest-credential/regenerate` |
| `zyloLiquid.gpsDevice.read` | `GET /api/v1/zylo-liquid/gps-devices`<br>`GET /api/v1/zylo-liquid/gps-devices/from-traccar`<br>`GET /api/v1/zylo-tanker/gps-devices`<br>`GET /api/v1/zylo-tanker/gps-devices/from-traccar` |
| `zyloLiquid.holykellAccount.manage` | `POST /api/v1/zylo-liquid/holykell-accounts` |
| `zyloLiquid.holykellAccount.read` | `GET /api/v1/zylo-liquid/holykell-accounts`<br>`GET /api/v1/zylo-liquid/holykell-accounts/{account_id}/sync-status` |
| `zyloLiquid.incidentDeclaration.create` | `POST /api/v1/zylo-liquid/incident-declarations`<br>`PATCH /api/v1/zylo-liquid/incident-declarations/{declaration_id}` |
| `zyloLiquid.incidentDeclaration.read` | `GET /api/v1/zylo-liquid/incident-declarations` |
| `zyloLiquid.intervention.assign` | `POST /api/v1/zylo-liquid/interventions/{intervention_id}/assign` |
| `zyloLiquid.intervention.close` | `POST /api/v1/zylo-liquid/interventions/{intervention_id}/close` |
| `zyloLiquid.intervention.create` | `POST /api/v1/zylo-liquid/interventions` |
| `zyloLiquid.intervention.read` | `GET /api/v1/zylo-liquid/interventions` |
| `zyloLiquid.leakEvent.read` | `GET /api/v1/zylo-liquid/leak-events`<br>`GET /api/v1/zylo-liquid/leak-events/{leak_event_id}` |
| `zyloLiquid.leakTestDeclaration.create` | `POST /api/v1/zylo-liquid/leak-test-declarations`<br>`PATCH /api/v1/zylo-liquid/leak-test-declarations/{declaration_id}` |
| `zyloLiquid.leakTestDeclaration.read` | `GET /api/v1/zylo-liquid/leak-test-declarations` |
| `zyloLiquid.manualGaugingDeclaration.create` | `POST /api/v1/zylo-liquid/manual-gauging-declarations`<br>`PATCH /api/v1/zylo-liquid/manual-gauging-declarations/{declaration_id}` |
| `zyloLiquid.manualGaugingDeclaration.read` | `GET /api/v1/zylo-liquid/manual-gauging-declarations` |
| `zyloLiquid.payment.create` | `POST /api/v1/zylo-liquid/payments` |
| `zyloLiquid.payment.read` | `GET /api/v1/zylo-liquid/payments` |
| `zyloLiquid.priceHistory.create` | `POST /api/v1/zylo-liquid/prices`<br>`PATCH /api/v1/zylo-liquid/prices/{price_id}` |
| `zyloLiquid.priceHistory.read` | `GET /api/v1/zylo-liquid/prices`<br>`GET /api/v1/zylo-liquid/prices/{price_id}` |
| `zyloLiquid.pricingPolicy.manage` | `PATCH /api/v1/zylo-liquid/station-product-pricing-policy` |
| `zyloLiquid.pricingPolicy.read` | `GET /api/v1/zylo-liquid/station-product-pricing-policy` |
| `zyloLiquid.productSale.cancel` | `POST /api/v1/zylo-liquid/product-sales/{transaction_id}/cancel` |
| `zyloLiquid.productSale.create` | `POST /api/v1/zylo-liquid/product-sales` |
| `zyloLiquid.productSale.read` | `GET /api/v1/zylo-liquid/product-sales` |
| `zyloLiquid.pump.manage` | `POST /api/v1/zylo-liquid/pumps`<br>`POST /api/v1/zylo-liquid/pumps/bulk`<br>`PATCH /api/v1/zylo-liquid/pumps/{pump_id}` |
| `zyloLiquid.pump.read` | `GET /api/v1/zylo-liquid/pumps`<br>`GET /api/v1/zylo-liquid/pumps/{pump_id}` |
| `zyloLiquid.pumpAssignment.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/assignments`<br>`POST /api/v1/zylo-liquid/shift-reports/{report_id}/assignments/reset-to-planning` |
| `zyloLiquid.pumpAssignment.read` | `GET /api/v1/zylo-liquid/my-shift-assignment`<br>`GET /api/v1/zylo-liquid/shift-reports/{report_id}/assignments` |
| `zyloLiquid.pumpClosing.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/closing-indexes` |
| `zyloLiquid.pumpClosing.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/closing-indexes` |
| `zyloLiquid.purchaseOrder.manage` | `POST /api/v1/zylo-liquid/purchase-orders`<br>`POST /api/v1/zylo-liquid/purchase-orders/{purchase_order_id}/generate-document` |
| `zyloLiquid.purchaseOrder.read` | `GET /api/v1/zylo-liquid/purchase-orders`<br>`GET /api/v1/zylo-liquid/purchase-orders/{purchase_order_id}`<br>`GET /api/v1/zylo-liquid/purchase-orders/{purchase_order_id}/trucks` |
| `zyloLiquid.qualityCheckDeclaration.create` | `POST /api/v1/zylo-liquid/quality-check-declarations`<br>`PATCH /api/v1/zylo-liquid/quality-check-declarations/{declaration_id}` |
| `zyloLiquid.qualityCheckDeclaration.read` | `GET /api/v1/zylo-liquid/quality-check-declarations` |
| `zyloLiquid.receivable.read` | `GET /api/v1/zylo-liquid/receivables` |
| `zyloLiquid.reconciliation.read` | `POST /api/v1/zylo-liquid/delivery-declaration-lines/{line_id}/reconcile-manual`<br>`GET /api/v1/zylo-liquid/delivery-declaration-lines/{line_id}/reconciliation-candidates`<br>`POST /api/v1/zylo-liquid/delivery-declarations/{declaration_id}/reconcile`<br>`POST /api/v1/zylo-liquid/manual-gauging-declarations/{declaration_id}/reconcile`<br>`POST /api/v1/zylo-liquid/quality-check-declarations/{declaration_id}/reconcile`<br>`GET /api/v1/zylo-liquid/reconciliation-records`<br>`POST /api/v1/zylo-liquid/tanks/{tank_id}/reconcile-stock` |
| `zyloLiquid.reconciliationSettings.manage` | `GET /api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings`<br>`PUT /api/v1/zylo-liquid/stations/{station_id}/reconciliation-settings` |
| `zyloLiquid.regulatoryDeclaration.read` | `GET /api/v1/zylo-liquid/regulatory-declarations` |
| `zyloLiquid.regulatoryDocument.create` | `POST /api/v1/zylo-liquid/regulatory-declarations`<br>`POST /api/v1/zylo-liquid/regulatory-documents` |
| `zyloLiquid.regulatoryDocument.manage` | `PATCH /api/v1/zylo-liquid/regulatory-documents/{document_id}`<br>`POST /api/v1/zylo-liquid/regulatory-documents/{document_id}/renew` |
| `zyloLiquid.regulatoryDocument.read` | `GET /api/v1/zylo-liquid/regulatory-documents` |
| `zyloLiquid.reportSections.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/report-sections` |
| `zyloLiquid.reportSections.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/report-sections` |
| `zyloLiquid.sale.create` | `POST /api/v1/zylo-liquid/sales`<br>`POST /api/v1/zylo-liquid/sales/bulk-import` |
| `zyloLiquid.sale.read` | `GET /api/v1/zylo-liquid/sales` |
| `zyloLiquid.securityEquipment.manage` | `POST /api/v1/zylo-liquid/security-equipment`<br>`PATCH /api/v1/zylo-liquid/security-equipment/{security_equipment_id}` |
| `zyloLiquid.securityEquipment.read` | `GET /api/v1/zylo-liquid/security-equipment` |
| `zyloLiquid.sellableProduct.manage` | `PATCH /api/v1/zylo-liquid/sellable-product-prices/{price_id}`<br>`POST /api/v1/zylo-liquid/sellable-products`<br>`POST /api/v1/zylo-liquid/sellable-products/bulk-import`<br>`PATCH /api/v1/zylo-liquid/sellable-products/{product_id}`<br>`POST /api/v1/zylo-liquid/sellable-products/{product_id}/prices` |
| `zyloLiquid.sellableProduct.read` | `GET /api/v1/zylo-liquid/sellable-products`<br>`GET /api/v1/zylo-liquid/sellable-products/{product_id}/prices` |
| `zyloLiquid.shiftAttendance.manage` | `PUT /api/v1/zylo-liquid/shift-attendance/bulk` |
| `zyloLiquid.shiftAttendance.read` | `GET /api/v1/zylo-liquid/shift-attendance`<br>`GET /api/v1/zylo-liquid/shift-attendance/summary` |
| `zyloLiquid.shiftCashDeclaration.create` | `POST /api/v1/zylo-liquid/shift-cash-declarations`<br>`PATCH /api/v1/zylo-liquid/shift-cash-declarations/{declaration_id}` |
| `zyloLiquid.shiftCashDeclaration.read` | `GET /api/v1/zylo-liquid/shift-cash-declarations` |
| `zyloLiquid.shiftDefinition.manage` | `POST /api/v1/zylo-liquid/shift-definitions/bulk` |
| `zyloLiquid.shiftDefinition.read` | `GET /api/v1/zylo-liquid/shift-definitions` |
| `zyloLiquid.shiftHandover.manage` | `PUT /api/v1/zylo-liquid/shift-handover/bulk`<br>`POST /api/v1/zylo-liquid/shift-handover/items/{item_id}/close`<br>`POST /api/v1/zylo-liquid/shift-handover/{handover_id}/receive` |
| `zyloLiquid.shiftHandover.read` | `GET /api/v1/zylo-liquid/shift-handover/context`<br>`GET /api/v1/zylo-liquid/shift-handover/summary` |
| `zyloLiquid.shiftPlanning.manage` | `PUT /api/v1/zylo-liquid/shift-planning/bulk` |
| `zyloLiquid.shiftPlanning.read` | `GET /api/v1/zylo-liquid/shift-planning` |
| `zyloLiquid.shiftReplacement.manage` | `POST /api/v1/zylo-liquid/shift-reports/{report_id}/movements`<br>`POST /api/v1/zylo-liquid/shift-reports/{report_id}/movements/{movement_id}/cancel` |
| `zyloLiquid.shiftReplacement.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/movements` |
| `zyloLiquid.shiftReport.manage` | `POST /api/v1/zylo-liquid/shift-opening`<br>`POST /api/v1/zylo-liquid/shift-reports/{report_id}/pump-lines`<br>`PATCH /api/v1/zylo-liquid/shift-reports/{report_id}/pump-lines/{line_id}/opening` |
| `zyloLiquid.shiftReport.read` | `GET /api/v1/zylo-liquid/shift-opening/context`<br>`GET /api/v1/zylo-liquid/shift-reports/current`<br>`GET /api/v1/zylo-liquid/shift-reports/{report_id}` |
| `zyloLiquid.station.manage` | `POST /api/v1/zylo-liquid/stations`<br>`PATCH /api/v1/zylo-liquid/stations/{station_id}`<br>`POST /api/v1/zylo-liquid/stations/{station_id}/deactivate`<br>`POST /api/v1/zylo-liquid/stations/{station_id}/reactivate` |
| `zyloLiquid.station.read` | `GET /api/v1/zylo-liquid/network/snapshot`<br>`GET /api/v1/zylo-liquid/network/summary`<br>`GET /api/v1/zylo-liquid/stations`<br>`GET /api/v1/zylo-liquid/stations/{station_id}`<br>`GET /api/v1/zylo-liquid/stations/{station_id}/current-state` |
| `zyloLiquid.stationFinancial.manage` | `PATCH /api/v1/zylo-liquid/stations/{station_id}/financial` |
| `zyloLiquid.stationFinancial.read` | `GET /api/v1/zylo-liquid/stations/{station_id}/financial` |
| `zyloLiquid.stationFuelProduct.manage` | `POST /api/v1/zylo-liquid/station-fuel-products`<br>`PATCH /api/v1/zylo-liquid/station-fuel-products/{association_id}`<br>`PATCH /api/v1/zylo-liquid/station-fuel-products/{association_id}/thresholds` |
| `zyloLiquid.stationFuelProduct.read` | `GET /api/v1/zylo-liquid/station-fuel-products`<br>`GET /api/v1/zylo-liquid/stations/{station_id}/fuel-products-overview` |
| `zyloLiquid.stationService.manage` | `POST /api/v1/zylo-liquid/station-services`<br>`PATCH /api/v1/zylo-liquid/station-services/{service_id}` |
| `zyloLiquid.stationService.read` | `GET /api/v1/zylo-liquid/station-services` |
| `zyloLiquid.stationStaff.manage` | `POST /api/v1/zylo-liquid/station-staff`<br>`POST /api/v1/zylo-liquid/station-staff/bulk`<br>`PATCH /api/v1/zylo-liquid/station-staff/{user_id}`<br>`POST /api/v1/zylo-liquid/station-staff/{user_id}/deactivate`<br>`POST /api/v1/zylo-liquid/station-staff/{user_id}/reactivate`<br>`POST /api/v1/zylo-liquid/station-staff/{user_id}/reset-password`<br>`PUT /api/v1/zylo-liquid/station-staff/{user_id}/role` |
| `zyloLiquid.stationStaff.read` | `GET /api/v1/zylo-liquid/station-staff` |
| `zyloLiquid.stationSupplier.manage` | `POST /api/v1/zylo-liquid/station-suppliers`<br>`PATCH /api/v1/zylo-liquid/station-suppliers/{station_supplier_id}` |
| `zyloLiquid.stationSupplier.read` | `GET /api/v1/zylo-liquid/station-suppliers` |
| `zyloLiquid.supplier.manage` | `POST /api/v1/zylo-liquid/suppliers`<br>`PATCH /api/v1/zylo-liquid/suppliers/{supplier_id}` |
| `zyloLiquid.supplier.read` | `GET /api/v1/zylo-liquid/suppliers` |
| `zyloLiquid.tank.manage` | `POST /api/v1/zylo-liquid/tanks`<br>`PATCH /api/v1/zylo-liquid/tanks/{tank_id}` |
| `zyloLiquid.tank.read` | `GET /api/v1/zylo-liquid/tanks`<br>`GET /api/v1/zylo-liquid/tanks/{tank_id}`<br>`GET /api/v1/zylo-liquid/tanks/{tank_id}/current-state`<br>`GET /api/v1/zylo-liquid/tanks/{tank_id}/measurements` |
| `zyloLiquid.tankCalibration.manage` | `PUT /api/v1/zylo-liquid/tanks/{tank_id}/calibration-points` |
| `zyloLiquid.tankCalibration.read` | `GET /api/v1/zylo-liquid/tanks/{tank_id}/calibration-points` |
| `zyloLiquid.tankGauging.manage` | `PUT /api/v1/zylo-liquid/shift-reports/{report_id}/closing-gauging` |
| `zyloLiquid.tankGauging.read` | `GET /api/v1/zylo-liquid/shift-reports/{report_id}/closing-gauging` |
| `zyloLiquid.tankSensorMapping.manage` | `POST /api/v1/zylo-liquid/tank-sensor-mappings`<br>`POST /api/v1/zylo-liquid/tank-sensor-mappings/{mapping_id}/close` |
| `zyloLiquid.tankSensorMapping.read` | `GET /api/v1/zylo-liquid/tank-sensor-mappings` |
| `zyloLiquid.technician.manage` | `POST /api/v1/zylo-liquid/technicians` |
| `zyloLiquid.technician.read` | `GET /api/v1/zylo-liquid/technicians` |
| `zyloLiquid.traccarConnection.manage` | `GET /api/v1/zylo-liquid/traccar-connection`<br>`POST /api/v1/zylo-liquid/traccar-connection`<br>`GET /api/v1/zylo-tanker/traccar-connection`<br>`POST /api/v1/zylo-tanker/traccar-connection` |
| `zyloLiquid.trackingLocation.manage` | `POST /api/v1/zylo-liquid/tracking-locations`<br>`DELETE /api/v1/zylo-liquid/tracking-locations/{location_id}`<br>`PATCH /api/v1/zylo-liquid/tracking-locations/{location_id}`<br>`POST /api/v1/zylo-liquid/truck-stop-reconciliations/{reconciliation_id}/resolve`<br>`POST /api/v1/zylo-liquid/vessel-stop-reconciliations/{reconciliation_id}/resolve`<br>`POST /api/v1/zylo-tanker/tracking-locations`<br>`DELETE /api/v1/zylo-tanker/tracking-locations/{location_id}`<br>`PATCH /api/v1/zylo-tanker/tracking-locations/{location_id}`<br>`POST /api/v1/zylo-tanker/truck-stop-reconciliations/{reconciliation_id}/resolve`<br>`POST /api/v1/zylo-tanker/vessel-stop-reconciliations/{reconciliation_id}/resolve` |
| `zyloLiquid.trackingLocation.read` | `GET /api/v1/zylo-liquid/tracking-locations`<br>`GET /api/v1/zylo-liquid/truck-stop-reconciliations`<br>`GET /api/v1/zylo-liquid/vessel-stop-reconciliations`<br>`GET /api/v1/zylo-tanker/tracking-locations`<br>`GET /api/v1/zylo-tanker/truck-stop-reconciliations`<br>`GET /api/v1/zylo-tanker/vessel-stop-reconciliations` |
| `zyloLiquid.trackingSettings.manage` | `PATCH /api/v1/zylo-liquid/tracking-settings`<br>`PATCH /api/v1/zylo-tanker/tracking-settings` |
| `zyloLiquid.truck.manage` | `POST /api/v1/zylo-liquid/trucks`<br>`PATCH /api/v1/zylo-liquid/trucks/{truck_id}` |
| `zyloLiquid.truck.read` | `GET /api/v1/zylo-liquid/tracking-settings`<br>`DELETE /api/v1/zylo-liquid/truck-stop-comments/{comment_id}`<br>`PATCH /api/v1/zylo-liquid/truck-stop-comments/{comment_id}`<br>`GET /api/v1/zylo-liquid/truck-stops/{stop_id}/comments`<br>`POST /api/v1/zylo-liquid/truck-stops/{stop_id}/comments`<br>`GET /api/v1/zylo-liquid/trucks`<br>`GET /api/v1/zylo-liquid/trucks/current-positions`<br>`GET /api/v1/zylo-liquid/trucks/live-positions`<br>`GET /api/v1/zylo-liquid/trucks/{truck_id}/orders`<br>`GET /api/v1/zylo-liquid/trucks/{truck_id}/positions`<br>`GET /api/v1/zylo-liquid/trucks/{truck_id}/stops`<br>`GET /api/v1/zylo-tanker/tracking-settings`<br>`DELETE /api/v1/zylo-tanker/truck-stop-comments/{comment_id}`<br>`PATCH /api/v1/zylo-tanker/truck-stop-comments/{comment_id}`<br>`GET /api/v1/zylo-tanker/truck-stops/{stop_id}/comments`<br>`POST /api/v1/zylo-tanker/truck-stops/{stop_id}/comments`<br>`GET /api/v1/zylo-tanker/trucks/current-positions`<br>`GET /api/v1/zylo-tanker/trucks/live-positions`<br>`GET /api/v1/zylo-tanker/trucks/{truck_id}/positions`<br>`GET /api/v1/zylo-tanker/trucks/{truck_id}/stops` |
| `zyloLiquid.truckOrderAssignment.manage` | `POST /api/v1/zylo-liquid/purchase-orders/{purchase_order_id}/trucks`<br>`DELETE /api/v1/zylo-liquid/purchase-orders/{purchase_order_id}/trucks/{truck_id}` |
| `zyloTanker.vessel.manage` | `POST /api/v1/zylo-tanker/vessels`<br>`DELETE /api/v1/zylo-tanker/vessels/{vessel_id}/destination`<br>`PUT /api/v1/zylo-tanker/vessels/{vessel_id}/destination` |
| `zyloTanker.vessel.read` | `GET /api/v1/zylo-liquid/tracking-settings`<br>`DELETE /api/v1/zylo-liquid/vessel-stop-comments/{comment_id}`<br>`PATCH /api/v1/zylo-liquid/vessel-stop-comments/{comment_id}`<br>`GET /api/v1/zylo-liquid/vessel-stops/{stop_id}/comments`<br>`POST /api/v1/zylo-liquid/vessel-stops/{stop_id}/comments`<br>`GET /api/v1/zylo-liquid/vessels/current-positions`<br>`GET /api/v1/zylo-liquid/vessels/live-positions`<br>`GET /api/v1/zylo-liquid/vessels/{vessel_id}/positions`<br>`GET /api/v1/zylo-liquid/vessels/{vessel_id}/stops`<br>`GET /api/v1/zylo-tanker/tracking-settings`<br>`DELETE /api/v1/zylo-tanker/vessel-stop-comments/{comment_id}`<br>`PATCH /api/v1/zylo-tanker/vessel-stop-comments/{comment_id}`<br>`GET /api/v1/zylo-tanker/vessel-stops/{stop_id}/comments`<br>`POST /api/v1/zylo-tanker/vessel-stops/{stop_id}/comments`<br>`GET /api/v1/zylo-tanker/vessels`<br>`GET /api/v1/zylo-tanker/vessels/current-positions`<br>`GET /api/v1/zylo-tanker/vessels/live-positions`<br>`GET /api/v1/zylo-tanker/vessels/{vessel_id}`<br>`GET /api/v1/zylo-tanker/vessels/{vessel_id}/positions`<br>`GET /api/v1/zylo-tanker/vessels/{vessel_id}/stops` |

## Routes sans permission ni appartenance

- `GET /` — Racine d'accueil, aucune donnée. 2026-10-09.
- `GET /api/v1/account/profile` — Profil de l'utilisateur de la session uniquement (get_current_user, aucun identifiant lu dans la requête). Portée utilisateur. BE-020.
- `GET /api/v1/admin/audit-events` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/cases` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/cases/{case_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/cases/{case_id}/assign` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/cases/{case_id}/close` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/cases/{case_id}/payment-diagnostics` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/cases/{case_id}/subscription-diagnostics` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/commands/{command_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/approve` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/confirm` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/commands/{command_id}/notifications` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/preview` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/reconcile` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/reject` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/commands/{command_id}/verify` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/invoices/{invoice_id}/finance-commands` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/modules` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/modules/{module_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/modules/{module_id}/upgrade-plans` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/modules/{module_id}/versions` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/modules/{module_id}/versions/{version_id}/compatibility-evaluations` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/modules/{module_id}/versions/{version_id}/publish` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/organizations/{organization_id}/entitlements/commands` — NON CLASSÉE — revoir la garde avant livraison
- `PATCH /api/v1/admin/organizations/{organization_id}/entitlements/{entitlement_id}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/organizations/{organization_id}/exceptional-access` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/reconciliations` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/reconciliations/{reconciliation_id}/resolve` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/admin/role-assignments` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/role-assignments` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/admin/role-assignments/{assignment_id}/revoke` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/auth/activate` — Activation d'un compte par jeton à usage unique reçu hors API (T-021) : jeton vérifié et consommé dans le service, limitée par T-012. 2026-10-09.
- `POST /api/v1/auth/change-password` — Changement de mot de passe de l'utilisateur connecté (portée utilisateur uniquement). 2026-10-09.
- `POST /api/v1/auth/login` — Connexion : public par nature, limitée par T-012. 2026-10-09.
- `POST /api/v1/auth/logout` — Révocation par jeton de session, sans organisation. 2026-10-09.
- `GET /api/v1/auth/me` — Profil de l'utilisateur connecté (portée utilisateur uniquement). 2026-10-09.
- `POST /api/v1/auth/password-reset/confirm` — Confirmation par jeton à usage unique reçu hors API, vérifié et consommé dans le service ; limitée par T-012.
- `POST /api/v1/auth/password-reset/request` — Demande de réinitialisation par adresse, publique par nature ; réponse uniforme, limitée par T-012.
- `POST /api/v1/auth/refresh` — Rafraîchissement par jeton de session, sans organisation. 2026-10-09.
- `POST /api/v1/auth/register` — Endpoint masqué par défaut; AUTH_PUBLIC_REGISTRATION_ENABLED=true n'est admis que si ENVIRONMENT=development ou test (le validateur Settings refuse production/staging). Libre-service sans décision produit réservé aux tests et au développement local. 2026-11-02.
- `GET /api/v1/billing/payment-provider` — Métadonnées statiques du provider de test (configured=false, checkoutAvailable=false), sans donnée tenant ni secret. 2026-11-02.
- `GET /api/v1/billing/plans` — Catalogue de plans, lecture seule (création par API retirée par T-019, option A de T-050). Passera authentifié si IAM-020 est confirmée. 2026-10-09.
- `GET /api/v1/catalog/modules` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/catalog/modules/{slug}` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/export/docx` — Conversion d'un tableau fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.
- `POST /api/v1/export/xlsx` — Conversion d'un tableau fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.
- `GET /api/v1/health` — Sonde de santé. 2026-10-09.
- `GET /api/v1/health/error-demo` — Démonstration du format d'erreur, sans donnée. A retirer en production. 2026-10-09.
- `GET /api/v1/health/ready` — Sonde de disponibilité : état de la base seulement, sans donnée ni secret (BE-032). 2026-11-03.
- `POST /api/v1/import/xlsx` — Lecture d'un fichier fourni par l'appelant, authentifiée (get_current_user), sans accès à la base. 2026-10-09.
- `POST /api/v1/internal/billing/entitlement-events` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/internal/ready` — Readiness réservée au réseau interne : 404 hors HEALTH_INTERNAL_NETWORKS (contrôle dans la route, sans session). BE-032.
- `GET /api/v1/modules` — Catalogue des modules (aucune donnée d'organisation). Passera authentifié si la décision catalogues-publics est confirmée (IAM-020). 2026-10-09.
- `GET /api/v1/notifications/vapid-public-key` — Clé publique VAPID (non secrète), lue avant tout abonnement, aucune donnée d'organisation. 2026-10-09 (T-004b lot 2).
- `GET /api/v1/organizations` — Liste des organisations de l'utilisateur connecté (portée utilisateur). 2026-10-09.
- `POST /api/v1/organizations` — Création d'organisation par tout utilisateur connecté. Quota ORG_CREATION_QUOTA à fixer par le client (T-019, décision en attente). 2026-10-09.
- `POST /api/v1/organizations/{organization_id}/modules/{module_id}/reactivations` — NON CLASSÉE — revoir la garde avant livraison
- `POST /api/v1/organizations/{organization_id}/modules/{module_id}/suspensions` — NON CLASSÉE — revoir la garde avant livraison
- `GET /api/v1/storage/local/{storage_reference}` — Téléchargement par URL signée (signature vérifiée dans le service). 2026-10-09.
- `PATCH /api/v1/users/{user_id}` — Photo de profil : soi-même, ou owner d'une organisation dont la cible est membre. Contrôle dans le service (update_user_profile). 2026-10-09.

## Routes protégées par allowlist opérateur

- `GET /api/v1/admin/health` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/ops/metrics` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/organizations` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/organizations/{organization_id}` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/payment-events/{event_id}` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/requests/{request_id}` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/sensitive-action-classes` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).
- `GET /api/v1/admin/status` — `require_operator` (session utilisateur + allowlist serveur `OPERATOR_READ_USER_IDS`).

## Routes avec contrôle manuel documenté

- `POST /api/v1/billing/webhooks/flutterwave` — Signature Flutterwave verif-hash comparée en temps constant avant lecture du payload ou accès aux événements; secret absent -> 503, signature invalide -> 401. 2026-11-02.
- `POST /api/v1/integrations/webhooks/{connecteur_id}` — Signature HMAC du connecteur (en-tête X-Zylo-Signature) vérifiée dans webhooks.py avant toute écriture ; secret absent -> 503 ou 404, signature invalide -> 401. BE-163.
- `POST /api/v1/zylo-liquid/gps/ingest` — Secret d'ingestion propre à l'organisation dans X-GPS-Ingest-Secret, vérifié en service avant traitement; absence/invalide -> 401. 2026-10-09.
- `POST /api/v1/zylo-tanker/gps/ingest` — Secret d'ingestion propre à l'organisation dans X-GPS-Ingest-Secret, vérifié en service avant traitement; absence/invalide -> 401. 2026-10-09.
