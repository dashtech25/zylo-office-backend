"""Rendu canonique de l'inventaire des tables ORM du socle Zylo Office.

Le périmètre suit les modèles enregistrés par l'application et exclut les deux
modules métier. Les portées sont des indications documentaires fondées sur les
colonnes, les clés étrangères et les décisions déjà vérifiées; elles ne prouvent
pas à elles seules l'isolation des requêtes.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Table


_PAQUETS_METIER_EXCLUS = (
    "app.modules.zylo_liquid.",
    "app.modules.zylo_tanker.",
)

# Modules ORM du socle que `app.main` n'importe pas (directement ni via ses
# routeurs). Leurs tables sont pourtant des tables du socle : sans cette liste,
# elles seraient absentes de l'inventaire et de Base.metadata au démarrage.
# Le générateur et le test importent ces modules après `app.main` pour fixer
# le périmètre de façon reproductible. Recommandation (QE-BE039-01) : les
# garder ici plutôt que de modifier le montage de l'application dans ce lot.
MODULES_ORM_SOCLE_HORS_APP = (
    "app.core.ratelimit",
    "app.operator.alertes_models",
    "app.operator.capacite_models",
    "app.release.models",
    "app.securite.models",
)

_PORTÉES_EXPLICITES = {
    "acces_support": "organisation",
    "capacity_samples": "organisation attribuée (tenantId, simple référence sans clé étrangère)",
    "admin_command": "multi-portée (effectiveScope: platform ou tenant:<uuid>)",
    "admin_command_approval": "portée héritée de la commande parente (tenant ou plateforme)",
    "admin_command_preview": "portée héritée de la commande parente (tenant ou plateforme)",
    "admin_notification": "portée héritée de la commande parente (tenant ou plateforme)",
    "admin_role_assignment": "multi-portée (scope: platform ou tenant:<uuid>)",
    "audit_event": "multi-portée explicite (organisation et plateforme pour les lectures opérateur; écart entre commentaire et writer à suivre)",
    "approbation_parametre": "portée déclarée (plateforme, organisation, module ou utilisateur; scopeKind contraint)",
    "setting_definition": "portée déclarée (plateforme, organisation, module ou utilisateur; scopeKind contraint)",
    "setting_value": "portée de la valeur (plateforme, organisation, module ou utilisateur; scopeKind contraint)",
    "settings_registry": "portée déclarée (platform, tenant, membership ou workspace; scopeKind contraint)",
    "settings_history": "portée de l'historique (platform, tenant, membership ou workspace; scopeKind contraint)",
    "connecteur": "multi-portée (portee globale ou organisation, contrainte du modèle)",
    "consommation_evenement": "portée héritée de l'événement outbox consommé",
    "credit_note": "organisation bénéficiaire (facture parente)",
    "checkout": "organisation bénéficiaire (devis parent)",
    "close_operation": "organisation bénéficiaire (abonnement parent)",
    "dead_letters": "organisation (tenantId vers organization.id)",
    "event_inbox": "organisation (tenantId, quarantaine d'événements tenant)",
    "consent_record": "multi-portée (scope de consentement: payeur, tenant ou bénéficiaire)",
    "entitlement_source_events": "organisation (organizationId journalisé)",
    "entitlement_sync": "organisation bénéficiaire (abonnement parent)",
    "escalation": "portée héritée du cas d'intervention parent",
    "feature_flags": "organisation",
    "flag_changes": "organisation",
    "incidents": "multi-portée (plateforme ou organisation)",
    "incident_events": "portée héritée de l'incident parent",
    "intervention_case": "multi-portée (plateforme ou organisation)",
    "invoice": "organisation bénéficiaire (abonnement parent)",
    "idempotencyKeys": "organisation et acteur (couple de portée documenté)",
    "idempotency_record": "acteur et clé de portée (principal, route et clé d'idempotence)",
    "module_permissions": "scope contraint (organization, tenant ou platform)",
    "organization": "organisation racine du tenant",
    "organization_user": "organisation (appartenance au tenant)",
    "organizationInvitation": "organisation (invitation au tenant)",
    "userInvitation": "organisation (invitation au membre du tenant)",
    "invitation": "organisation (organizationId du modèle)",
    "notification": "utilisateur destinataire; audience tenant résolue mais tenant non persisté",
    "livraison": "utilisateur destinataire via notification parente; tenant non persisté",
    "notification_delivery": "utilisateur destinataire via notification parente; tenant non persisté",
    "paymentWebhookEvent": "globale fournisseur (clé eventId, sans portée tenant)",
    "module_state_transitions": "multi-portée (organisation ou sujet de plateforme)",
    "operations": "organisation (tenantId vers organization.id)",
    "operator_access_request": "organisation (tenantId vers organization.id)",
    "outbox_evenement": "multi-portée (plateforme ou organisation)",
    "paymentAttempt": "organisation bénéficiaire (facture ou checkout parent)",
    "payment_diagnostic": "portée héritée du cas d'intervention parent",
    "plan_change": "organisation bénéficiaire (abonnement parent)",
    "reconciliation_difference": "organisation bénéficiaire (run de rapprochement parent)",
    "refund": "organisation bénéficiaire (tentative de paiement parente)",
    "dispute": "organisation bénéficiaire (tentative de paiement parente)",
    "renewal_run": "organisation bénéficiaire (abonnement parent)",
    "quote": "organisation bénéficiaire (beneficiaryTenantId vers organization.id)",
    "rolePermission": "organisation (portée du rôle parent)",
    "secret_integration": "portée héritée du connecteur parent (globale ou organisation)",
    "secret_registry": "globale par environnement (registre de secrets)",
    "subscription_diagnostic": "portée héritée du cas d'intervention parent",
    "subscription": "organisation bénéficiaire (beneficiaryTenantId; organizationId repris par migration)",
    "tentativeIntegration": "organisation (organizationId journalisé)",
    "subscription_entitlement": "multi-portée (offre globale ou organisation)",
    "tenant": "organisation (un tenant par organisation)",
    "zyloLiquidAlert": "organisation (portée résolue par jointure station/truck/vessel; le modèle ne garantit pas un owner unique)",
    "webhook_recu": "multi-portée (organisation du connecteur ou portée globale)",
    "organization": "organisation (racine du tenant)",
    "zyloLiquidDocumentLink": "organisation héritée du document parent",
    "zyloLiquidGpsDeviceAssignment": "organisation héritée du GPS affecté",
    "zyloLiquidTruckPositionPing": "organisation héritée du GPS source",
    "zyloLiquidTruckStopComment": "organisation héritée de l'événement d'arrêt parent",
    "zyloLiquidTruckStopEvent": "organisation de l'actif suivi (truck XOR vessel, vérifiée par le service)",
    "zyloLiquidTruckStopReconciliation": "organisation héritée de l'événement d'arrêt parent",
}

_PORTÉES_CATALOGUE_GLOBAL = {
    "capability": "globale (catalogue de capacités)",
    "categorie_notification": "globale (catalogue)",
    "city": "globale (référentiel géographique)",
    "country": "globale (référentiel géographique)",
    "currency": "globale (référentiel de devises)",
    "exchangeRate": "globale (référentiel de taux)",
    "module": "globale (catalogue de modules)",
    "module_compatibility_evaluations": "globale (compatibilité de versions)",
    "module_upgrade_plans": "globale (catalogue de modules)",
    "module_version": "globale (catalogue de versions)",
    "permission": "globale (catalogue de permissions)",
    "plan": "globale (catalogue d'offres)",
    "planVersion": "globale (catalogue de versions d'offres)",
    "region": "globale (référentiel géographique)",
    "regle_notification": "globale (catalogue de règles)",
    "schema_evenement": "globale (registre de schémas)",
}

_PORTÉES_UTILISATEUR = {
    "loginAttempt": "globale (clé pseudonymisée de limitation d'authentification)",
    "password_reset_token": "utilisateur global",
    "preference_notification": "utilisateur dans l'organisation active",
    "refreshToken": "utilisateur global",
    "user": "utilisateur global",
}

# Routes et tests sont associés séparément quand l'usage du modèle a été vérifié
# dans son handler/service ou dans un test précis. Les tables absentes des cartes
# restent visibles et sont signalées comme à vérifier.
_ROUTES_VERIFIEES = {
    "acces_support": "POST /api/v1/organizations/{organization_id}/acces-support; GET /api/v1/organizations/{organization_id}/acces-support/courant",
    "role": "GET /api/v1/rbac/organizations/{organization_id}/roles",
    "rolePermission": "PUT /api/v1/rbac/organizations/{organization_id}/roles/{role_id}/permissions",
    "admin_command_approval": "POST /api/v1/admin/commands/{command_id}/approve; POST /api/v1/admin/commands/{command_id}/reject",
    "admin_command_preview": "POST /api/v1/admin/commands/{command_id}/preview; POST /api/v1/admin/commands/{command_id}/confirm",
    "admin_command": "GET/POST /api/v1/admin/commands; GET /api/v1/admin/commands/{command_id}; POST /api/v1/admin/commands/{command_id}/approve; POST /api/v1/admin/commands/{command_id}/reject; POST /api/v1/admin/commands/{command_id}/preview; POST /api/v1/admin/commands/{command_id}/confirm; POST /api/v1/admin/commands/{command_id}/reconcile; POST /api/v1/admin/commands/{command_id}/verify",
    "admin_notification": "GET /api/v1/admin/commands/{command_id}/notifications",
    "admin_role_assignment": "POST/GET /api/v1/admin/role-assignments; POST /api/v1/admin/role-assignments/{assignment_id}/revoke",
    "export_audit": "POST /api/v1/audit/exports; GET /api/v1/audit/exports/{job_id}; GET /api/v1/audit/exports/{job_id}/telechargement",
    "idempotencyKeys": "Aucun endpoint CRUD direct; table interne utilisée par run_idempotent sur les routes d'installation, mise à jour et suppression",
    "legal_holds": "Aucun endpoint CRUD direct; holds internes vérifiés lors de la sortie du tenant",
    "module": "POST /api/v1/admin/modules; GET /api/v1/admin/modules/{module_id}; GET /api/v1/catalog/modules; GET /api/v1/catalog/modules/{slug}; GET /api/v1/modules",
    "module_compatibility_evaluations": "POST /api/v1/admin/modules/{module_id}/versions/{version_id}/compatibility-evaluations",
    "module_reconciliations": "GET /api/v1/admin/reconciliations; POST /api/v1/admin/reconciliations/{reconciliation_id}/resolve",
    "module_state_transitions": "Aucun endpoint direct; journal écrit par les routes de cycle de vie des modules",
    "module_upgrade_plans": "POST /api/v1/admin/modules/{module_id}/upgrade-plans",
    "module_version": "POST /api/v1/admin/modules/{module_id}/versions; POST /api/v1/admin/modules/{module_id}/versions/{version_id}/publish; versions publiées visibles dans GET /api/v1/catalog/modules/{slug}",
    "module_permissions": "GET /api/v1/organizations/{organization_id}/modules/{module_id}/permissions",
    "operations": "GET /api/v1/operations/{operation_id}; création et transitions internes",
    "operator_access_request": "POST /api/v1/admin/access-requests; POST /api/v1/admin/access-requests/{request_id}/approve; DELETE /api/v1/admin/access-requests/{request_id}",
    "organizationModule": "GET /api/v1/organizations/current/modules; PUT /api/v1/organizations/current/modules/{module_id}/activation; GET /api/v1/modules/organizations/{organization_id}; POST /api/v1/modules/organizations/{organization_id}/activate; POST /api/v1/modules/organizations/{organization_id}/deactivate",
    "permission": "GET /api/v1/rbac/organizations/{organization_id}/permissions (catalogue global)",
    "planVersion": "Aucun CRUD direct; version active exposée par GET /api/v1/billing/plans",
    "tenant_exit_requests": "POST /api/v1/organizations/{organization_id}/exit; GET /api/v1/organizations/{organization_id}/exit/attestation",
    "userPermissionGrant": "POST/DELETE /api/v1/organizations/current/members/{user_id}/grants[/{grant_id}]; GET /api/v1/rbac/organizations/{organization_id}/users/{user_id}/grants; POST/DELETE /api/v1/rbac/organizations/{organization_id}/grants[/{grant_id}]",
    "userRole": "PUT /api/v1/organizations/current/members/{user_id}/roles; GET /api/v1/organizations/current/roles; POST/DELETE /api/v1/rbac/organizations/{organization_id}/user-roles[/{assignment_id}]",
    "approbation_parametre": "GET /api/v1/approbations/{demande_id}; POST /api/v1/approbations/{demande_id}/decisions",
    "audit_event": "GET /api/v1/admin/audit-events; GET /api/v1/audit/records",
    "plan": "GET /api/v1/billing/plans",
    "close_operation": "POST /api/v1/billing/subscriptions/{subscription_id}/close",
    "consent_record": "POST /api/v1/billing/consents",
    "data_export_request": "POST /api/v1/billing/data-exports",
    "dispute": "GET /api/v1/billing/disputes/{dispute_id}; ingestion webhook fournisseur de paiement",
    "entitlement_allocations": "POST /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations; DELETE /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations/{user_id}",
    "entitlement_source_events": "POST /api/v1/internal/billing/entitlement-events",
    "entitlement_sync": "POST /api/v1/internal/billing/entitlement-events",
    "subscription_entitlement": "POST /api/v1/internal/billing/entitlement-events; GET /api/v1/organizations/current/entitlements",
    "paymentWebhookEvent": "POST /api/v1/billing/provider-events; POST /api/v1/billing/webhooks/flutterwave (alias historique)",
    "plan_change": "POST /api/v1/billing/subscriptions/{subscription_id}/plan-change/preview; POST /api/v1/billing/subscriptions/{subscription_id}/plan-change",
    "reconciliation_run": "POST /api/v1/billing/reconciliations",
    "reconciliation_difference": "POST /api/v1/billing/reconciliations",
    "subscription": "POST /api/v1/billing/organizations/{organization_id}/subscriptions; GET /api/v1/billing/organizations/{organization_id}/subscription; GET /api/v1/billing/subscriptions/{subscription_id}; POST /api/v1/billing/subscriptions/{subscription_id}/cancel; POST /api/v1/billing/subscriptions/{subscription_id}/reactivate; POST /api/v1/billing/subscriptions/{subscription_id}/close",
    "billing_payer": "Aucun endpoint direct; payeur résolu via devis et checkout",
    "capability": "Aucun endpoint direct; capacités consultées par les services d'entitlement",
    "idempotency_record": "Aucun endpoint direct; table interne au mécanisme d'idempotence",
    "plan_version_snapshot": "Aucun endpoint direct; instantané consulté par les flux d'abonnement et devis",
    "price_rule": "Aucun endpoint direct; règles consultées par le résolveur de prix",
    "renewal_run": "Aucun endpoint direct; exécution par tâche de renouvellement",
    "billing_case": "POST /api/v1/billing/cases; POST /api/v1/billing/cases/{case_id}/resolve",
    "checkout": "POST /api/v1/billing/checkouts; GET /api/v1/billing/checkouts/{checkout_id}",
    "credit_note": "POST /api/v1/billing/invoices/{invoice_id}/credit-notes",
    "connecteur": "GET/POST /api/v1/connecteurs; routes de transition et configuration",
    "currency": "GET/POST/PATCH /api/v1/currencies",
    "dead_letters": "GET/POST /api/v1/internal/dead-letters",
    "exchangeRate": "GET/POST /api/v1/exchange-rates",
    "escalation": "POST /api/v1/admin/cases/{case_id}/escalations; POST /api/v1/admin/escalations/{escalation_id}/close",
    "export_jobs": "POST /api/v1/exports; GET /api/v1/exports/{id}; GET /api/v1/exports/{id}/download",
    "export_job": "POST /api/v1/organizations/{organization_id}/exports; GET /api/v1/organizations/{organization_id}/exports/{export}; GET /api/v1/organizations/{organization_id}/exports/{export}/download",
    "feature_flags": "GET /api/v1/internal/flags; PUT /api/v1/internal/flags/{flag_key}",
    "flag_changes": "GET /api/v1/internal/flags; PUT /api/v1/internal/flags/{flag_key} (journal écrit par le PUT)",
    "incidents": "GET /api/v1/admin/incidents; GET /api/v1/admin/incidents/{incident_id}",
    "incident_events": "GET /api/v1/admin/incidents/{incident_id} (chronologie incluse)",
    "invoice": "GET /api/v1/organizations/current/invoices; GET /api/v1/organizations/current/invoices/{invoice_id}; GET /api/v1/billing/invoices/{invoice_id}; POST /api/v1/billing/invoices/{invoice_id}/finalize; POST /api/v1/billing/invoices/{invoice_id}/credit-notes",
    "integration_links": "GET /api/v1/integrations/integrations; POST /api/v1/integrations/integrations/{provider}/connect; POST /api/v1/integrations/integrations/{lien_id}/disconnect",
    "intervention_case": "POST/GET /api/v1/admin/cases; POST /api/v1/admin/cases/{case_id}/assign; POST /api/v1/admin/cases/{case_id}/close",
    "lettreMorte": "GET /api/v1/integrations/lettres-mortes; POST /api/v1/integrations/lettres-mortes/{lettre_id}/reprises",
    "loginAttempt": "Aucune route CRUD directe; lecture, écriture et purge par le rate limit de POST /api/v1/auth/login, /register et /refresh",
    "module_installations": "POST /api/v1/organizations/{organization_id}/modules/{module_id}/installations; GET /api/v1/organizations/{organization_id}/modules/{module_id}/installations/{operation_id}",
    "notificationPushSubscription": "POST /api/v1/notifications/push-subscriptions; DELETE /api/v1/notifications/push-subscriptions/{subscription_id}",
    "notification_inbox_item": "GET /api/v1/notifications/inbox; GET/PATCH /api/v1/notifications/inbox/{item_id}",
    "notification": "GET /api/v1/notifications",
    "livraison": "GET /api/v1/notifications/{notification_id}/livraisons",
    "notification_delivery": "Aucun endpoint direct; résultat écrit par le service de livraison BE-238",
    "categorie_notification": "GET /api/v1/notifications/preferences; PUT /api/v1/notifications/preferences/{categorie_code}",
    "preference_notification": "GET /api/v1/notifications/preferences; PUT /api/v1/notifications/preferences/{categorie_code}",
    "regle_notification": "Aucun endpoint direct; règles lues par le moteur BE-169",
    "consommation_evenement": "Aucun endpoint direct; traitement par le dispatcher d'événements",
    "event_inbox": "Aucun endpoint direct; traitement interne de consommation d'événements",
    "organization": "GET /api/v1/organizations; GET /api/v1/organizations/current; POST /api/v1/organizations; PATCH /api/v1/organizations/{organization_id}",
    "organization_user": "GET /api/v1/organizations/current/members; appartenance créée par activation d'invitation (aucun CRUD direct)",
    "organizationInvitation": "POST/GET /api/v1/organizations/current/invitations",
    "userInvitation": "POST /api/v1/organizations/{organization_id}/users; POST /api/v1/organizations/{organization_id}/users/{user_id}/invitation; POST /api/v1/auth/activate",
    "user": "POST /api/v1/auth/register; GET /api/v1/auth/me; GET /api/v1/account/profile; PATCH /api/v1/users/{user_id}",
    "password_reset_token": "POST /api/v1/auth/password-reset/request; POST /api/v1/auth/password-reset/confirm",
    "setting_definition": "GET /api/v1/parametres/{scope_kind}/{scope_id}",
    "setting_value": "GET /api/v1/parametres/{scope_kind}/{scope_id}; PUT /api/v1/parametres/{scope_kind}/{scope_id}/{cle}; POST /api/v1/parametres/{scope_kind}/{scope_id}/{cle}/restaurations",
    "settings_registry": "Aucune route HTTP identifiée; registre interne des réglages",
    "settings_history": "Aucune route HTTP identifiée; historique interne des réglages",
    "secret_registry": "Aucune route HTTP identifiée; registre de métadonnées de secrets d'environnement",
    "schema_evenement": "GET /api/v1/admin/evenements/types",
    "secret_integration": "POST /api/v1/integrations/integrations/{provider}/connect (création interne; aucun endpoint secret dédié)",
    "tentativeIntegration": "Aucune route HTTP identifiée; journal interne des tentatives (BE-164)",
    "tenant": "Aucune route HTTP identifiée; modèle non utilisé par les handlers HTTP",
    "invitation": "Aucune route HTTP identifiée; aucune référence par les handlers",
    "webhook_recu": "POST /api/v1/integrations/webhooks/{connecteur_id}",
    "zyloLiquidAlert": "GET /api/v1/zylo-liquid/alerts; GET /api/v1/zylo-liquid/alerts/{alert_id}; POST /api/v1/zylo-liquid/alerts/{alert_id}/acknowledge; PATCH /api/v1/zylo-liquid/alerts/{alert_id}",
    "outbox_evenement": "Aucun endpoint direct; écriture et lecture internes par producteur/dispatcher",
    "payment_diagnostic": "POST /api/v1/admin/cases/{case_id}/payment-diagnostics; GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id}",
    "paymentAttempt": "POST /api/v1/billing/checkouts/{checkout_id}/payment-attempts",
    "quote": "POST /api/v1/billing/quotes; GET /api/v1/billing/quotes/{quote_id}; POST /api/v1/billing/quotes/{quote_id}/accept",
    "refund": "POST /api/v1/billing/payments/{payment_id}/refunds",
    "refreshToken": "POST /api/v1/auth/refresh; POST /api/v1/auth/logout",
    "region": "GET /api/v1/cities (utilisée par jointure, aucune route directe)",
    "subscription_diagnostic": "POST /api/v1/admin/cases/{case_id}/subscription-diagnostics; GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id}",
    "country": "GET /api/v1/countries",
    "city": "GET /api/v1/cities",
    "zyloLiquidDocument": "GET/POST/DELETE /api/v1/zylo-liquid/documents",
    "zyloLiquidDocumentLink": "POST /api/v1/zylo-liquid/document-links",
    "zyloLiquidGpsDevice": "Routes GPS sous /api/v1/zylo-liquid/gps-devices",
    "zyloLiquidGpsDeviceAssignment": "Routes d'affectation de GPS sous /api/v1/zylo-liquid/gps-devices",
    "zyloLiquidGpsIngestCredential": "Routes d'identifiants d'ingestion sous /api/v1/zylo-liquid/gps-ingest-credential",
    "zyloLiquidTraccarConnection": "Routes de connexion Traccar sous /api/v1/zylo-liquid/traccar-connection",
    "zyloLiquidTrackingSettings": "Routes de réglages de suivi sous /api/v1/zylo-liquid/tracking-settings",
    "zyloLiquidTruckPositionPing": "Ingestion et historique GPS sous /api/v1/zylo-liquid/gps",
    "zyloLiquidTruckStopComment": "Routes de commentaires d'arrêt sous /api/v1/zylo-liquid/trucks/{id}/stops",
    "zyloLiquidTruckStopEvent": "Routes d'arrêts de camion sous /api/v1/zylo-liquid/trucks/{id}/stops",
    "zyloLiquidTruckStopReconciliation": "Routes de rapprochement d'arrêt sous /api/v1/zylo-liquid/trucks/{id}/stops",
    "zyloLiquidTruckTrackingLocation": "Routes de positions sous /api/v1/zylo-liquid/tracking-locations",
}

_TESTS_VERIFIES = {
    "acces_support": "tests/test_be262_acces_support.py",
    "role": "tests/test_be008_rbac_modele.py; tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py",
    "rolePermission": "tests/test_be008_rbac_modele.py; tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py",
    "admin_command": "tests/test_be124_commandes_operateur.py",
    "admin_command_approval": "tests/test_be128_double_validation.py",
    "admin_command_preview": "tests/test_be125_previsualisation_commandes.py",
    "admin_notification": "tests/test_be144_notifications_action.py",
    "admin_role_assignment": "tests/test_be121_affectations_roles_admin.py; tests/test_be146_revocation_fin_fenetre.py",
    "export_audit": "tests/test_be173_export_audit.py",
    "idempotencyKeys": "tests/test_be047_installation_technique.py; tests/test_be050_desinstallation_module.py; tests/test_be051_mise_a_jour_version.py; tests/test_idempotence_be232.py",
    "legal_holds": "tests/test_be246_sortie_tenant.py",
    "module": "tests/test_be040_catalogue_modules.py; tests/test_be042_publication_modules.py; tests/test_be043_catalogue_visibilite.py",
    "module_compatibility_evaluations": "tests/test_be044_compatibilite_plans.py",
    "module_reconciliations": "tests/test_be052_reconciliation.py",
    "module_state_transitions": "tests/test_be041_machine_etats.py; tests/test_be042_publication_modules.py; tests/test_be047_installation_technique.py; tests/test_be048_disponibilite_module.py; tests/test_be050_desinstallation_module.py; tests/test_be051_mise_a_jour_version.py",
    "module_upgrade_plans": "tests/test_be044_compatibilite_plans.py",
    "module_version": "tests/test_be040_catalogue_modules.py; tests/test_be042_publication_modules.py; tests/test_be043_catalogue_visibilite.py; tests/test_be044_compatibilite_plans.py",
    "operations": "tests/test_be236_operations.py",
    "operator_access_request": "tests/test_be229_acces_operateur.py",
    "organizationModule": "tests/test_be022_catalogue_activation.py; tests/test_modules.py",
    "permission": "tests/test_be008_rbac_modele.py; tests/test_be016_lecture_roles.py; tests/test_rbac_module_roles.py",
    "planVersion": "tests/test_billing.py; tests/test_be023_plans_abonnement.py",
    "tenant_exit_requests": "tests/test_be246_sortie_tenant.py",
    "userPermissionGrant": "tests/test_be017_grants_membres.py; tests/test_rbac_grants_and_audit.py; tests/test_be008_rbac_modele.py",
    "userRole": "tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py; tests/test_rbac_grants_and_audit.py",
    "approbation_parametre": "tests/test_be159_approbation_parametres.py",
    "audit_event": "tests/test_be122_journal_audit_admin.py; tests/test_be184_journal_audit_append_only.py",
    "billing_case": "tests/test_be096_cas_facturation.py",
    "checkout": "tests/test_be081_achat_checkout.py; tests/test_be084_confirmation_abonnement.py",
    "credit_note": "tests/test_be087_avoir_correction.py",
    "consent_record": "tests/test_be076_consentements.py",
    "data_export_request": "tests/test_be098_export_donnees_facturation.py",
    "dispute": "tests/test_be094_litiges.py",
    "entitlement_allocations": "tests/test_be046_allocation_sieges.py",
    "entitlement_source_events": "tests/test_be058_liaison_facturation_entitlements.py",
    "entitlement_sync": "tests/test_be058_liaison_facturation_entitlements.py; tests/test_be085_synchronisation_droits.py",
    "paymentWebhookEvent": "tests/test_be029_webhooks_paiement.py",
    "plan": "tests/test_billing.py",
    "plan_change": "tests/test_be088_changement_plan.py",
    "reconciliation_run": "tests/test_be095_reconciliation_paiements.py; tests/test_be143_reconciliation.py",
    "reconciliation_difference": "tests/test_be095_reconciliation_paiements.py; tests/test_be143_reconciliation.py",
    "subscription": "tests/test_be026_abonnement_courant.py; tests/test_be079_agregat_subscription.py; tests/test_be080_demarrage_essai.py; tests/test_be084_confirmation_abonnement.py; tests/test_be090_resiliation_abonnement.py; tests/test_be092_reactivation_abonnement.py; tests/test_be097_cloture_abonnement.py",
    "subscription_entitlement": "tests/test_be058_liaison_facturation_entitlements.py; tests/test_be085_synchronisation_droits.py",
    "connecteur": "tests/test_be160_registre_connecteurs.py; tests/test_be162_routes_connecteurs.py",
    "consommation_evenement": "tests/test_be074_enveloppe_outbox_inbox.py",
    "currency": "tests/test_shared_currency.py",
    "dead_letters": "tests/test_be235_consommation_dlq.py",
    "exchangeRate": "tests/test_shared_currency.py",
    "export_jobs": "tests/test_be243_export_donnees.py",
    "export_job": "tests/test_be117_exports_asynchrones.py",
    "escalation": "tests/test_be142_escalade.py",
    "feature_flags": "tests/test_be251_flags.py",
    "flag_changes": "tests/test_be251_flags.py",
    "incidents": "tests/test_be247_incidents.py",
    "incident_events": "tests/test_be247_incidents.py",
    "integration_links": "tests/test_be239_integrations_liens.py",
    "loginAttempt": "tests/test_auth_rate_limit.py",
    "invoice": "tests/test_be027_factures_lecture.py; tests/test_be086_facture_brouillon_finalisation.py",
    "intervention_case": "tests/test_be123_cas_intervention.py",
    "lettreMorte": "tests/test_be165_lettres_mortes.py",
    "module_installations": "tests/test_be047_installation_technique.py",
    "notificationPushSubscription": "tests/test_be034_abonnement_push.py",
    "notification_inbox_item": "tests/test_be035_boite_reception.py",
    "notification": "tests/test_be171_consultation_notifications.py",
    "livraison": "tests/test_be171_consultation_notifications.py",
    "categorie_notification": "tests/test_be171_consultation_notifications.py",
    "preference_notification": "tests/test_be171_consultation_notifications.py",
    "organization": "tests/test_identity_organizations.py",
    "organization_user": "tests/test_identity_organizations.py; tests/test_be012_invitations_organisation.py; tests/test_be013_activation_invitation_organisation.py",
    "organizationInvitation": "tests/test_be012_invitations_organisation.py; tests/test_be013_activation_invitation_organisation.py",
    "userInvitation": "tests/test_be013_activation_invitation_organisation.py",
    "user": "tests/test_auth.py; tests/test_identity_organizations.py",
    "password_reset_token": "tests/test_password_reset.py; tests/test_be019_recuperation_mot_de_passe.py",
    "notification_delivery": "tests/test_be238_livraison_preferences.py",
    "setting_definition": "tests/test_be154_modele_parametres.py; tests/test_be158_routes_parametres.py",
    "setting_value": "tests/test_be154_modele_parametres.py; tests/test_be155_validation_parametres.py; tests/test_be156_resolution_parametres.py; tests/test_be157_application_parametres.py; tests/test_be158_routes_parametres.py",
    "settings_registry": "Aucun test associé identifié",
    "settings_history": "Aucun test associé identifié",
    "schema_evenement": "tests/test_be176_schemas_evenements.py",
    "secret_integration": "tests/test_be161_secrets_integration.py; tests/test_be239_integrations_liens.py",
    "webhook_recu": "tests/test_be083_ingestion_evenements_fournisseur.py",
    "zyloLiquidAlert": "tests/test_zylo_liquid_alerts.py",
    "outbox_evenement": "tests/test_be074_enveloppe_outbox_inbox.py; tests/test_be192_outbox_producteur.py",
    "payment_diagnostic": "tests/test_be132_diagnostic_paiement.py",
    "paymentAttempt": "tests/test_be082_tentatives_paiement.py",
    "quote": "tests/test_be077_devis.py; tests/test_be081_achat_checkout.py",
    "refund": "tests/test_be093_remboursements.py",
    "refreshToken": "tests/test_be188_session_logout.py",
    "subscription_diagnostic": "tests/test_be133_diagnostic_abonnement.py",
    "zyloLiquidDocument": "tests/test_zylo_liquid_documents.py",
    "zyloLiquidDocumentLink": "tests/test_zylo_liquid_documents.py",
    "zyloLiquidGpsDevice": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidGpsDeviceAssignment": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidGpsIngestCredential": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTraccarConnection": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTrackingSettings": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTruckPositionPing": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTruckStopComment": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTruckStopEvent": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTruckStopReconciliation": "tests/test_zylo_liquid_truck_tracking.py",
    "zyloLiquidTruckTrackingLocation": "tests/test_zylo_liquid_truck_tracking.py",
}

_COLONNES_TENANT = {
    "tenantid",
    "tenant_id",
    "beneficiarytenantid",
    "beneficiary_tenant_id",
}


def _est_metier(module: str) -> bool:
    """Indique si un mapper appartient à l'un des deux modules métier exclus."""
    return any(module.startswith(prefix) for prefix in _PAQUETS_METIER_EXCLUS)


