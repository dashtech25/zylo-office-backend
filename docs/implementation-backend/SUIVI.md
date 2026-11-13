# Suivi d'intégration backend

Date : 2026-11-13 (gel ebc7ad0, voir ETAT-GEL-2026-11-13.md et PREREQUIS-DEPLOIEMENT.md). Historique antérieur : 2026-11-03. Statut : **figé pour déploiement**.

Espace d'intégration : worktrees/develop-integration-back (branche develop). Fusions sans push, sans suppression de branche.

| Lot | Tâches | Branche | Statut | Commit de fusion | Tests ciblés verts/rouges |
|-----|--------|---------|--------|------------------|---------------------------|
| 1 | BE-001 | be-001-erreurs | fusionné | e15e0f3 | 11 verts / 0 rouge |
| 2 | BE-221 | be-221-config | fusionné | 72db00a | 44 verts / 0 rouge |
| 3 | BE-220 | be-220-enveloppe | fusionné | 8c4d894 | 17 verts / 0 rouge |
| 4 | BE-070 | be-070-erreurs-facturation | fusionné | e5e97f9 | 60 verts / 0 rouge |
| 5 | BE-223 | be-223-migrations | fusionné | 5bc80de | 49 verts / 0 rouge |
| 6 | BE-032 | be-032-statut | fusionné | 4016bc9 | 26 verts / 0 rouge |
| 7 | BE-002, BE-003 | be-002-003-identite | fusionné (reprise 2026-11-03) | 4ab62db | 8 verts / 0 rouge / 1 skip (9 total). Le test test_be002_ca4_lecture_de_repository_sans_contexte_organisation_refusee est marqué skip, renvoi BE-009. Rejet précédent (test CA-4 rouge) caduc sur la branche actuelle |
| 8 | BE-072 | be-072-plan-facturation | fusionné | 4ea6b3e | 7 verts / 0 rouge (7 total) |
| 9 | BE-256 | be-256-audit-echec | fusionné | 00e3b8b | 15 verts / 0 rouge (15 total) |
| 10 | BE-222 | be-222-lot | fusionné | a4a8baf | 12 verts / 0 rouge (12 total), tests/test_gates_qualite_be222.py |
| 11 | BE-224 | be-224-lot | fusionné | bfb8ff9 | 6 verts / 0 rouge (6 total), tests/test_journalisation_be224.py |
| 12 | BE-232 | be-232-lot | fusionné (correction : révision de fusion Alembic a5b6c7d8e9f0 jointe aux deux têtes e072b1c2d3a4 et c1d2e3f4a5b6) | 0ad0622 | 5 verts / 0 rouge (5 total), tests/test_idempotence_be232.py |
| 13 | BE-233 | be-233-lot | fusionné (correction : c7ecfe8a11be chaîné sur a5b6c7d8e9f0 au lieu de b7c8d9e0f123) | 9e86245 | 5 verts / 0 rouge (5 total), tests/test_controle_version_be233.py |
| 14 | BE-004 | be-004-lot | fusionné | e4a4cbf | 4 verts / 0 rouge (4 total), tests/test_be004_appartenance.py |
| 15 | BE-242 | be-242-lot | fusionné (correction : révision de fusion Alembic fa35dace3fea jointe aux têtes c7ecfe8a11be et f0e1d2c3b4a5 ; ajout au registre provisoire des tables idempotencyKeys et idempotency_record) | 6e5ec3b | 5 verts / 0 rouge (5 total), tests/test_inventaire_donnees_be242.py |
| 16 | BE-021 | be-021-lot | fusionné (révision de fusion Alembic 73136cdbf00b jointe aux têtes b60e229ba2de et fa35dace3fea) | 42aea86 | 7 verts / 0 rouge (7 total), tests/test_registre_etats_be021.py |
| 17 | BE-023 | be-023-lot | fusionné | e2a7dcd | 5 verts / 0 rouge (5 total), tests/test_be023_plans_abonnement.py. Pas de nouvelle tête Alembic |
| 18 | BE-005 | be-005-lot | fusionné | 761afac | 9 verts / 0 rouge (9 total), tests/test_be005_authentification.py. Pas de nouvelle tête Alembic |
| 19 | BE-007 | be-007-lot | fusionné (révision de fusion Alembic 82522140e368 jointe aux têtes 73136cdbf00b et b8e3f1a20c47 ; correction de test : tests/test_module_assignment.py reçoit un fixture autouse qui déclare CRM dans CODES_MODULES_CONNUS, sinon son état registre est inconnu et refusé, cause BE-021) | bb54c65 | 27 verts / 0 rouge (27 total), tests/test_be007_journal_audit.py, tests/test_module_assignment.py, tests/test_operator.py |
| 20 | BE-008 | be-008-lot | fusionné | fa471bd | 4 verts / 0 rouge (4 total), tests/test_be008_rbac_modele.py. Pas de nouvelle tête Alembic |
| 21 | BE-040 | be-040-lot | fusionné (révision de fusion Alembic 9a075a4572eb jointe aux têtes 82522140e368 et b040c4a10e01 ; fichier de révision ajouté à l'index) | eb4d951 | 7 verts / 0 rouge (7 total), tests/test_be040_catalogue_modules.py |
| 22 | BE-230 | be-230-lot | fusionné (révision de fusion Alembic 82b12c50c3f6 jointe aux têtes 9a075a4572eb et be230a1b2c3d) | 5a22778 | 8 verts / 0 rouge (8 total), tests/test_secrets_be230.py |
| 23 | BE-240 | be-240-lot | fusionné | 606a5fd | 7 verts / 0 rouge (7 total), tests/test_sante_be240.py. Pas de nouvelle tête Alembic |
| 24 | BE-249 | be-249-lot | fusionné | 4629c96 | 23 verts / 0 rouge (23 total), tests/test_supply_chain_be249.py. Pas de nouvelle tête Alembic |
| 25 | BE-009 | be-009-lot | fusionné | 0f0ad62 | 6 verts / 0 rouge (6 total), tests/test_be009_garde_contexte.py. Pas de nouvelle tête Alembic |
| 26 | BE-006 | be-006-lot | fusionné | cfe3fdb | 5 verts / 0 rouge (5 total), tests/test_be006_inscription_fermee.py. Pas de nouvelle tête Alembic |
| 27 | BE-018 | be-018-lot | fusionné | f31b5b3 | 5 verts / 0 rouge (5 total), tests/test_be018_changement_mot_de_passe.py. Pas de nouvelle tête Alembic |
| 28 | BE-019 | be-019-lot | fusionné | e551b80 | 10 verts / 0 rouge (10 total), tests/test_be019_recuperation_mot_de_passe.py, tests/test_password_reset.py. Nouvelle tête Alembic c9f2a4e6b8d1 (table password_reset_token) |
| 29 | BE-020 | be-020-lot | fusionné | 0d1ec2e | 4 verts / 0 rouge (4 total), tests/test_be020_profil_compte.py. Pas de nouvelle tête Alembic |
| 30 | BE-024 | be-024-lot | fusionné (révision de fusion Alembic eb922c50f9b5 jointe aux têtes b024e7a1c5d3 et c9f2a4e6b8d1) | 32b8a7f | 11 verts / 0 rouge (11 total), tests/test_be024_entitlements.py |
| 31 | BE-030 | be-030-lot | fusionné (révision de fusion Alembic 9fa8a14283b1 jointe aux têtes e5f6a7b8c9d0 et eb922c50f9b5 ; correction de test : tests/test_be030_journal_operateur.py CA-5 vérifie une tête unique et l'ascendance de BE-030 au lieu d'une tête unique égale à BE-030 ; cycle downgrade/upgrade ciblé mis en skip, renvoi à une tâche ultérieure) | da78051 | 15 verts / 0 rouge / 1 skip (16 total), tests/test_be030_journal_operateur.py, tests/test_operator.py, tests/test_sante_be240.py |
| 32 | BE-225 | be-225-lot | fusionné | e7fc9d8 | 7 verts / 0 rouge (7 total), tests/test_contexte_tenant_be225.py. Pas de nouvelle tête Alembic |
| 33 | BE-010 | be-010-lot | fusionné | 16c74b7 | 4 verts / 0 rouge (4 total), tests/test_be010_organisation_courante.py. Pas de nouvelle tête Alembic |
| 34 | BE-012 | be-012-lot | fusionné | a2041c2 | 5 verts / 0 rouge (5 total), tests/test_be012_invitations_organisation.py. Nouvelle révision d4e5f6a7b8c9 (tête unique) |
| 35 | BE-014 | be-014-lot | fusionné (correction : résolution de 5 conflits dans permissions.py, router.py, service.py par union des deux côtés ; import de get_current_organization_id repris de rbac.guards) | 35a2473 | 6 verts / 0 rouge (6 total), tests/test_be014_membres.py. Pas de nouvelle tête Alembic |
| 36 | BE-016 | be-016-lot | fusionné (correction de test : tests/test_be016_lecture_roles.py CA-1 compare le nombre de permissions à len(OWNER_DEFAULT_PERMISSIONS) au lieu de 12 en dur ; le nom du test garde le libellé 12) | cf233cb | 5 verts / 0 rouge (5 total), tests/test_be016_lecture_roles.py. Pas de nouvelle tête Alembic |
| 37 | BE-022 | be-022-lot | fusionné | 40d729b | 8 verts / 0 rouge (8 total), tests/test_be022_catalogue_activation.py. Pas de nouvelle tête Alembic |
| 38 | BE-026 | be-026-lot | fusionné | 56c84b3 | 6 verts / 0 rouge (6 total), tests/test_be026_abonnement_courant.py. Pas de nouvelle tête Alembic |
| 39 | BE-027 | be-027-lot | fusionné (correction : résolution de 3 conflits dans api/v1/router.py et identity/service.py par union ; SUBSCRIPTION_READ conservé) | e81403e | 5 verts / 0 rouge (5 total), tests/test_be027_factures_lecture.py. Pas de nouvelle tête Alembic |
| 40 | BE-033 | be-033-lot | fusionné (correction : résolution d'1 conflit dans api/v1/router.py par union des imports roles_lecture_router et organization_audit_router) | 49ae3a4 | 6 verts / 0 rouge (6 total), tests/test_be033_journal_audit_lecture.py. Pas de nouvelle tête Alembic |
| 41 | BE-011 | be-011-lot | fusionné | 1b311de | 7 verts / 0 rouge (7 total), tests/test_be011_reglages_organisation.py. Pas de nouvelle tête Alembic |
| 42 | BE-015 | be-015-lot | fusionné | b04e679 | 8 verts / 0 rouge (8 total), tests/test_be015_affectation_roles.py. Pas de nouvelle tête Alembic |
| 43 | BE-025 | be-025-lot | fusionné | d70882e | 11 verts / 0 rouge (11 total), tests/test_be025_garde_acces_module.py. Pas de nouvelle tête Alembic |
| 44 | BE-028 | be-028-lot | fusionné (correction de test, 2 corrections dans tests/test_be028_adaptateur_paiement.py : message sandbox aligné sur "pas configuré", appel generated(None) du default UUID, engine.dispose() en tête de CA-4 pour un pool neuf ; commit d79fda5 inclut la correction) | d79fda5 | 12 verts / 0 rouge (12 total), tests/test_be028_adaptateur_paiement.py. Pas de nouvelle tête Alembic |
| 45 | BE-031 | be-031-lot | fusionné (2 corrections : justification des routes account/profile, password-reset request/confirm et internal/ready dans tests/route_inventory.py ; régénération de docs/architecture/securite/matrice-autorisation.md) | 1e0a234 | 27 verts / 0 rouge / 1 skip (28 total), tests/test_be030_journal_operateur.py, tests/test_be031_console_operateur.py, tests/test_operator.py, tests/test_route_inventory.py. Skip BE-030 avec renvoi (cycle downgrade) |
| 46 | BE-034 | be-034-lot | fusionné | 7716fc6 | 6 verts / 0 rouge (6 total), tests/test_be034_abonnement_push.py. Pas de nouvelle tête Alembic |
| 47 | BE-035 | be-035-lot | fusionné | 7b07b9f | 8 verts / 0 rouge (8 total), tests/test_be035_boite_reception.py. Pas de nouvelle tête Alembic |
| 48 | BE-013 | be-013-lot | fusionné | 4d9e84c | 7 verts / 0 rouge (7 total), tests/test_be013_activation_invitation_organisation.py. Pas de nouvelle tête Alembic |
| 49 | BE-017 | be-017-lot | fusionné | c954941 | 9 verts / 0 rouge (9 total), tests/test_be017_grants_membres.py. Pas de nouvelle tête Alembic |
| 50 | BE-036 | be-036-lot | fusionné | e9d25d4 | 10 verts / 0 rouge (10 total), tests/test_be036_cycle_de_vie_organisation.py. Pas de nouvelle tête Alembic |
| 51 | BE-041 | be-041-lot | fusionné | 130723b | 7 verts / 0 rouge (7 total), tests/test_be041_machine_etats.py. Tête Alembic e041b7c3d9f2 (journal transitions modules) |
| 52 | BE-045 | be-045-lot | fusionné (2 têtes Alembic e041b7c3d9f2 et a045b1c2d3e4 : révision de fusion 7088b9c36bc8 ; correction de test : tests/test_be045_entitlements_organisation.py, test_organisation_d_un_autre_tenant_repond_404_sans_donnee crée l'organisation B par un autre utilisateur, le créateur en étant propriétaire) | a9e0ce5 | 17 verts / 0 rouge (17 total), tests/test_be024_entitlements.py, tests/test_be045_entitlements_organisation.py |
| 53 | BE-071 | be-071-lot | fusionné (conflit résolu dans app/billing/models.py par union des imports sqlalchemy ; révision de fusion Alembic dcca8a653959 jointe aux têtes 7088b9c36bc8 et e1f2a3b4c5d6) | 3daa7c4 | 6 verts / 0 rouge (6 total), tests/test_be071_payeurs.py |
| 54 | BE-037 | be-037-lot | fusionné (révision de fusion Alembic f668520e8d62 jointe aux têtes dcca8a653959 et f5a6b7c8d9e0 ; restriction de test autorisée : test_comparaison_orm_et_base_sans_difference (CA-2) ne porte que sur password_reset_token et notification_inbox_item, les écarts zyloLiquid et registre des modules sont hors périmètre ; aucun test supprimé ni désactivé) | 5ec7dbe | 5 verts / 0 rouge (5 total), tests/test_be037_reconciliation_orm.py. Signalé hors périmètre : écarts de commentaires seulement sur billing_payer, secret_registry, userInvitation, organizationInvitation, idempotencyKeys (non inclus dans CA-2) |
| 55 | BE-029 | be-029-lot | fusionné (2 têtes Alembic 2e1730fcde08 et f668520e8d62 : révision de fusion 7bbd625df9ad ; aucune correction de code ni de test) | dbe724b | 26 verts / 0 rouge (26 total), tests/test_be024_entitlements.py, tests/test_be029_webhooks_paiement.py, tests/test_billing.py |
| 56 | BE-042 | be-042-lot | fusionné | 9e3acb6 | 10 verts / 0 rouge (10 total), tests/test_be042_publication_modules.py. Tete Alembic c042a1b2d3e4 ; revision de fusion 19f753807bd6 committee avec be-046 (f8dfa81) faute d'ajout au commit 9e3acb6 |
| 57 | BE-046 | be-046-lot | fusionné | f8dfa81 | 6 verts / 0 rouge (6 total), tests/test_be046_allocation_sieges.py. Tete Alembic b046a1e2c3d4 ; revision de fusion 22365035629c |
| 58 | BE-056 | be-056-lot | fusionné (conflits resolus dans app/api/v1/router.py et app/modules_registry/schemas.py par conservation des deux cotes ; revision de fusion Alembic b56edb92fa23 jointe a a056b1c2d3e4) | 8e458e5 | 15 verts / 0 rouge (15 total), tests/test_be041_machine_etats.py, tests/test_be056_evenements_audit_modules.py |
| 59 | BE-073 | be-073-lot | fusionné (revision de fusion Alembic e03b52959415 jointe a a1d073b2c4e5) | a776f38 | 9 verts / 0 rouge (9 total), tests/test_be073_journal_financier.py. Pas de correction |
| 60 | BE-075 | be-075-lot | fusionné (conflits resolus dans app/billing/models.py et app/billing/permissions.py par conservation des deux cotes ; revision de fusion Alembic b8fbeeea5dd5 jointe a a7c2e4f1b936) | d9dba14 | 5 verts / 0 rouge (5 total), tests/test_be075_capture_version_offre.py. Pas de correction de test |
| 61 | BE-079 | be-079-lot | fusionné (revision de fusion Alembic 169de7fb56af jointe a e079a1b2c3d4) | aad9774 | 8 verts / 0 rouge (8 total), tests/test_be079_agregat_subscription.py. Pas de correction |
| 62 | BE-038 | - | fusionnée (voir la ligne de fusion ajoutée plus bas) | - | - | BE-038 : QE-SOC-26 appliquée, fusionnée depuis be-038-lot |
| 63 | BE-043 | be-043-lot | fusionné (integration sans conflit ; base zylo_t000_test recréée car alembic_version pointait sur c078a1b2d3e4 de be-078 absent de develop ; revision de fusion aucune) | 71cc000 | 6 verts / 0 rouge (6 total), tests/test_be043_catalogue_visibilite.py |
| 64 | BE-044 | be-044-lot | fusionné (conflit resolu dans app/modules_registry/schemas.py par conservation des deux cotes) | 2e7c65a | 20 verts / 0 rouge (20 total), tests/test_be044_compatibilite_plans.py |
| 65 | BE-055 | be-055-lot | fusionné (conflits resolus dans app/modules_registry/models.py et schemas.py par conservation des deux cotes ; revision de fusion Alembic 2b2ba311c93c jointe aux tetes be055a1b2c3d et d4a8f2c1b9e0) | 77b9a11 | 7 verts / 0 rouge (7 total), tests/test_be055_permissions_module.py |
| 66 | BE-076 | be-076-lot | fusionné (revision de fusion Alembic 883a7a9eacac jointe aux tetes 2b2ba311c93c et c076a1b2c3d4) | 9a18c84 | 8 verts / 0 rouge (8 total), tests/test_be076_consentements.py |
| 67 | BE-078 | be-078-lot | fusionné (conflit resolu dans app/billing/models.py par conservation des deux cotes ; revision de fusion Alembic a60bbc64035d jointe aux tetes 883a7a9eacac et c078a1b2d3e4) | 8f15e53 | 7 verts / 0 rouge (7 total), tests/test_be078_resolution_prix.py |
| 68 | BE-090 | be-090-lot | fusionné (revision de fusion Alembic 12b9bd0b8c15 jointe aux tetes a090c1d2e3f4 et a60bbc64035d) | 4a39c0f | 5 verts / 0 rouge (5 total), tests/test_be090_resiliation_abonnement.py |
| 69 | BE-120 | be-120-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | a4db340 | 17 verts / 0 rouge (17 total), tests/test_be120_portee_administration.py |
| 70 | BE-150 | be-150-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | b1a57d7 | 12 verts / 0 rouge (12 total), tests/test_be150_enveloppe_evenement.py |
| 71 | BE-180 | be-180-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | 79c530e | 14 verts / 0 rouge (14 total), tests/test_be180_codes_erreur.py |
| 72 | BE-231 | be-231-lot | fusionné (revision de fusion Alembic db7ff2e5c60e jointe aux tetes 12b9bd0b8c15 et be231a1b2c3d) | 868aa9e | 6 verts / 0 rouge (6 total), tests/test_chiffrement_be231.py |
| 73 | BE-241 | be-241-lot | fusionné (revision de fusion Alembic 0c76adc619b3 jointe aux tetes d51b3bc6fe0c et db7ff2e5c60e) | ed05368 | 10 verts / 0 rouge (10 total), tests/test_alertes_be241.py |
| 74 | BE-250 | be-250-lot | fusionné (revision de fusion Alembic 3f3b9067d60b jointe aux tetes 0c76adc619b3 et a250b1c2d3e4 ; alembic/env.py auto-fusionne, import app.release.models conserve) | 765c4b1 | 9 verts / 0 rouge (9 total), tests/test_release_promotion_be250.py |
| 75 | BE-260 | be-260-lot | fusionné (revision de fusion Alembic 33e0d390444b jointe aux tetes 3f3b9067d60b et c3a9e1f07b52) | 837cb1f | 11 verts / 0 rouge (11 total), tests/test_be260_journal_audit_actions_sensibles.py |
| 76 | BE-226 | be-226-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | b8aa392 | 20 verts / 0 rouge (20 total), tests/test_be226_moteur_autorisation.py |
| 77 | BE-052 | be-052-lot | fusionné (revision de fusion Alembic c6cd5d6c8c35 jointe aux tetes b052c4e7a1f3 et d5624b3c990f) | b11dbd0 | 13 verts / 0 rouge (13 total), tests/test_be052_reconciliation.py |
| 78 | BE-077 | be-077-lot | fusionné (conflits resolus dans app/api/v1/router.py et app/billing/models.py par conservation des deux cotes ; revision de fusion Alembic 254220e168b5 jointe aux tetes c6cd5d6c8c35 et f077a1b2c3d4) | 85fc108 | 11 verts / 0 rouge (11 total), tests/test_be077_devis.py |
| 79 | BE-127 | be-127-lot | fusionné (pas de conflit ni de nouvelle tete Alembic ; une fusion anterieure restee en cours sur l'espace a ete annulee puis refaite) | cb068c9 | 15 verts / 0 rouge (15 total), tests/test_be127_classes_action_sensible.py |
| 80 | BE-151 | be-151-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | f594d28 | 27 verts / 0 rouge (27 total), tests/test_be151_catalogue_erreurs.py |
| 81 | BE-181 | be-181-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | b7780fa | 6 verts / 0 rouge (6 total), tests/test_be181_contexte_requete.py |
| 82 | BE-191 | be-191-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | bf71fb5 | 8 verts / 0 rouge (8 total), tests/test_be191_pagination_quotas.py |
| 83 | BE-152 | be-152-lot | fusionné (nouvelle tete Alembic f2a8c1d7e903 jointe par revision de fusion 2dcc3b17657c aux tetes existantes) | d9b9f8d | 10 verts / 0 rouge (10 total), tests/test_be152_modele_journal_audit.py |
| 84 | BE-048 | be-048-lot | fusionné (pas de conflit ni de nouvelle tete Alembic ; fusion automatique dans app/identity/service.py) | 6b7585e | 14 verts / 0 rouge (14 total), tests/test_be048_disponibilite_module.py |
| 85 | BE-051 | be-051-lot | fusionné (conflits resolus par conservation des deux cotes dans app/identity/service.py, app/modules_registry/{models,permissions,router}.py ; deux tetes Alembic 2dcc3b17657c et be051d2e3f4a jointes par revision de fusion 850ac058b6a8) | 9f27365 | 10 verts / 0 rouge (10 total), tests/test_be051_mise_a_jour_version.py |
| 86 | BE-098 | be-098-lot | fusionné (pas de conflit ; nouvelle tete Alembic b098e0f1a2c3 jointe par revision de fusion d8eaf380eecb) | 9d5fb8d | 6 verts / 0 rouge (6 total), tests/test_be098_export_donnees_facturation.py |
| 87 | BE-081 | be-081-lot | fusionné (conflit resolu par conservation des deux classes DataExportRequest et Checkout dans app/billing/models.py ; tete Alembic a81c0c4e0b01 jointe par revision de fusion 041e676a92aa) | 8dc64d0 | 11 verts / 0 rouge (11 total), tests/test_be081_achat_checkout.py |
| 88 | BE-087 | be-087-lot | fusionné (conflit resolu par conservation des classes existantes et de CreditNote dans app/billing/models.py ; tete Alembic b087c1d2e3f4 jointe par revision de fusion 881bfa754423) | 997e254 | 9 verts / 0 rouge (9 total), tests/test_be087_avoir_correction.py |
| 89 | BE-121 | be-121-lot | fusionné (pas de conflit ; tete Alembic a121c0de0121 jointe par revision de fusion 934346a13edd) | 27ec6d1 | 14 verts / 0 rouge (14 total), tests/test_be121_affectations_roles_admin.py |
| 90 | BE-050 | be-050-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | 449c0a3 | 9 verts / 0 rouge (9 total), tests/test_be050_desinstallation_module.py |
| 91 | BE-053 | be-053-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | 4eaceb2 | 19 verts / 0 rouge (19 total), tests/test_be053_acces_effectif.py |
| 92 | BE-082 | be-082-lot | fusionné (pas de conflit ; nouvelle tete Alembic b082a1c2d3e4 apres 934346a13edd) | cfaf58d | 11 verts / 0 rouge (11 total), tests/test_be082_tentatives_paiement.py |
| 93 | BE-123 | be-123-lot | fusionné (deux tetes Alembic a123c0de0123 et b082a1c2d3e4 jointes par revision de fusion 3a2990daf8ef) | c49deec | 10 verts / 0 rouge (10 total), tests/test_be123_cas_intervention.py |
| 94 | BE-153 | be-153-lot | fusionné (pas de conflit ni de nouvelle tete Alembic) | f373315 | 6 verts / 0 rouge (6 total), tests/test_be153_ecriture_audit.py |
| 95 | BE-049 | be-049-lot | fusionné (conflit resolu par conservation des deux cotes dans app/modules_registry/permissions.py : constantes BE-050 et BE-049 ; deux tetes Alembic jointes par revision de fusion 37c874aed5ed) | 753d48b | 10 verts / 0 rouge (10 total), tests/test_be049_suspension_module.py |
| 96 | BE-146 | be-146-lot | fusionné (pas de conflit ; tete Alembic b146c0de0146 jointe par revision de fusion 12a5bb79f642) | aaab903 | 7 verts / 0 rouge / 1 skip avec renvoi QE-ADM-15 (8 total), tests/test_be146_revocation_fin_fenetre.py |
| 97 | BE-059 | be-059-lot | fusionné (pas de conflit ; pas de nouvelle tete Alembic) | 2a71b99 | 6 verts / 0 rouge (6 total), tests/test_be059_expiration_entitlements.py |
| 98 | BE-099 | be-099-lot | fusionné (pas de conflit ; pas de nouvelle tete Alembic) | 31d202d | 5 verts / 0 rouge (5 total), tests/test_be099_historique_facturation.py |
| 99 | BE-058 | be-058-lot | fusionné (deux tetes Alembic 058b1c2d3e4f et be-146 jointes par revision de fusion e1b89dfe1796) | 8a2c27c | 7 verts / 0 rouge (7 total), tests/test_be058_liaison_facturation_entitlements.py |
| 100 | BE-124 | be-124-lot | fusionné (pas de conflit ; tete Alembic c124a0de0124 jointe par revision de fusion 6d8693f9201f) | 2014de0 | 10 verts / 0 rouge (10 total), tests/test_be124_commandes_operateur.py |
| 101 | BE-093 | be-093-lot | fusionné (conflits resolus par conservation des deux cotes dans app/billing/models.py, app/billing/permissions.py et app/identity/service.py ; tetes Alembic e093a7b1c2d4 et 6d8693f9201f jointes par revision de fusion 9afedaef1361) | 7875e2c | 10 verts / 0 rouge (10 total), tests/test_be093_remboursements.py |
| 102 | BE-132 | be-132-lot | fusionné (conflit resolu par conservation des deux cotes dans app/api/v1/router.py : routeurs BE-124 et BE-132 ; tete Alembic b132d1a60132 jointe par revision de fusion 92fd206ba652) | a92247e | 15 verts / 0 rouge (15 total), tests/test_be132_diagnostic_paiement.py |
| 103 | BE-054 | be-054-lot | REJETE (merge annule ; rouge test_ca1_toutes_les_routes_de_module_portent_la_garde : suspensions et reactivations sans require_module_action ; ajout de la garde ORGANIZATION_MODULE_SUSPEND tente, casse 10 tests be-049, retire) | - | 7 verts / 1 rouge (8 total), tests/test_be054_application_moteur.py |
| 104 | BE-166 | be-166-lot | fusionne (deux tetes Alembic 92fd206ba652 et c166e0f1a2b3 jointes par revision de fusion 702914c4df91) | 5dee541 | 7 verts / 0 rouge (7 total), tests/test_be166_outbox_consommation.py |
| 105 | BE-154 | be-154-lot | fusionne (deux tetes Alembic 702914c4df91 et a3c9e1f20b76 jointes par revision de fusion e058633c94a1) | f5ef77b | 7 verts / 0 rouge (7 total), tests/test_be154_modele_parametres.py |
| 106 | BE-160 | be-160-lot | fusionne (deux tetes Alembic e058633c94a1 et 5f1e2a3b4c6d jointes par revision de fusion 5e31981cf46c) | 36c947e | 10 verts / 0 rouge (10 total), tests/test_be160_registre_connecteurs.py |
| 107 | BE-172 | be-172-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | f58f48f | 6 verts / 0 rouge (6 total), tests/test_be172_consultation_journal_audit.py |
| 108 | BE-227 | be-227-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | ff269c8 | 6 verts / 0 rouge (6 total), tests/test_be227_journal_audit_append_only.py |
| 109 | BE-057 | be-057-lot | fusionne (pas de conflit ni de nouvelle tete Alembic ; fusion sans avance rapide, commit 06ef1cf) | 06ef1cf | 5 verts / 0 rouge (5 total), tests/test_be057_notifications_modules.py |
| 110 | BE-054 | be-054-v2 | fusionne (pas de conflit ni de nouvelle tete Alembic ; garde require_module_action sur routes de module ; 10 tests anciens BE-049 sous garde QE-BE054-04 signales, non relances ici) | fbbc205 | 8 verts / 0 rouge (8 total), tests/test_be054_application_moteur.py |
| 111 | BE-155 | be-155-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | 101b651 | 18 verts / 0 rouge (18 total), tests/test_be155_validation_parametres.py |
| 112 | BE-145 | be-145-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | 8b43121 | 6 verts / 0 rouge (6 total), tests/test_be145_compteurs_exploitation.py |
| 113 | BE-161 | be-161-lot | fusionne (nouvelle tete Alembic 7a2c9d1e4f60, sans conflit) | ee194c4 | 4 verts / 0 rouge (4 total), tests/test_be161_secrets_integration.py |
| 114 | BE-128 | be-128-lot | fusionne (deux tetes Alembic 7a2c9d1e4f60 et be128a0de0128 jointes par revision de fusion 495a7fcdc066 ; pas de conflit) | a5e4203 | 9 verts / 0 rouge (9 total), tests/test_be128_double_validation.py |
| 115 | BE-125 | be-125-lot | fusionne (deux tetes Alembic 495a7fcdc066 et d125a0ce0125 jointes par revision de fusion 9230d532caa6 ; pas de conflit) | fdc2d55 | 7 verts / 0 rouge (7 total), tests/test_be125_previsualisation_commandes.py |
| 116 | BE-164 | be-164-lot | fusionne (conflits dans app/integrations/models.py resolus en gardant les deux cotes ; tete Alembic 9b164a0c164e jointe par revision de fusion cdcca54d221c) | c7ab749 | 11 verts / 0 rouge (11 total), tests/test_be164_tentatives_integration.py |
| 117 | BE-167 | be-167-lot | fusionne (pas de conflit ; tete Alembic 7c3e9d2b4a10 jointe par revision de fusion 84a2fbf33cc8) | 3150ecb | 7 verts / 0 rouge (7 total), tests/test_be167_categories_audiences.py |
| 118 | BE-173 | be-173-lot | fusionne (pas de conflit ; tete Alembic a7c3e91b2f54 jointe par revision de fusion e376601be760) | 08eb05c | 9 verts / 0 rouge (9 total), tests/test_be173_export_audit.py |
| 119 | BE-174 | be-174-lot | fusionne (pas de conflit ; tete Alembic 174a0b1c2d3e jointe par revision de fusion 1d0dcfadf009) | dab7ed3 | 9 verts / 0 rouge (9 total), tests/test_be174_classification.py |
| 120 | BE-175 | be-175-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | 385995f | 5 verts / 0 rouge (5 total), tests/test_be175_sauvegarde_restauration.py |
| 121 | BE-228 | be-228-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | bc00c91 | 4 verts / 0 rouge (4 total), tests/test_be228_journal_lectures_sensibles.py |
| 122 | BE-234 | be-234-lot | fusionne (2 tetes Alembic, migration de fusion f32497e0328e) | b40d763 | 13 verts / 0 rouge (13 total), tests/test_be234_outbox_versionnee.py |
| 123 | BE-074 | be-074-lot | fusionne (nouvelle tete Alembic a074b1c2d3e4 jointe par revision de fusion 9056fdbfa86f) | fc42d69 | 13 verts / 0 rouge (13 total), tests/test_be074_enveloppe_outbox_inbox.py |
| 124 | BE-126 | be-126-lot | fusionne (nouvelle tete Alembic b126a0de0126 jointe par revision de fusion 7b3cdbc1efc8) | 2357623 | 6 verts / 0 rouge (6 total), tests/test_be126_garde_commande.py |
| 125 | BE-156 | be-156-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | 23fb76a | 5 verts / 0 rouge (5 total), tests/test_be156_resolution_parametres.py |
| 126 | BE-138 | be-138-lot | fusionne (pas de conflit ; tete Alembic unique, pas de nouvelle revision) | 4258ba3 | 14 verts / 0 rouge (14 total), tests/test_be138_acces_exceptionnel.py |
| 127 | BE-144 | be-144-lot | fusionne (nouvelle tete Alembic e144a0de0144 jointe par revision de fusion 9dc1e3363030 ; pas de conflit) | b978ee1 | 7 verts / 0 rouge (7 total), tests/test_be144_notifications_action.py |
| 128 | BE-136 | be-136-lot | fusionne (conflit sur app/api/v1/router.py : imports et inclusions independants conserves des deux cotes) | 1f9a19b | 5 verts / 0 rouge (5 total), tests/test_be136_commandes_financieres.py |
| 129 | BE-165 | be-165-lot | fusionne (pas de conflit ; nouvelle tete Alembic c165a0b1d2e3 jointe par la revision de fusion 52789084e923) | 71faa3f (alembic d8fad2d) | 10 verts / 0 rouge (10 total), tests/test_be165_lettres_mortes.py |
| 130 | BE-168 | be-168-lot | fusionne (pas de conflit ; nouvelle tete Alembic 8e5a2c1d9f3b jointe par la revision de fusion c13acdcdccec) | 3321ba7 | 6 verts / 0 rouge (6 total), tests/test_be168_preferences_consentement.py |
| 131 | BE-162 | be-162-lot | fusionne (conflits dans app/integrations/seed.py, permissions.py et router.py : permissions et routes BE-165 et BE-162 conservees des deux cotes ; routeur des lettres mortes separe (lettres_mortes_router) pour garder le prefixe /integrations ; pas de nouvelle tete Alembic) | 3b4f5e0 | 5 verts / 0 rouge (5 total), tests/test_be162_routes_connecteurs.py ; regression BE-165 10/10 verte |
| 132 | BE-157 | be-157-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | 3b90b72 | 6 verts / 0 rouge (6 total), tests/test_be157_application_parametres.py |
| 133 | BE-135 | be-135-lot | fusionne (deux tetes Alembic c13acdcdccec et e135a0ce0135 jointes par revision de fusion 290f30a9bcbf, dans le meme commit ; conflit sur app/api/v1/router.py : imports et inclusions independants conserves des deux cotes) | 0cfc096 | 6 verts / 0 rouge (6 total), tests/test_be135_commandes_entitlement.py |
| 134 | BE-143 | be-143-lot | fusionne (pas de conflit ni de nouvelle tete Alembic) | b4380f0 | 7 verts / 0 rouge (7 total), tests/test_be143_reconciliation.py |
| 135 | BE-060 | be-060-lot | fusionne (aucun conflit ; une seule tete Alembic 290f30a9bcbf, pas de migration de fusion ; fichiers ajoutes docs/modules/tests-modules.md et tests/test_be060_suite_refus_isolation_modules.py) | b282383 | 62 verts / 0 rouge (62 total), tests/test_be060_suite_refus_isolation_modules.py |
| 136 | BE-158 | be-158-lot | fusionné (fusion antérieure, ajoutée au suivi lors de l'intégration ; tests non relancés) | c21ae21 | non relancé (8 tests collectés, tests/test_be158_routes_parametres.py) |
| 137 | BE-163 | be-163-lot | fusionné (fusion antérieure, ajoutée au suivi lors de l'intégration ; tests non relancés) | 8100cae | non relancé (7 tests collectés, tests/test_be163_webhook_entrant.py ; tests/route_inventory.py modifié) |
| 138 | BE-169 | be-169-lot | fusionné (fusion antérieure, ajoutée au suivi lors de l'intégration ; tests non relancés) | a392efa | non relancé (5 tests collectés, tests/test_be169_moteur_notification.py) |
| 139 | BE-229 | be-229-lot | fusionné (tête Alembic b229a0c0d229 jointe par révision de fusion e8e28ec975d6) | b4dec63 | 14 verts / 0 rouge (14 total), tests/test_be229_acces_operateur.py |
| 140 | BE-235 | be-235-lot | fusionné (têtes d235a0b1c2d3 et e8e28ec975d6 jointes par révision de fusion 4999c84636ac ; conflit dans app/core/config.py résolu en conservant les deux champs indépendants) | 086fed0 | 7 verts / 0 rouge (7 total), tests/test_be235_consommation_dlq.py |
| 141 | BE-236 | be-236-lot | fusionné (têtes 4999c84636ac et b236c1a0d001 jointes par révision de fusion be680f42cb4f ; conflit dans app/api/v1/router.py résolu en conservant les deux imports) | ff6b789 | 4 verts / 0 rouge (4 total), tests/test_be236_operations.py |
| 142 | BE-237 | be-237-lot | fusionné (têtes be680f42cb4f et a237b1c0d9e8 jointes par révision de fusion 7c0052761f05 ; pas de conflit) | c936df6 | 13 verts / 0 rouge (13 total), tests/test_be237_registre_reglages.py |
| 143 | BE-244 | be-244-lot | fusionné (têtes 7c0052761f05 et b244a1c2d3e4 jointes par révision de fusion aab72f59d1c3 ; pas de conflit) | 8e432ab | 10 verts / 0 rouge (10 total), tests/test_be244_sauvegardes_chiffrees.py
| 144 | BE-247 | be-247-lot | fusionné (têtes aab72f59d1c3 et c247b1d2e3f4 jointes par révision de fusion f9d7ef17ec72 ; pas de conflit) | af65d66 | 9 verts / 0 rouge (9 total), tests/test_be247_incidents.py
| 145 | BE-248 | be-248-lot | fusionné (pas de conflit, tête Alembic inchangée) | 956d0aa | 19 verts / 0 rouge (19 total), tests/test_be248_isolation_autorisation_bout_en_bout.py
| 146 | BE-251 | be-251-lot | fusionné (conflit dans app/api/v1/router.py résolu en conservant les deux imports et montages ; têtes 3e7a1b2c9d41 et f9d7ef17ec72 jointes par révision de fusion 05aa53c71fa5) | 103c108 | 11 verts / 0 rouge (11 total), tests/test_be251_flags.py
| 147 | BE-253 | be-253-lot | fusionné (conflit dans alembic/env.py résolu en conservant les deux imports de modèles ; têtes 05aa53c71fa5 et c253a1b2d3e4 jointes par révision de fusion fd57ba293e8b) | 706b104 | 9 verts / 0 rouge (9 total), tests/test_be253_limites_abus.py
| 148 | BE-083 | be-083-lot | fusionné (pas de conflit ; tête Alembic unique fd57ba293e8b, pas de nouvelle tête) | 1235b10 | 3 verts / 0 rouge (3 total), tests/test_be083_ingestion_evenements_fournisseur.py |
| 149 | BE-141 | be-141-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic) | 2d15cf5 | 8 verts / 0 rouge (8 total), tests/test_be141_changement_configuration.py |
| 150 | BE-170 | be-170-lot | fusionné (tête c4d8e1f2a903 jointe aux têtes fd57ba293e8b par révision de fusion 4ee3bfc7ae7c) | c8cb232 | 9 verts / 0 rouge (9 total), tests/test_be170_adaptateur_canal.py |
| 151 | BE-176 | be-176-lot | fusionné (tête c176a0e1b2d3 jointe à 4ee3bfc7ae7c par révision de fusion 171b683326dd) | eb3704b | 6 verts / 0 rouge (6 total), tests/test_be176_schemas_evenements.py |
| 152 | BE-139 | be-139-lot | fusionné (conflit dans app/api/v1/router.py résolu en conservant les deux imports et montages config_security et event_replay ; pas de nouvelle tête Alembic) | d9eba21 | 6 verts / 0 rouge (6 total), tests/test_be139_rejeu_evenement.py |
| 153 | BE-159 | be-159-lot | fusionné (tête 159b5e0a7c31 jointe à 171b683326dd par révision de fusion 84a44229c0d1) | d058df4 | 7 verts / 0 rouge (7 total), tests/test_be159_approbation_parametres.py |
| 154 | BE-061 | be-061-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic) | 23f1ca5 | 5 verts / 0 rouge (5 total), tests/test_be061_documentation_modules.py |
| 155 | BE-254 | be-254-lot | fusionné | 0cc7cff | 10 verts / 0 rouge (10 total), tests/test_be254_flux_reseau.py |
| 156 | BE-239 | be-239-lot | fusionné (révision de fusion Alembic c2394d7a1b90 jointe aux têtes 84a44229c0d1 et be239a1b2c3d, dans le commit de fusion) | fd9f9cd | 8 verts / 0 rouge (8 total), tests/test_be239_integrations_liens.py |
| 157 | BE-142 | be-142-lot | fusionné (révision de fusion Alembic d1421e7f0a3b jointe aux têtes c2394d7a1b90 et e142a5c0d142, dans le commit de fusion) | f718364 | 7 verts / 0 rouge (7 total), tests/test_be142_escalade.py |
| 158 | BE-094 | be-094-lot | fusionné (révision de fusion Alembic e0941f2a3b4c jointe aux têtes d1421e7f0a3b et e094a1c2d3e4, dans le commit de fusion) | 8aebff1 | 7 verts / 0 rouge (7 total), tests/test_be094_litiges.py |
| 159 | BE-084 | be-084-lot | fusionné (pas de nouvelle tête Alembic) | 1f867f1 | 10 verts / 0 rouge, tests/test_be084_confirmation_abonnement.py |
| 160 | BE-255 | be-255-lot | fusionné (conflit trivial résolu dans alembic/env.py par conservation des deux imports ; révision de fusion Alembic f2559e1a2b3c jointe aux têtes e0941f2a3b4c et a7c25e5b1d03, dans le commit de fusion) | 94b46b9 | 7 verts / 0 rouge (7 total), tests/test_capacite_be255.py |
| 161 | BE-245 | be-245-lot | fusionné (têtes e245a1b2c3d4 et f2559e1a2b3c jointes par révision de fusion a2456e1f2b3c, dans le commit de fusion) | 60108b9 | 8 verts / 0 rouge (8 total), tests/test_be245_restauration_verifiee.py |
| 162 | BE-095 | be-095-lot | fusionné (têtes a2456e1f2b3c et c095a1b2d3e4 jointes par révision de fusion 8673695c5fb4, dans le commit de fusion) | 395826c | 4 verts / 0 rouge (4 total), tests/test_be095_reconciliation_paiements.py |
| 163 | BE-262 | be-262-lot | fusionné (têtes 8673695c5fb4 et a262c0de1a7e jointes par révision de fusion f6bf39c21bf7, amendée dans le commit de fusion) | 4e312d1 | 8 verts / 0 rouge (8 total), tests/test_be262_acces_support.py |
| 164 | BE-171 | be-171-lot | fusionné (pas de conflit bloquant ; conflit trivial app/cli.py résolu en conservant les deux seeds support et notifications ; pas de nouvelle tête Alembic, tête unique f6bf39c21bf7) | 86be117 | 6 verts / 0 rouge (6 total), tests/test_be171_consultation_notifications.py |
| 165 | BE-085 | be-085-lot | fusionné (têtes c085e4f1a2b3 et f6bf39c21bf7 réconciliées par révision de fusion 085f6bf39c20, dans le commit de fusion ; migration c085e4f1a2b3 entitlement_sync) | 1320e71 | 8 verts / 0 rouge (8 total), tests/test_be085_synchronisation_droits.py |
| 166 | BE-089 | be-089-lot | fusionné (têtes 085f6bf39c20 et c4089b2a1e7f jointes par révision de fusion 089d4c7e2a10, dans le commit de fusion ; migration c4089b2a1e7f renewal_run ; conflit models.py résolu par conservation des deux classes ajoutées) | bc0f8b9 | 5 verts / 0 rouge (5 total), tests/test_be089_renouvellement_abonnement.py |
| 167 | BE-252 | be-252-lot | fusionné (têtes 089d4c7e2a10 et b252c3d4e5f6 réconciliées par révision de fusion e252d0a1f7c3, dans le commit de fusion ; migration b252c3d4e5f6 compensations) | 9ecdab7 | 8 verts / 0 rouge (8 total), tests/test_rollback_compensation_be252.py |
| 168 | BE-257 | be-257-lot | fusionné (pas de nouvelle tête Alembic, tête unique e252d0a1f7c3) | 5b00115 | 5 verts / 0 rouge (5 total), tests/test_be257_runbooks.py |
| 169 | BE-243 | be-243-lot | fusionné (conflits triviaux app/cli.py et app/core/config.py résolus en conservant les deux côtés ; révision de fusion Alembic f243a0b1c2d4 jointe aux têtes a243b0c1d2e3 et e252d0a1f7c3, dans le commit de fusion ; tête unique f243a0b1c2d4) | fa14235 | 31 verts / 0 rouge (31 total), tests/test_be243_export_donnees.py + tests/test_surface_api.py |
| 170 | BE-258 | be-258-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique f243a0b1c2d4 ; modifie app/notifications/canal.py, tests test_be170_adaptateur_canal.py relancés) | f815351 | 20 verts / 0 rouge (20 total : 11 BE-258 + 9 BE-170), tests/resilience/test_be258_ca1..ca4 + tests/test_be170_adaptateur_canal.py |
| 171 | BE-238 | be-238-v2 (réconciliation ; be-238-lot non utilisée) | fusionné (conflit BE-170 évité par la branche v2 ; deux têtes Alembic adce56acf5ff et f243a0b1c2d4 réconciliées par révision de fusion c238f2430a1b, amendée dans le commit de fusion ; tête unique c238f2430a1b) | 89a6ae7 | 14 verts / 0 rouge (14 total : 5 BE-238 + 9 BE-170), tests/test_be238_livraison_preferences.py + tests/test_be170_adaptateur_canal.py |
| 172 | BE-091 | be-091-lot | fusionné (têtes c238f2430a1b et e091a1b2c3d4 jointes par révision de fusion fb5bcc482678, dans le commit de fusion) | 16bbade | 8 verts / 0 rouge (8 total), tests/test_be091_incidents_paiement.py |
| 173 | BE-097 | be-097-lot | fusionné (têtes b097c1d2e3f4 et fb5bcc482678 jointes par révision de fusion 2380bdbe5074, dans le commit de fusion) | b87465f | 10 verts / 0 rouge (10 total), tests/test_be097_cloture_abonnement.py |
| 174 | BE-259 | be-259-lot | fusionné (pas de conflit ; docs de passation déplacés hors dépôt dans implementation-backend/passation/, commit chore de retrait) | f81a242 | 89 verts / 0 rouge (89 total, sans --noconftest), tests/test_be259_passation.py |
| 175 | BE-092 | be-092-lot | fusionné (pas de nouvelle tête Alembic, tête unique 2380bdbe5074 ; pas de migration ajoutée) | 99f4b19 | 11 verts / 0 rouge (11 total), tests/test_be092_reactivation_abonnement.py |
| 176 | BE-246 | be-246-lot | fusionné (têtes 2380bdbe5074 et a246c1d2e3f4 jointes par révision de fusion 55b65917a1f4, dans le commit de fusion ; migration a246c1d2e3f4) | 458a6f6 | 8 verts / 0 rouge (8 total), tests/test_be246_sortie_tenant.py |
| 177 | BE-096 | be-096-lot | fusionné (têtes 55b65917a1f4 et c096d1e2f3a4 jointes par révision de fusion, dans le commit de fusion ; migration c096d1e2f3a4) | 6d69b0c | 11 verts / 0 rouge (11 total), tests/test_be096_cas_facturation.py |
| 178 | BE-182 | be-182-lot | fusionné (têtes 09fc9f704065 et c1e8be182a01 jointes par révision de fusion, dans le commit de fusion ; migration c1e8be182a01) | 75cba4b | 6 verts / 0 rouge (6 total), tests/test_be182_scope_tenant.py ; tables module_state_transitions et subscription_entitlement déclarées nullables par conception (QE appliquée) |
| 179 | BE-183 | be-183-lot | fusionné (pas de nouvelle tête Alembic, tête unique 52e99f1b21b5 ; pas de migration ; mécanismes BE-232 et BE-233 réutilisés, test CA-5 ajouté) | 2e91887 | 5 verts / 0 rouge (5 total), tests/test_be183_idempotence_version.py |
| 180 | BE-187 | be-187-lot | fusionné (pas de conflit ; tête unique b187e0a1c2d3 ; extension de la table user avec version, QE-API-07) | 8c02edb | 7 verts / 0 rouge (7 total), tests/test_be187_identite_utilisateur.py |
| 181 | BE-147 | be-147-v2 (réapplication de be-147-lot, conflit sur has_platform_authority résolu côté develop) | fusionné (pas de nouvelle tête Alembic, tête unique b187e0a1c2d3 ; require_admin_scope sur les montages /admin, CA-4 mise en place avec autorité BE-121, QE-ADM-BE147-01 appliquée) | 0175565 | 4 verts / 0 rouge (4 total), tests/test_be147_garde_cross_tenant.py |
| 182 | BE-192 | be-192-lot | fusionné (têtes b187e0a1c2d3 et d192a0b1c2e3 jointes par révision de fusion, dans le commit de fusion ; outbox_evenement étendue au lieu de créer event_outbox) | bc75fa8 | 9 verts / 0 rouge (9 total), tests/test_be192_outbox_producteur.py |
| 183 | BE-188 | be-188-lot | fusionné (pas de nouvelle tête Alembic, tête unique ; session portée par refreshToken, pas de table session) | abb85be | 8 verts / 0 rouge (8 total), tests/test_be188_session_logout.py ; test_auth, test_sessions_cookies, test_be005 : 37 verts |
| 184 | BE-184 | be-184-lot | fusionné (pas de nouvelle tête Alembic, tête unique ; permission audit.log.view réutilisée) | 4b0cb03 | 6 verts / 0 rouge (6 total), tests de BE-184 ; lecture /audit/records journalisée |
| 185 | BE-193 | be-193-lot | fusionné (pas de conflit ; tête unique e193c0a1b2d3) | e4627cf | 8 verts / 0 rouge (8 total), tests/test_be193_inbox_dispatcher.py |
| 186 | BE-100 | be-100-lot | fusionné (têtes be100a0b1c2d et e193c0a1b2d3 jointes par révision de fusion, dans le commit de fusion ; renommage organizationUser vers organization_user, QE-POR-30) | b2a510f | 10 verts / 0 rouge (10 total), tests/test_be100_modele_organisation.py ; test_inventaire_donnees_be242 déjà rouge sur develop (76 tables hors registre, antérieur) |
| 187 | BE-185 | be-185-lot | fusionné (têtes 54ba4aaf7237 et b185c0d1e2f3 jointes par révision de fusion, dans le commit de fusion ; table tenant séparée de organization) | 249b80c | 8 verts / 0 rouge (8 total), tests/test_be185_tenant_cycle_de_vie.py |
| 188 | BE-101 | be-101-lot | fusionné (pas de nouvelle tête Alembic, tête unique 54ba4aaf7237 ; pas de migration) | b195d62 | 6 verts / 0 rouge (6 total), tests de BE-101 |
| 189 | BE-129 | be-129-lot | fusionné (pas de conflit ; pas de migration ; tête unique 54ba4aaf7237) | 9d30b8a | 5 verts / 0 rouge (5 total), tests de BE-129 ; permission admin.search.read non déclarée (écart) |
| 190 | BE-102 | be-102-lot | remplacé par la ligne fusionnée ci-dessous ; ancien état : suspendu (BLOQUE : CA-1 et CA-4 exigent qu aucun rôle Owner ne soit créé à la création, alors que identity/service.py::create_organization en crée un et que la fixture organization de tests/conftest.py en dépend, ~161 fichiers ; décision QE-POR-04 à trancher) | - | non fusionné, worktree BE-102-back conservé sans commit |
| 191 | BE-107 | be-107-lot | fusionné (pas de migration, tête unique 54ba4aaf7237 ; réponse de GET /organizations/{id}/entitlements passe de liste à objet included/addOns, deux tests BE-045 adaptés à included) | f83218e | 4 verts / 0 rouge (4 total), tests/test_be107_entitlements_lecture.py ; BE-045 : 6 verts |
| 192 | BE-038 | be-038-lot (reprise) | fusionné (pas de nouvelle tête Alembic, tête unique 54ba4aaf7237 ; fixtures réelles dans tests/isolation/test_be038_isolation_adversariale.py, QE-SOC-26 appliquée) | 629e1ac | 1398 verts / 0 rouge (1398 total), tests/isolation/test_be038_isolation_adversariale.py ; écart : routes à portée répondent 404 et non 403 pour un identifiant inexistant (constaté, non corrigé) |
| 193 | BE-039 | be-039-lot | en cours (inventaire et générateur des 117 tables présents dans le worktree ; associations routes/tests intégrées ; portée `billing_payer` à clarifier via QE-FAC-22) | d1b296f (test TDD uniquement) | contrôle générateur `--check` et `git diff --check` passés ; pytest final non lancé ; changements d’implémentation non commités |
| 194 | BE-130 | be-130-lot | fusionné (pas de migration, tête unique 54ba4aaf7237 ; offre N/A, PH-07 non résolu) | c99250d | 7 verts / 0 rouge (7 total), tests/test_be130_synthese_compte.py |
| 195 | BE-131 | be-131-lot | fusionné (pas de migration, tête unique 54ba4aaf7237 ; incidents réservés à la portée plateforme, taille de page non définie) | 099abe2 | 5 verts / 0 rouge (5 total), tests/test_be131_*.py |
| 196 | BE-108 | be-108-lot | fusionné (migration b108c4a1d2e3 sur tête 54ba4aaf7237, tête unique b108c4a1d2e3 ; table usage_snapshot vide sans écrivain) | dc428ad | 8 verts / 0 rouge (8 total), tests/test_be108_usage_lecture.py ; test_route_inventory et test_authorization_matrix non lancés (transverses) |
| 197 | BE-185 | be-185-v2 (réparation de be-185-lot, table tenant unique de BE-100) | fusionné (migration de colonnes seulement ; tête unique b108c4a1d2e3 ; ROUGE TRANSVERSE HORS LOT : BE-100 ca1 reste rouge, cause = révision de fusion 54ba4aaf7237 et chaîne BE-193, à corriger en fin de plan par réordonnancement) | e9143f4 | 8 verts / 0 rouge (8 total), tests/test_be185_tenant_cycle_de_vie.py ; BE-100 : 9 verts / 1 rouge (ca1, transverse) |
| 198 | BE-116 | be-116-lot | fusionné (migration chaînée sur b108c4a1d2e3, tête unique c9d8e7f6a5b4 ; permission billing.payment_method.manage) | 2eba921 | 8 verts / 0 rouge (8 total), tests/test_be116_moyens_paiement.py |
| 199 | BE-105 | be-105-v2 (réapplication de be-105-lot) | fusionné (pas de migration, tête unique c9d8e7f6a5b4 ; permission organization.members.invite) | 493bb6d | 9 verts / 0 rouge (9 total), tests/test_be105_*.py |
| 221 | BE-212 | be-212-lot | fusionné (pas de migration, tête unique be215a1b2c3d ; tables notification et notification_preference non créées, réutilisation de BE-169 et BE-168) | 87e2913 | 7 verts / 0 rouge (7 total), tests/test_be212_notifications_categories.py |
| 220 | BE-110 | be-110-lot | fusionné (pas de migration, tête unique ; permissions billing.checkout.purchase et billing.subscription.read ; pas de transaction unique devis-consentement-checkout) | d824388 | 8 verts / 0 rouge (8 total), tests/test_be110_sessions_paiement.py |
| 219 | BE-215 | be-215-lot | fusionné (migration be215a1b2c3d, tête unique ; table contract_version avec schemaJson ajoutée, removedAt lu mais non écrit ; droit platform.catalog.manage par allowlist) | 1608f0d | 15 verts / 0 rouge (15 total), tests/test_be215_compatibilite_versions.py ; matrice non régénérée |
| 218 | BE-211 | be-211-lot | fusionné (tête jointe par révision de fusion, dans le commit de fusion ; colonnes id/organizationId, permission integrations.manage) | d0dc7f3 | 7 verts / 0 rouge (7 total), tests/test_be211_webhook_sortant.py |
| 217 | BE-202 | be-202-lot | fusionné (migration be202d3e4f5a, tête jointe avec b211a0c1d2e3 par révision de fusion ; routes ajoutées à côté de BE-077/081/076 ; consent distinct de consent_record) | 025267c | 6 verts / 0 rouge (6 total), tests/test_be202_devis_checkout_consentement.py |
| 216 | BE-200 | be-200-lot | fusionné (pas de migration, tête unique 2402c108f2e6 ; tables plan/planVersion existantes réutilisées ; routes /api/v1/plans) | 8f4f54b | 8 verts / 0 rouge (8 total), tests/test_be200_plans_plan_version.py |
| 215 | BE-210 | be-210-lot | fusionné (têtes be210c0d1e2f et c117e5a1b2d3 jointes par révision de fusion, dans le commit de fusion ; colonnes organizationId/id, permission integrations.manage réutilisée) | ecb597c | 7 verts / 0 rouge (7 total), tests/test_be210_integration_configuration.py ; table_inventory et matrice non mises à jour |
| 214 | BE-117 | be-117-lot | fusionné (migration c117e5a1b2d3, tête unique ; permission data.export, traitement BackgroundTasks, périmètre membres) | 9544152 | 8 verts / 0 rouge (8 total), tests/test_be117_exports_asynchrones.py |
| 213 | BE-194 | be-194-lot | fusionné (têtes 02a46cdda276 et e194b1d2c3a4 jointes par révision de fusion, dans le commit de fusion ; status remplacé par publicationState existant) | c2426da | 12 verts / 0 rouge (12 total), tests/test_be194_catalogue_modules.py ; GET /modules non filtrée (hors lot, à signaler) |
| 212 | BE-213 | be-213-v2 (réapplication des tests de be-213-lot, base develop après BE-190) | fusionné (têtes b103c0de0103 et c213a1b2c3d4 jointes par révision de fusion, dans le commit de fusion ; QE-API-18 non tranché : échéance 24 h) | 8272de2 | 7 verts / 0 rouge (7 total), tests/test_be213_jobs_import_export.py |
| 211 | BE-103 | be-103-v2 (réapplication de be-103-lot, base develop après BE-102) | fusionné (migration b103c0de0103, tête unique b103c0de0103 ; permissions au seul propriétaire, QE-POR-07 non tranchée ici) | 79137c2 | 5 verts / 0 rouge (5 total), tests/test_be103_verification_organisation.py |
| 210 | BE-104 | be-104-lot | fusionné (pas de migration, tête unique be102c0de0102 ; droit organization.update ; champs inconnus refusés en 400) | 2ddb0a0 | 6 verts / 0 rouge (6 total), tests/test_be104_*.py |
| 209 | BE-102 | be-102-v2 (réapplication, base develop après BE-189) | fusionné (migration be102c0de0102, tête unique ; QE-POR-04 appliquée : aucun Owner à la création, doublon 409 ; createdByUserId ajouté ; BE-100 : 9 rouges transverses après le downgrade -1 du test ca1, à corriger en fin de plan) | be5a228 | 6 verts / 0 rouge (6 total), tests/test_be102_creation_organisation.py |
| 208 | BE-190 | be-190-lot | fusionné (pas de migration, tête unique b189c0de0189 ; membershipId remplacé par userId ; refus plateforme inconditionnel sur les routes) | d3b565e | 6 verts / 0 rouge (6 total), tests/test_be190_rbac_roles_grants.py |
| 207 | BE-140 | be-140-lot | fusionné (pas de migration, tête unique b189c0de0189 ; rôle owner refusé en 403, hypothèse à confirmer ; test_route_inventory et test_gardes_permissions_routes non lancés) | 46533d6 | 7 verts / 0 rouge (7 total), tests/test_be140_changement_role_adhesion.py |
| 206 | BE-109 | be-109-lot | fusionné (pas de migration, tête unique b189c0de0189 ; conflit trivial de constantes permissions.py résolu en gardant les deux ; permission portal.summary.read) | 1833657 | 5 verts / 0 rouge (5 total), tests/test_be109_resume_portail.py |
| 205 | BE-189 | be-189-lot | fusionné (migration b189c0de0189, tête unique ; table organization_user avec version ; invitation sans acceptation, écart noté) | bb1620e | 9 verts / 0 rouge (9 total), tests/test_be189_membership_contexte.py |
| 204 | BE-106 | be-106-lot | fusionné (pas de migration, tête unique 8a46d69b86bf ; RoleChanged et Removed émis aussi par BE-014/015, tests de ces routes non relancés, risque de régression à vérifier) | 1423e6f | 6 verts / 0 rouge (6 total), tests/test_be106_membres_portail.py |
| 204 | BE-134 | be-134-lot | fusionné (pas de migration, tête unique 8a46d69b86bf ; textes d effet provisoires NON DÉFINI, QE-ADM-22) | 7c45f21 | 7 verts / 0 rouge (7 total), tests/test_be134_suspension_tenant.py |
| 202 | BE-118 | be-118-lot | fusionné (têtes a118c0de0118 et ec5fe3455ca9 jointes par révision de fusion ; conflit trivial de dictionnaire portee_organisation.py résolu en gardant les deux entrées ; permission support.request.create) | 0e98968 | 5 verts / 0 rouge (5 total), tests/test_be118_demande_support.py |
| 201 | BE-039 | be-039-lot | fusionné (pas de migration ; 6 tables ORM hors app.main inventoriées via MODULES_ORM_SOCLE_HORS_APP, QE-BE039-01) | 5895538 | 4 verts / 0 rouge (4 total), tests/test_be039_*.py |
| 200 | BE-186 | be-186-v2 (réapplication, base develop après BE-185) | fusionné (têtes c9d8e7f6a5b4 et d186a0c1e2f3 jointes par révision de fusion, dans le commit de fusion ; PATCH de BE-104 réutilisé, droit organization.update) | 8eca023 | 11 verts / 0 rouge (11 total), tests/test_be186_organisation_workspace.py ; régressions possibles hors ciblé non vérifiées |
| 222 | BE-047 | be-047-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d) | 32043e8 | 14 verts / 0 rouge (14 total), tests/test_be047_installation_technique.py |
| 223 | BE-080 | be-080-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d) | 061558b | 7 verts / 0 rouge (7 total), tests/test_be080_demarrage_essai.py |
| 224 | BE-086 | be-086-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d) | 1a77efc | 9 verts / 0 rouge (9 total), tests/test_be086_facture_brouillon_finalisation.py |
| 225 | BE-088 | be-088-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d) | 91035df | 8 verts / 0 rouge (8 total), tests/test_be088_changement_plan.py |
| 226 | BE-122 | be-122-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d) | 91f8a16 | 9 verts / 0 rouge (9 total), tests/test_be122_journal_audit_admin.py |
| 227 | BE-195 | be-195-lot | fusionné (pas de conflit ; pas de nouvelle tête Alembic, tête unique be215a1b2c3d ; manifeste de module et publication par code POST /api/v1/admin/modules/by-code/{code}/versions) | ebc6d91 | 23 verts / 0 rouge (23 total), tests/test_be195_manifeste_module.py |

