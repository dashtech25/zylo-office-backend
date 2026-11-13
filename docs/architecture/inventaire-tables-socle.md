# Inventaire des tables du socle Zylo Office

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

| Table | Propriétaire | Portée | Routes HTTP | Tests associés |
| --- | --- | --- | --- | --- |
| acces_support | app.support.models | organisation | POST /api/v1/organizations/{organization_id}/acces-support; GET /api/v1/organizations/{organization_id}/acces-support/courant | tests/test_be262_acces_support.py |
| admin_command | app.operator.commands | multi-portée (effectiveScope: platform ou tenant:<uuid>) | GET/POST /api/v1/admin/commands; GET /api/v1/admin/commands/{command_id}; POST /api/v1/admin/commands/{command_id}/approve; POST /api/v1/admin/commands/{command_id}/reject; POST /api/v1/admin/commands/{command_id}/preview; POST /api/v1/admin/commands/{command_id}/confirm; POST /api/v1/admin/commands/{command_id}/reconcile; POST /api/v1/admin/commands/{command_id}/verify | tests/test_be124_commandes_operateur.py |
| admin_command_approval | app.operator.approval | portée héritée de la commande parente (tenant ou plateforme) | POST /api/v1/admin/commands/{command_id}/approve; POST /api/v1/admin/commands/{command_id}/reject | tests/test_be128_double_validation.py |
| admin_command_preview | app.operator.preview | portée héritée de la commande parente (tenant ou plateforme) | POST /api/v1/admin/commands/{command_id}/preview; POST /api/v1/admin/commands/{command_id}/confirm | tests/test_be125_previsualisation_commandes.py |
| admin_notification | app.notifications.admin_notifications | portée héritée de la commande parente (tenant ou plateforme) | GET /api/v1/admin/commands/{command_id}/notifications | tests/test_be144_notifications_action.py |
| admin_role_assignment | app.rbac.role_assignments | multi-portée (scope: platform ou tenant:<uuid>) | POST/GET /api/v1/admin/role-assignments; POST /api/v1/admin/role-assignments/{assignment_id}/revoke | tests/test_be121_affectations_roles_admin.py; tests/test_be146_revocation_fin_fenetre.py |
| alert_routes | app.operator.alertes_models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| approbation_parametre | app.parametres.models | portée déclarée (plateforme, organisation, module ou utilisateur; scopeKind contraint) | GET /api/v1/approbations/{demande_id}; POST /api/v1/approbations/{demande_id}/decisions | tests/test_be159_approbation_parametres.py |
| audit_event | app.audit.models | multi-portée explicite (organisation et plateforme pour les lectures opérateur; écart entre commentaire et writer à suivre) | GET /api/v1/admin/audit-events; GET /api/v1/audit/records | tests/test_be122_journal_audit_admin.py; tests/test_be184_journal_audit_append_only.py |
| billing_case | app.billing.models | organisation | POST /api/v1/billing/cases; POST /api/v1/billing/cases/{case_id}/resolve | tests/test_be096_cas_facturation.py |
| billing_payer | app.billing.models | NON DÉFINI | Aucun endpoint direct; payeur résolu via devis et checkout | Aucun test associé identifié |
| capability | app.billing.models | globale (catalogue de capacités) | Aucun endpoint direct; capacités consultées par les services d'entitlement | Aucun test associé identifié |
| capacity_samples | app.operator.capacite_models | organisation attribuée (tenantId, simple référence sans clé étrangère) | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| categorie_notification | app.notifications.models | globale (catalogue) | GET /api/v1/notifications/preferences; PUT /api/v1/notifications/preferences/{categorie_code} | tests/test_be171_consultation_notifications.py |
| checkout | app.billing.models | organisation bénéficiaire (devis parent) | POST /api/v1/billing/checkouts; GET /api/v1/billing/checkouts/{checkout_id} | tests/test_be081_achat_checkout.py; tests/test_be084_confirmation_abonnement.py |
| city | app.shared.geo | globale (référentiel géographique) | GET /api/v1/cities | Aucun test associé identifié |
| classification_champ | app.securite.models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| close_operation | app.billing.models | organisation bénéficiaire (abonnement parent) | POST /api/v1/billing/subscriptions/{subscription_id}/close | Aucun test associé identifié |
| compensations | app.release.models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| connecteur | app.integrations.models | multi-portée (portee globale ou organisation, contrainte du modèle) | GET/POST /api/v1/connecteurs; routes de transition et configuration | tests/test_be160_registre_connecteurs.py; tests/test_be162_routes_connecteurs.py |
| consent_record | app.billing.models | multi-portée (scope de consentement: payeur, tenant ou bénéficiaire) | POST /api/v1/billing/consents | tests/test_be076_consentements.py |
| consommation_evenement | app.evenements.models | portée héritée de l'événement outbox consommé | Aucun endpoint direct; traitement par le dispatcher d'événements | tests/test_be074_enveloppe_outbox_inbox.py |
| country | app.shared.geo | globale (référentiel géographique) | GET /api/v1/countries | Aucun test associé identifié |
| credit_note | app.billing.models | organisation bénéficiaire (facture parente) | POST /api/v1/billing/invoices/{invoice_id}/credit-notes | tests/test_be087_avoir_correction.py |
| currency | app.shared.currency | globale (référentiel de devises) | GET/POST/PATCH /api/v1/currencies | tests/test_shared_currency.py |
| data_export_request | app.billing.models | organisation | POST /api/v1/billing/data-exports | tests/test_be098_export_donnees_facturation.py |
| dead_letters | app.evenements.models | organisation (tenantId vers organization.id) | GET/POST /api/v1/internal/dead-letters | tests/test_be235_consommation_dlq.py |
| dispute | app.billing.models | organisation bénéficiaire (tentative de paiement parente) | GET /api/v1/billing/disputes/{dispute_id}; ingestion webhook fournisseur de paiement | tests/test_be094_litiges.py |
| entitlement_allocations | app.billing.models | organisation | POST /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations; DELETE /api/v1/organizations/{organization_id}/entitlements/{entitlement_id}/allocations/{user_id} | tests/test_be046_allocation_sieges.py |
| entitlement_source_events | app.billing.models | organisation (organizationId journalisé) | POST /api/v1/internal/billing/entitlement-events | tests/test_be058_liaison_facturation_entitlements.py |
| entitlement_sync | app.billing.models | organisation bénéficiaire (abonnement parent) | POST /api/v1/internal/billing/entitlement-events | tests/test_be058_liaison_facturation_entitlements.py; tests/test_be085_synchronisation_droits.py |
| escalation | app.operator.escalation | portée héritée du cas d'intervention parent | POST /api/v1/admin/cases/{case_id}/escalations; POST /api/v1/admin/escalations/{escalation_id}/close | tests/test_be142_escalade.py |
| event_inbox | app.evenements.models | organisation (tenantId, quarantaine d'événements tenant) | Aucun endpoint direct; traitement interne de consommation d'événements | Aucun test associé identifié |
| exchangeRate | app.shared.currency | globale (référentiel de taux) | GET/POST /api/v1/exchange-rates | tests/test_shared_currency.py |
| export_audit | app.audit.models | organisation | POST /api/v1/audit/exports; GET /api/v1/audit/exports/{job_id}; GET /api/v1/audit/exports/{job_id}/telechargement | tests/test_be173_export_audit.py |
| export_job | app.portail.exports.models | organisation | POST /api/v1/organizations/{organization_id}/exports; GET /api/v1/organizations/{organization_id}/exports/{export}; GET /api/v1/organizations/{organization_id}/exports/{export}/download | tests/test_be117_exports_asynchrones.py |
| export_jobs | app.exports.models | organisation | POST /api/v1/exports; GET /api/v1/exports/{id}; GET /api/v1/exports/{id}/download | tests/test_be243_export_donnees.py |
| feature_flags | app.core.flags | organisation | GET /api/v1/internal/flags; PUT /api/v1/internal/flags/{flag_key} | tests/test_be251_flags.py |
| flag_changes | app.core.flags | organisation | GET /api/v1/internal/flags; PUT /api/v1/internal/flags/{flag_key} (journal écrit par le PUT) | tests/test_be251_flags.py |
| idempotency_record | app.billing.models | acteur et clé de portée (principal, route et clé d'idempotence) | Aucun endpoint direct; table interne au mécanisme d'idempotence | Aucun test associé identifié |
| idempotencyKeys | app.core.idempotency | organisation et acteur (couple de portée documenté) | Aucun endpoint CRUD direct; table interne utilisée par run_idempotent sur les routes d'installation, mise à jour et suppression | tests/test_be047_installation_technique.py; tests/test_be050_desinstallation_module.py; tests/test_be051_mise_a_jour_version.py; tests/test_idempotence_be232.py |
| incident_events | app.operator.incidents_models | portée héritée de l'incident parent | GET /api/v1/admin/incidents/{incident_id} (chronologie incluse) | tests/test_be247_incidents.py |
| incidents | app.operator.incidents_models | multi-portée (plateforme ou organisation) | GET /api/v1/admin/incidents; GET /api/v1/admin/incidents/{incident_id} | tests/test_be247_incidents.py |
| integration_links | app.integrations.models | organisation | GET /api/v1/integrations/integrations; POST /api/v1/integrations/integrations/{provider}/connect; POST /api/v1/integrations/integrations/{lien_id}/disconnect | tests/test_be239_integrations_liens.py |
| intervention_case | app.operator.cases | multi-portée (plateforme ou organisation) | POST/GET /api/v1/admin/cases; POST /api/v1/admin/cases/{case_id}/assign; POST /api/v1/admin/cases/{case_id}/close | tests/test_be123_cas_intervention.py |
| invitation | app.identity.models | organisation (organizationId du modèle) | Aucune route HTTP identifiée; aucune référence par les handlers | Aucun test associé identifié |
| invoice | app.billing.models | organisation bénéficiaire (abonnement parent) | GET /api/v1/organizations/current/invoices; GET /api/v1/organizations/current/invoices/{invoice_id}; GET /api/v1/billing/invoices/{invoice_id}; POST /api/v1/billing/invoices/{invoice_id}/finalize; POST /api/v1/billing/invoices/{invoice_id}/credit-notes | tests/test_be027_factures_lecture.py; tests/test_be086_facture_brouillon_finalisation.py |
| job | app.jobs.models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| job_error_report | app.jobs.models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| legal_holds | app.sortie_tenant.models | organisation | Aucun endpoint CRUD direct; holds internes vérifiés lors de la sortie du tenant | tests/test_be246_sortie_tenant.py |
| lettreMorte | app.integrations.models | organisation | GET /api/v1/integrations/lettres-mortes; POST /api/v1/integrations/lettres-mortes/{lettre_id}/reprises | tests/test_be165_lettres_mortes.py |
| livraison | app.notifications.models | utilisateur destinataire via notification parente; tenant non persisté | GET /api/v1/notifications/{notification_id}/livraisons | tests/test_be171_consultation_notifications.py |
| loginAttempt | app.auth.models | globale (clé pseudonymisée de limitation d'authentification) | Aucune route CRUD directe; lecture, écriture et purge par le rate limit de POST /api/v1/auth/login, /register et /refresh | tests/test_auth_rate_limit.py |
| module | app.modules_registry.models | globale (catalogue de modules) | POST /api/v1/admin/modules; GET /api/v1/admin/modules/{module_id}; GET /api/v1/catalog/modules; GET /api/v1/catalog/modules/{slug}; GET /api/v1/modules | tests/test_be040_catalogue_modules.py; tests/test_be042_publication_modules.py; tests/test_be043_catalogue_visibilite.py |
| module_compatibility_evaluations | app.modules_registry.models | globale (compatibilité de versions) | POST /api/v1/admin/modules/{module_id}/versions/{version_id}/compatibility-evaluations | tests/test_be044_compatibilite_plans.py |
| module_installations | app.modules_registry.models | organisation | POST /api/v1/organizations/{organization_id}/modules/{module_id}/installations; GET /api/v1/organizations/{organization_id}/modules/{module_id}/installations/{operation_id} | tests/test_be047_installation_technique.py |
| module_permissions | app.modules_registry.models | scope contraint (organization, tenant ou platform) | GET /api/v1/organizations/{organization_id}/modules/{module_id}/permissions | Aucun test associé identifié |
| module_reconciliations | app.modules_registry.models | organisation | GET /api/v1/admin/reconciliations; POST /api/v1/admin/reconciliations/{reconciliation_id}/resolve | tests/test_be052_reconciliation.py |
| module_state_transitions | app.modules_registry.models | multi-portée (organisation ou sujet de plateforme) | Aucun endpoint direct; journal écrit par les routes de cycle de vie des modules | tests/test_be041_machine_etats.py; tests/test_be042_publication_modules.py; tests/test_be047_installation_technique.py; tests/test_be048_disponibilite_module.py; tests/test_be050_desinstallation_module.py; tests/test_be051_mise_a_jour_version.py |
| module_upgrade_plans | app.modules_registry.models | globale (catalogue de modules) | POST /api/v1/admin/modules/{module_id}/upgrade-plans | tests/test_be044_compatibilite_plans.py |
| module_version | app.modules_registry.models | globale (catalogue de versions) | POST /api/v1/admin/modules/{module_id}/versions; POST /api/v1/admin/modules/{module_id}/versions/{version_id}/publish; versions publiées visibles dans GET /api/v1/catalog/modules/{slug} | tests/test_be040_catalogue_modules.py; tests/test_be042_publication_modules.py; tests/test_be043_catalogue_visibilite.py; tests/test_be044_compatibilite_plans.py |
| notification | app.notifications.models | utilisateur destinataire; audience tenant résolue mais tenant non persisté | GET /api/v1/notifications | tests/test_be171_consultation_notifications.py |
| notification_delivery | app.notifications.models | utilisateur destinataire via notification parente; tenant non persisté | Aucun endpoint direct; résultat écrit par le service de livraison BE-238 | tests/test_be238_livraison_preferences.py |
| notification_inbox_item | app.notifications.models | organisation | GET /api/v1/notifications/inbox; GET/PATCH /api/v1/notifications/inbox/{item_id} | tests/test_be035_boite_reception.py |
| notificationPushSubscription | app.notifications.models | organisation | POST /api/v1/notifications/push-subscriptions; DELETE /api/v1/notifications/push-subscriptions/{subscription_id} | tests/test_be034_abonnement_push.py |
| operations | app.operations.models | organisation (tenantId vers organization.id) | GET /api/v1/operations/{operation_id}; création et transitions internes | tests/test_be236_operations.py |
| operator_access_request | app.operator.access | organisation (tenantId vers organization.id) | POST /api/v1/admin/access-requests; POST /api/v1/admin/access-requests/{request_id}/approve; DELETE /api/v1/admin/access-requests/{request_id} | tests/test_be229_acces_operateur.py |
| organization | app.identity.models | organisation (racine du tenant) | GET /api/v1/organizations; GET /api/v1/organizations/current; POST /api/v1/organizations; PATCH /api/v1/organizations/{organization_id} | tests/test_identity_organizations.py |
| organization_user | app.identity.models | organisation (appartenance au tenant) | GET /api/v1/organizations/current/members; appartenance créée par activation d'invitation (aucun CRUD direct) | tests/test_identity_organizations.py; tests/test_be012_invitations_organisation.py; tests/test_be013_activation_invitation_organisation.py |
| organizationInvitation | app.identity.models | organisation (invitation au tenant) | POST/GET /api/v1/organizations/current/invitations | tests/test_be012_invitations_organisation.py; tests/test_be013_activation_invitation_organisation.py |
| organizationModule | app.modules_registry.models | organisation | GET /api/v1/organizations/current/modules; PUT /api/v1/organizations/current/modules/{module_id}/activation; GET /api/v1/modules/organizations/{organization_id}; POST /api/v1/modules/organizations/{organization_id}/activate; POST /api/v1/modules/organizations/{organization_id}/deactivate | tests/test_be022_catalogue_activation.py; tests/test_modules.py |
| outbox_evenement | app.evenements.models | multi-portée (plateforme ou organisation) | Aucun endpoint direct; écriture et lecture internes par producteur/dispatcher | tests/test_be074_enveloppe_outbox_inbox.py; tests/test_be192_outbox_producteur.py |
| password_reset_token | app.auth.models | utilisateur global | POST /api/v1/auth/password-reset/request; POST /api/v1/auth/password-reset/confirm | tests/test_password_reset.py; tests/test_be019_recuperation_mot_de_passe.py |
| payment_diagnostic | app.operator.payment_diagnostic | portée héritée du cas d'intervention parent | POST /api/v1/admin/cases/{case_id}/payment-diagnostics; GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id} | tests/test_be132_diagnostic_paiement.py |
| payment_method_reference | app.billing.models | organisation | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| paymentAttempt | app.billing.models | organisation bénéficiaire (facture ou checkout parent) | POST /api/v1/billing/checkouts/{checkout_id}/payment-attempts | tests/test_be082_tentatives_paiement.py |
| paymentWebhookEvent | app.billing.models | globale fournisseur (clé eventId, sans portée tenant) | POST /api/v1/billing/provider-events; POST /api/v1/billing/webhooks/flutterwave (alias historique) | tests/test_be029_webhooks_paiement.py |
| permission | app.rbac.models | globale (catalogue de permissions) | GET /api/v1/rbac/organizations/{organization_id}/permissions (catalogue global) | tests/test_be008_rbac_modele.py; tests/test_be016_lecture_roles.py; tests/test_rbac_module_roles.py |
| plan | app.billing.models | globale (catalogue d'offres) | GET /api/v1/billing/plans | tests/test_billing.py |
| plan_change | app.billing.models | organisation bénéficiaire (abonnement parent) | POST /api/v1/billing/subscriptions/{subscription_id}/plan-change/preview; POST /api/v1/billing/subscriptions/{subscription_id}/plan-change | tests/test_be088_changement_plan.py |
| plan_version_snapshot | app.billing.models | organisation | Aucun endpoint direct; instantané consulté par les flux d'abonnement et devis | Aucun test associé identifié |
| planVersion | app.billing.models | globale (catalogue de versions d'offres) | Aucun CRUD direct; version active exposée par GET /api/v1/billing/plans | tests/test_billing.py; tests/test_be023_plans_abonnement.py |
| preference_notification | app.notifications.models | utilisateur dans l'organisation active | GET /api/v1/notifications/preferences; PUT /api/v1/notifications/preferences/{categorie_code} | tests/test_be171_consultation_notifications.py |
| price_rule | app.billing.models | organisation | Aucun endpoint direct; règles consultées par le résolveur de prix | Aucun test associé identifié |
| quote | app.billing.models | organisation bénéficiaire (beneficiaryTenantId vers organization.id) | POST /api/v1/billing/quotes; GET /api/v1/billing/quotes/{quote_id}; POST /api/v1/billing/quotes/{quote_id}/accept | tests/test_be077_devis.py; tests/test_be081_achat_checkout.py |
| rate_limit_events | app.core.ratelimit | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| reconciliation_difference | app.billing.models | organisation bénéficiaire (run de rapprochement parent) | POST /api/v1/billing/reconciliations | tests/test_be095_reconciliation_paiements.py; tests/test_be143_reconciliation.py |
| reconciliation_run | app.billing.models | organisation | POST /api/v1/billing/reconciliations | tests/test_be095_reconciliation_paiements.py; tests/test_be143_reconciliation.py |
| refreshToken | app.auth.models | utilisateur global | POST /api/v1/auth/refresh; POST /api/v1/auth/logout | tests/test_be188_session_logout.py |
| refund | app.billing.models | organisation bénéficiaire (tentative de paiement parente) | POST /api/v1/billing/payments/{payment_id}/refunds | tests/test_be093_remboursements.py |
| region | app.shared.geo | globale (référentiel géographique) | GET /api/v1/cities (utilisée par jointure, aucune route directe) | Aucun test associé identifié |
| regle_notification | app.notifications.models | globale (catalogue de règles) | Aucun endpoint direct; règles lues par le moteur BE-169 | Aucun test associé identifié |
| release_records | app.release.models | NON DÉFINI | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| renewal_run | app.billing.models | organisation bénéficiaire (abonnement parent) | Aucun endpoint direct; exécution par tâche de renouvellement | Aucun test associé identifié |
| role | app.rbac.models | organisation | GET /api/v1/rbac/organizations/{organization_id}/roles | tests/test_be008_rbac_modele.py; tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py |
| rolePermission | app.rbac.models | organisation (portée du rôle parent) | PUT /api/v1/rbac/organizations/{organization_id}/roles/{role_id}/permissions | tests/test_be008_rbac_modele.py; tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py |
| schema_evenement | app.evenements.models | globale (registre de schémas) | GET /api/v1/admin/evenements/types | tests/test_be176_schemas_evenements.py |
| secret_integration | app.integrations.models | portée héritée du connecteur parent (globale ou organisation) | POST /api/v1/integrations/integrations/{provider}/connect (création interne; aucun endpoint secret dédié) | tests/test_be161_secrets_integration.py; tests/test_be239_integrations_liens.py |
| secret_registry | app.operator.secrets_models | globale par environnement (registre de secrets) | Aucune route HTTP identifiée; registre de métadonnées de secrets d'environnement | Aucun test associé identifié |
| setting_definition | app.parametres.models | portée déclarée (plateforme, organisation, module ou utilisateur; scopeKind contraint) | GET /api/v1/parametres/{scope_kind}/{scope_id} | tests/test_be154_modele_parametres.py; tests/test_be158_routes_parametres.py |
| setting_value | app.parametres.models | portée de la valeur (plateforme, organisation, module ou utilisateur; scopeKind contraint) | GET /api/v1/parametres/{scope_kind}/{scope_id}; PUT /api/v1/parametres/{scope_kind}/{scope_id}/{cle}; POST /api/v1/parametres/{scope_kind}/{scope_id}/{cle}/restaurations | tests/test_be154_modele_parametres.py; tests/test_be155_validation_parametres.py; tests/test_be156_resolution_parametres.py; tests/test_be157_application_parametres.py; tests/test_be158_routes_parametres.py |
| settings_history | app.settings.models | portée de l'historique (platform, tenant, membership ou workspace; scopeKind contraint) | Aucune route HTTP identifiée; historique interne des réglages | Aucun test associé identifié |
| settings_registry | app.settings.models | portée déclarée (platform, tenant, membership ou workspace; scopeKind contraint) | Aucune route HTTP identifiée; registre interne des réglages | Aucun test associé identifié |
| subscription | app.billing.models | organisation bénéficiaire (beneficiaryTenantId; organizationId repris par migration) | POST /api/v1/billing/organizations/{organization_id}/subscriptions; GET /api/v1/billing/organizations/{organization_id}/subscription; GET /api/v1/billing/subscriptions/{subscription_id}; POST /api/v1/billing/subscriptions/{subscription_id}/cancel; POST /api/v1/billing/subscriptions/{subscription_id}/reactivate; POST /api/v1/billing/subscriptions/{subscription_id}/close | tests/test_be026_abonnement_courant.py; tests/test_be079_agregat_subscription.py; tests/test_be080_demarrage_essai.py; tests/test_be084_confirmation_abonnement.py; tests/test_be090_resiliation_abonnement.py; tests/test_be092_reactivation_abonnement.py; tests/test_be097_cloture_abonnement.py |
| subscription_diagnostic | app.operator.subscription_diagnostic | portée héritée du cas d'intervention parent | POST /api/v1/admin/cases/{case_id}/subscription-diagnostics; GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id} | tests/test_be133_diagnostic_abonnement.py |
| subscription_entitlement | app.billing.models | multi-portée (offre globale ou organisation) | POST /api/v1/internal/billing/entitlement-events; GET /api/v1/organizations/current/entitlements | tests/test_be058_liaison_facturation_entitlements.py; tests/test_be085_synchronisation_droits.py |
| support_request | app.support.models | organisation | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| tenant | app.identity.models | organisation (un tenant par organisation) | Aucune route HTTP identifiée; modèle non utilisé par les handlers HTTP | Aucun test associé identifié |
| tenant_exit_requests | app.sortie_tenant.models | organisation | POST /api/v1/organizations/{organization_id}/exit; GET /api/v1/organizations/{organization_id}/exit/attestation | tests/test_be246_sortie_tenant.py |
| tentativeIntegration | app.integrations.models | organisation (organizationId journalisé) | Aucune route HTTP identifiée; journal interne des tentatives (BE-164) | Aucun test associé identifié |
| usage_snapshot | app.billing.models | organisation | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| user | app.identity.models | utilisateur global | POST /api/v1/auth/register; GET /api/v1/auth/me; GET /api/v1/account/profile; PATCH /api/v1/users/{user_id} | tests/test_auth.py; tests/test_identity_organizations.py |
| userInvitation | app.identity.models | organisation (invitation au membre du tenant) | POST /api/v1/organizations/{organization_id}/users; POST /api/v1/organizations/{organization_id}/users/{user_id}/invitation; POST /api/v1/auth/activate | tests/test_be013_activation_invitation_organisation.py |
| userPermissionGrant | app.rbac.models | organisation | POST/DELETE /api/v1/organizations/current/members/{user_id}/grants[/{grant_id}]; GET /api/v1/rbac/organizations/{organization_id}/users/{user_id}/grants; POST/DELETE /api/v1/rbac/organizations/{organization_id}/grants[/{grant_id}] | tests/test_be017_grants_membres.py; tests/test_rbac_grants_and_audit.py; tests/test_be008_rbac_modele.py |
| userRole | app.rbac.models | organisation | PUT /api/v1/organizations/current/members/{user_id}/roles; GET /api/v1/organizations/current/roles; POST/DELETE /api/v1/rbac/organizations/{organization_id}/user-roles[/{assignment_id}] | tests/test_be015_affectation_roles.py; tests/test_be016_lecture_roles.py; tests/test_rbac_grants_and_audit.py |
| verification_case | app.portail.verification.models | organisation | À vérifier — aucune liaison prouvée | Aucun test associé identifié |
| webhook_recu | app.integrations.models | multi-portée (organisation du connecteur ou portée globale) | POST /api/v1/integrations/webhooks/{connecteur_id} | tests/test_be083_ingestion_evenements_fournisseur.py |
| zyloLiquidAlert | app.alerts.models | organisation (portée résolue par jointure station/truck/vessel; le modèle ne garantit pas un owner unique) | GET /api/v1/zylo-liquid/alerts; GET /api/v1/zylo-liquid/alerts/{alert_id}; POST /api/v1/zylo-liquid/alerts/{alert_id}/acknowledge; PATCH /api/v1/zylo-liquid/alerts/{alert_id} | tests/test_zylo_liquid_alerts.py |
| zyloLiquidDocument | app.files.models | organisation | GET/POST/DELETE /api/v1/zylo-liquid/documents | tests/test_zylo_liquid_documents.py |
| zyloLiquidDocumentLink | app.files.models | organisation héritée du document parent | POST /api/v1/zylo-liquid/document-links | tests/test_zylo_liquid_documents.py |
| zyloLiquidGpsDevice | app.location.models | organisation | Routes GPS sous /api/v1/zylo-liquid/gps-devices | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidGpsDeviceAssignment | app.location.models | organisation héritée du GPS affecté | Routes d'affectation de GPS sous /api/v1/zylo-liquid/gps-devices | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidGpsIngestCredential | app.location.models | organisation | Routes d'identifiants d'ingestion sous /api/v1/zylo-liquid/gps-ingest-credential | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTraccarConnection | app.location.models | organisation | Routes de connexion Traccar sous /api/v1/zylo-liquid/traccar-connection | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTrackingSettings | app.location.models | organisation | Routes de réglages de suivi sous /api/v1/zylo-liquid/tracking-settings | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTruckPositionPing | app.location.models | organisation héritée du GPS source | Ingestion et historique GPS sous /api/v1/zylo-liquid/gps | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTruckStopComment | app.location.models | organisation héritée de l'événement d'arrêt parent | Routes de commentaires d'arrêt sous /api/v1/zylo-liquid/trucks/{id}/stops | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTruckStopEvent | app.location.models | organisation de l'actif suivi (truck XOR vessel, vérifiée par le service) | Routes d'arrêts de camion sous /api/v1/zylo-liquid/trucks/{id}/stops | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTruckStopReconciliation | app.location.models | organisation héritée de l'événement d'arrêt parent | Routes de rapprochement d'arrêt sous /api/v1/zylo-liquid/trucks/{id}/stops | tests/test_zylo_liquid_truck_tracking.py |
| zyloLiquidTruckTrackingLocation | app.location.models | organisation | Routes de positions sous /api/v1/zylo-liquid/tracking-locations | tests/test_zylo_liquid_truck_tracking.py |