def _mapper_par_table() -> dict[str, list[object]]:
    """Associe les tables aux mappers déjà enregistrés par l'application."""
    from app.core.database import Base

    resultat: dict[str, list[object]] = {}
    for mapper in Base.registry.mappers:
        resultat.setdefault(mapper.local_table.name, []).append(mapper)
    return resultat


def _tables_socle() -> list[tuple[Table, str]]:
    """Retourne toutes les tables du socle et leur module propriétaire ORM."""
    from app.core.database import Base

    mappers = _mapper_par_table()
    tables: list[tuple[Table, str]] = []
    for table in Base.metadata.tables.values():
        candidats = [
            mapper
            for mapper in mappers.get(table.name, [])
            if not _est_metier(mapper.class_.__module__)
        ]
        if not candidats:
            if mappers.get(table.name):
                continue
            raise ValueError(f"Table SQLAlchemy sans classe ORM propriétaire: {table.name}")
        modules = sorted({mapper.class_.__module__ for mapper in candidats})
        tables.append((table, modules[0]))
    return sorted(tables, key=lambda item: item[0].name.casefold())


def _cible_fk(table: Table, nom_colonne: str) -> str | None:
    """Renvoie la cible déclarée par une clé étrangère, si elle existe."""
    colonne = table.columns.get(nom_colonne)
    if colonne is None:
        return None
    for foreign_key in colonne.foreign_keys:
        if foreign_key.target_fullname == "organization.id":
            return foreign_key.target_fullname
    if colonne.foreign_keys:
        return sorted(fk.target_fullname for fk in colonne.foreign_keys)[0]
    return None