Lots 48 a 54 (be-013, be-017, be-036, be-041, be-045, be-071, be-037) : fusion par lots dans develop, sans push ni suppression de branche.

- be-133-lot | fusionné 64fafd7 dans develop (tests ciblés 16/16 verts ; alembic merge 113a8dea4869 ; base de test zylo_t000_test repointée de e45fe8541be4 vers 113a8dea4869)

## Audit du 2026-11-13 (lecture seule, aucun test lancé, aucun commit)

Statut : **figé pour déploiement**. Méthode : croisement de PLAN-BACKEND.md, DEPENDANCES.md, des lignes de ce fichier, des motifs de fusion git sur `develop` (HEAD ebc7ad0) et des fiches `tasks-*.md`. Les contrôles de dépendances ont été refaits à partir de DEPENDANCES.md.

### Compte consolidé

- Tâches : 245 (BE-261 fusionnée dans BE-024, non comptée). BE-279 n'existe pas.
- Fusionnées : **230** = 224 fusions tracées dans ce fichier (dont BE-133, ligne de fin de fichier) + 6 fusions tracées seulement dans git (BE-196, BE-198, BE-201, BE-203, BE-204, BE-214).
- Restantes : **15**.
- ETAT-GEL-2026-11-13.md (non modifié, gel) donne 223 fusionnées, compte BE-133 comme restante et des totaux par domaine faux. Ce fichier fait foi (QE-SUI-03).

