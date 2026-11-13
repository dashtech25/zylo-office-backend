# BE-259 : rapport de passation de la porte back-end

Statut de la porte à la date du rapport : **BLOCKED** (décision humaine absente, voir `BE-259-pv-porte.md`).
Date de rédaction : 2026-11-05. Branche : `be-259-lot`.

## Périmètre et méthode

- Tâches passées en revue : BE-220 à BE-258 (39 tâches, 171 critères CA). BE-259 n'a ni route, ni table, ni migration.
- Statut : lu dans `implementation-backend/SUIVI.md` du dossier office (lecture seule, non modifié ici).
- Fichiers de test : trouvés par nom (`be<NNN>` dans le nom du fichier) sous `tests/`. Ce rapport ne relance aucun test des tâches citées ; la couverture de chaque critère reste à établir par l'intégrateur.
- Seuils : tout seuil NON DÉFINI reste non défini (voir la liste du PV).

## Référencement par tâche

| Tâche | Critères | Statut SUIVI | Fichiers de test (par nom) |
|---|---|---|---|
| BE-220 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_enveloppe_homogene_be220.py` |
| BE-221 | CA-1, CA-2, CA-3, CA-4 | fusionné | aucun fichier nommé |
| BE-222 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_gates_qualite_be222.py` |
| BE-223 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | aucun fichier nommé |
| BE-224 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_journalisation_be224.py` |
| BE-225 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_contexte_tenant_be225.py` |
| BE-226 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be226_moteur_autorisation.py` |
| BE-227 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionne | `tests/test_be227_journal_audit_append_only.py` |
| BE-228 | CA-1, CA-2, CA-3, CA-4 | fusionne | `tests/test_be228_journal_lectures_sensibles.py` |
| BE-229 | CA-1, CA-2, CA-3, CA-4, CA-5, CA-6 | fusionné | `tests/test_be229_acces_operateur.py` |
| BE-230 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_secrets_be230.py` |
| BE-231 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_chiffrement_be231.py` |
| BE-232 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_idempotence_be232.py` |
| BE-233 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_controle_version_be233.py` |
| BE-234 | CA-1, CA-2, CA-3, CA-4 | fusionne | `tests/test_be234_outbox_versionnee.py` |
| BE-235 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be235_consommation_dlq.py` |
| BE-236 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_be236_operations.py` |
| BE-237 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be237_registre_reglages.py` |
| BE-238 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be238_livraison_preferences.py` |
| BE-239 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be239_integrations_liens.py` |
| BE-240 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_sante_be240.py` |
| BE-241 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_alertes_be241.py` |
| BE-242 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_inventaire_donnees_be242.py` |
| BE-243 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be243_export_donnees.py` |
| BE-244 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be244_sauvegardes_chiffrees.py` |
| BE-245 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be245_restauration_verifiee.py` |
| BE-246 | CA-1, CA-2, CA-3, CA-4, CA-5 | absent de SUIVI.md | aucun fichier nommé |
| BE-247 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_be247_incidents.py` |
| BE-248 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_be248_isolation_autorisation_bout_en_bout.py` |
| BE-249 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_supply_chain_be249.py` |
| BE-250 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_release_promotion_be250.py` |
| BE-251 | CA-1, CA-2, CA-3, CA-4, CA-5 | fusionné | `tests/test_be251_flags.py` |
| BE-252 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_rollback_compensation_be252.py` |
| BE-253 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_be253_limites_abus.py` |
| BE-254 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_be254_flux_reseau.py` |
| BE-255 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/test_capacite_be255.py` |
| BE-256 | CA-1, CA-2, CA-3 | fusionné | `tests/test_messages_be256.py` |
| BE-257 | CA-1, CA-2, CA-3 | fusionné | `tests/test_be257_runbooks.py` |
| BE-258 | CA-1, CA-2, CA-3, CA-4 | fusionné | `tests/resilience/test_be258_ca1_migration_interrompue.py`, `tests/resilience/test_be258_ca2_replay_sans_doublon.py`, `tests/resilience/test_be258_ca3_panne_dependance.py`, `tests/resilience/test_be258_ca4_resultats_versionnes.py` |

## Écarts
- Emplacement : le rapport et le PV sont dans `implementation-backend/` du worktree (dépôt backend), et non dans le dossier office, qui n'appartient pas au worktree. L'intégrateur les déplace à la fusion.
- Fiche BE-259 : la section « Code existant » n'existe pas ; rien à réutiliser.
- Tests : `tests/test_be259_passation.py` vérifie la présence, les liens et le statut sur ces documents.