def _portee(table: Table) -> str:
    """Décrit la portée avec une preuve explicite, sans la déduire du nom de table."""
    if table.name in _PORTÉES_EXPLICITES:
        return _PORTÉES_EXPLICITES[table.name]
    if table.name in _PORTÉES_CATALOGUE_GLOBAL:
        return _PORTÉES_CATALOGUE_GLOBAL[table.name]
    if table.name in _PORTÉES_UTILISATEUR:
        return _PORTÉES_UTILISATEUR[table.name]

    for nom in ("tenantId", "tenant_id", "beneficiaryTenantId", "beneficiary_tenant_id"):
        colonne = table.columns.get(nom)
        if colonne is None:
            continue
        cible = _cible_fk(table, nom)
        if cible == "organization.id" and not colonne.nullable:
            return "organisation (champ tenantId vers organization.id)"
        return "NON DÉFINI"

    for nom in ("organizationId", "organization_id"):
        colonne = table.columns.get(nom)
        if colonne is None:
            continue
        if _cible_fk(table, nom) == "organization.id" and not colonne.nullable:
            return "organisation"

    return "NON DÉFINI"


def _ligne(table: Table, module: str) -> tuple[str, str, str, str, str]:
    """Prépare les cinq cellules visibles d'une entrée d'inventaire."""
    routes = _ROUTES_VERIFIEES.get(
        table.name, "À vérifier — aucune liaison prouvée"
    )
    tests = _TESTS_VERIFIES.get(
        table.name, "Aucun test associé identifié"
    )
    return table.name, module, _portee(table), routes, tests