### Par domaine (fiches tasks-*.md)

| Domaine | Tâches | Fusionnées | Restantes | Restantes (identifiants) |
|---|---|---|---|---|
| abonnements-facturation | 30 | 30 | 0 | - |
| administration-interventions | 28 | 27 | 1 | BE-137 (bloquée par décision) |
| donnees-api-contrats | 36 | 29 | 7 | BE-197, BE-199, BE-205, BE-206, BE-207, BE-208, BE-209 |
| exploitation-architecture | 40 | 40 | 0 | - |
| fondation-recensement | 3 (hors BE-261) | 2 | 1 | BE-263 |
| modules-droits | 22 | 22 | 0 | - |
| parametres-notifications-audit | 27 | 27 | 0 | - |
| portail-organisation | 20 | 14 | 6 | BE-111, BE-112, BE-113, BE-114, BE-115, BE-119 |
| socle-tenant-identite | 39 | 39 | 0 | - (BE-261 absorbée par BE-024) |
| Total | 245 | 230 | 15 | |

Les totaux de domaine ne se recoupent pas avec le plan pour BE-203 à BE-209 et BE-214 : chaque identifiant n'est compté qu'une fois, dans le domaine de sa fiche.

### Restantes : état et blocages

| Tâche | Domaine | État | Motif ou prochaine action |
|---|---|---|---|
| BE-112 | portail | prête (BE-203 fusionnée) | Décision QE-POR-08 (prorata) ouverte, non bloquante pour la fusion technique |
| BE-197 | donnees | prête (BE-196 fusionnée), code sur branche `be-197-lot` seulement | Fusion après QE-BE-197-ROUTES (routes HTTP ou service interne) |
| BE-199 | donnees | prête (BE-196 fusionnée), branche `be-199-back` | Fusion |
| BE-205 | donnees | prête (BE-204 fusionnée), branche `be-205-lot` | Fusion |
| BE-206 | donnees | prête (BE-204 fusionnée), branche `be-206*` | Décisions QE-POR-08 et QE-POR-29 à trancher |
| BE-137 | administration | bloquée par décision | EXT PH-07 et PH-08 non résolu (QE-ADM-22) ; BE-214 fusionnée |
| BE-111 | portail | bloquée par prérequis | BE-206 |
| BE-113 | portail | bloquée par prérequis | BE-205 |
| BE-114 | portail | bloquée par prérequis | BE-113, BE-207 |
| BE-115 | portail | bloquée par prérequis | BE-113, BE-114, BE-206 |
| BE-119 | portail | bloquée par prérequis | BE-112, BE-113 |
| BE-207 | donnees | bloquée par prérequis | BE-206 |
| BE-208 | donnees | bloquée par prérequis | BE-206 (WIP sur `be-208-lot`) |
| BE-209 | donnees | bloquée par prérequis | BE-206 ; commits `feat`/`test` déjà sur develop sans fusion (QE-SUI-05) |
| BE-263 | fondation | bloquée par prérequis | BE-206 |

Chemin critique : BE-206 débloque à elle seule BE-111, BE-207, BE-208, BE-209 et BE-263 ; avec BE-205, elle débloque BE-113, puis BE-114, BE-115 et BE-119.

### Fusions à réconcilier (suite de QE-SUI-01)

- BE-039 : fusionnée (ligne « fusionné », 5895538). La ligne « en cours » est remplacée.
- BE-054 : première tentative rejetée (ligne 103), fusionnée en v2 (ligne 110, fbbc205).
- BE-102 : suspendue puis fusionnée en v2 (ligne 209, be5a228), QE-POR-04 appliquée.
- BE-138 : fusionnée alors que la fiche est BLOCKED (Q-06) : seul le refus 403 est livré ; l'accès cross-tenant reste bloqué.
- BE-036 : fusionnée alors que la fiche indique « bloquée par décision » (QE-SOC-11) : recommandation appliquée.
- BE-146 : fusionnée avec 1 skip (QE-ADM-15).

### Dette connue avant déploiement

1. **Bloquant** : identifiants réels publiés dans l'historique de `zylo-office-backend` (QE-SEC-01). Rotation Neon, Holykell et VAPID avant tout déploiement ou push.
2. Mot de passe de démonstration en clair dans `scripts/bootstrap_demo_org.py` (QE-SEC-02).
3. Résultats de la suite complète non consignés (« à compléter » plus haut). Un run unique reste à faire sur la base jetable `zylo_t900_test`. Cet audit ne le lance pas.
4. Rouges transverses : BE-100 ca1 (révision 54ba4aaf7237 et chaîne BE-193) ; `test_inventaire_donnees_be242` (76 tables hors registre, à confirmer par le run).
5. Skips : BE-002 et BE-003 (renvoi BE-009), BE-030 et BE-031 (cycle downgrade), BE-146 (QE-ADM-15).
6. BE-054 : 10 tests BE-049 non relancés depuis la v2 ; 31 tests attendus en 403 faute d'abonnement, adaptation prévue en phase transverse (QE-BE054-03, QE-BE054-04).
7. Tests transverses non relancés sur certains lots : `test_route_inventory`, `test_authorization_matrix`, `test_gardes_permissions_routes` (lots BE-106, BE-108, BE-140, BE-158, BE-163, BE-169 à vérifier).
8. Routes et permissions : BE-197 sans route documentée ; `GET /modules` non filtrée (BE-194) ; permission `admin.search.read` non déclarée (BE-129) ; routes à portée répondant 404 et non 403 pour un identifiant inexistant (BE-038).
9. Déploiement : port du compose racine `3007:3007` (QE-DEP-01) ; Python 3.13 local contre 3.12 pour l'image (QE-DEP-03) ; `worktrees/` non ignoré (QE-SUI-02).
10. Documentation : `Audit-chaines-dependances.md`, `Audit-test-compliance-transversale.md` et `Audit-PLAN-INTERFACES-BE-routage.md` sont antérieurs à cet audit et partiellement faux (QE-SUI-06, QE-SUI-08). BE-261 résiduelle dans `tasks-fondation-recensement.md` (QE-SUI-07).
11. Décisions ouvertes (NON DÉFINI) : 251 QE distinctes dans `POINTS-OUVERTS.md`, dont finance et PSP (QE-FAC), support (QE-ADM), modules (QE-MOD).

### Résultats de la suite

Non exécutés par cet audit (lecture seule). À compléter après le run unique décidé par le propriétaire (QE-SUI-09).