def _echapper_cellule(valeur: str) -> str:
    """Échappe les caractères Markdown interdits dans une cellule de tableau."""
    return valeur.replace("|", "&#124;").replace("\n", "<br>").strip()


def _table_markdown(lignes: Iterable[tuple[str, str, str, str, str]]) -> str:
    """Rend les lignes d'inventaire dans un tableau Markdown déterministe."""
    entetes = ("Table", "Propriétaire", "Portée", "Routes HTTP", "Tests associés")
    resultat = ["| " + " | ".join(entetes) + " |", "| --- | --- | --- | --- | --- |"]
    for ligne in lignes:
        cellules = [_echapper_cellule(valeur) for valeur in ligne]
        resultat.append("| " + " | ".join(cellules) + " |")
    return "\n".join(resultat)


def noms_tables_socle() -> list[str]:
    """Renvoie les noms, triés, des tables du périmètre de l'inventaire.

    Le périmètre dépend des modules importés par l'appelant : il faut avoir chargé
    `app.main` et `MODULES_ORM_SOCLE_HORS_APP` avant l'appel.
    """
    return [table.name for table, _module in _tables_socle()]


def render_inventory_markdown() -> str:
    """Produit le document canonique après chargement des modèles par l'appelant.

    L'application doit avoir importé ses modèles (par exemple via ``app.main``)
    avant l'appel; ce module du cœur ne charge pas la couche application.
    """
    tables = _tables_socle()
    lignes = [_ligne(table, module) for table, module in tables]
    entete = """# Inventaire des tables du socle Zylo Office

## Périmètre et méthode

L'inventaire couvre les classes ORM enregistrées lorsque l'application backend
charge `app.main`, à l'exclusion des seuls paquets métier
`app.modules.zylo_liquid` et `app.modules.zylo_tanker`. Les capacités partagées
comme `files`, `alerts` et `location` restent incluses, même si une table porte
un préfixe `zyloLiquid`. Le propriétaire indiqué est le module Python qui
déclare le modèle ORM, pas le numéro du lot qui l'a introduit.

Les portées sont renseignées à partir des clés étrangères, colonnes et décisions
documentées. `NON DÉFINI` signifie qu'aucune source vérifiée ne permet de fixer
la portée. `À vérifier` signale qu'aucune association table-route n'a été prouvée
dans le handler et son service. Les tests cités sont ceux qui ont été reliés au
modèle par inspection; `Aucun test associé identifié` n'affirme pas qu'aucun
test général ne pourrait le couvrir.

La source ISS-084 est un échantillon historique non exhaustif. La présence d'une
table ou d'une route dans cet inventaire ne prouve ni son isolation ni la
couverture de tous ses chemins. Les contrôles d'accès et d'isolation restent à
vérifier dans les tests dédiés de chaque capacité.

Les colonnes historiques `tenantId` qui référencent `organization.id` sont
notées comme organisationnelles; le nom historique ne crée pas un objet Tenant
distinct. Une portée multi-portée n'est indiquée que lorsqu'une contrainte, une
documentation de modèle ou un service établit explicitement les deux portées;
la nullabilité seule ne suffit pas. Le modèle ne précise pas si le compte
``billing_payer`` correspond à une personne ou à une organisation; ce point reste
ouvert dans [QE-FAC-22](../../../../implementation-backend/POINTS-OUVERTS.md#qe-fac-22).

Les routes marquées `À vérifier` restent des associations non prouvées et
l'inventaire ne prétend donc pas couvrir intégralement CA1. Une route peut être
documentée sans test associé identifié, et inversement.

Génération et contrôle: `python scripts/docs/generer_inventaire_tables_socle.py`
et `python scripts/docs/generer_inventaire_tables_socle.py --check`.

"""
    return entete + _table_markdown(lignes) + "\n"

