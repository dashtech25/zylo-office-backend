# T-010 : Isolation inter-organisations (IDOR) sur les 13 routes et sur toutes les routes d'organisation

- **Statut** : À vérifier · **Priorité** : P0 · **Vague** : 1 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : security
- **Branche suggérée** : `fix/T-010-isolation-organisations` · **Base de test** : `zylo_t010_test` · **Ports** : back 3110, front prod 3310
- **Dépendances** : T-004 (faite)
- **Décisions requises** : `rbac/code-http-acces-interdit.md` (recommandation appliquée : 404 uniforme)

## Objectif
L'autorisation se fait sur l'en-tête `X-Organization-Id`, l'action sur l'`organization_id` du chemin, et rien ne compare les deux. Un administrateur de A peut agir sur B. Le client n'est jamais autorité sur le tenant : l'en-tête est un sélecteur, validé contre une appartenance active, pour **toutes** les routes d'organisation (avec ou sans chemin), et chaque objet est chargé avec le filtre `organizationId`.

## Problèmes résolus
- BCK-001 (P0), IAM-001 (P0), IAM-018, ARC-009 (partie), IAM-013 (partie), REV-S-04 (périmètre limité aux 13 routes), REV-D-19 (partie)

## Dépendances : justification
Dépendances initiales retirées par décision du coordinateur : T-005 (base dédiée), T-038a (CI bloquante), T-008 (parcours prod). Correctif de sécurité P0 dont les preuves sont des tests pytest ; l'isolation de base est déjà assurée par `scripts/dev/env_tache.sh` (base dédiée `zylo_t010_test`). Seule dépendance restante : T-004 (faite). Bloque T-018, T-019, T-021, T-022, T-023, T-036, T-047.

## Fichiers / modules concernés
- `app/rbac/service.py` : `get_current_organization_id` (validation d'appartenance centralisée, cible = chemin si présent, sinon en-tête ; en-tête incohérent refusé), `assert_active_membership`, `assert_target_is_member` (rôles et grants), `require_permission` (inchangé, s'appuie sur la dépendance validée). Adapté : `app/rbac/dependencies.py` n'existe pas.
- `app/identity/router.py`, `service.py` (`PATCH /organizations/{id}`, `protected-demo` : protégées ici, supprimées par T-051) ; `require_organization_member` passe par la même vérification
- `app/modules_registry/router.py`, `service.py`
- `app/billing/router.py` (`POST /organizations/{id}/subscriptions`)
- `app/rbac/router.py`
- `tests/test_isolation_organisations.py` (créé : 13 routes à chemin, routes sans chemin, attribution à un non-membre, élévation), `tests/test_rbac*.py`, `tests/test_modules.py`, `tests/test_rbac_grants_and_audit.py` (test de délégation : les délégués deviennent membres, IAM-004)

## Stratégie
1. Dépendance unique : l'acteur doit avoir une appartenance active (`OrganizationUser`) à l'organisation du chemin. Si l'en-tête est présent, il doit être égal au chemin. Réponse uniforme 404 pour « inexistant » et « interdit » (R2).
2. Validation d'appartenance dans `get_current_organization_id` : applique la règle aux routes sans chemin (zylo_liquid, zylo_tanker, files, shared), pas seulement aux 13 routes.
3. Objets chargés par `WHERE id = :id AND organizationId = :org`.
4. Interdire tout `require_permission` qui ne compare pas l'organisation à l'appartenance.

## Tests attendus
- Paramétré sur les 13 routes : utilisateur de A (tous droits sur A) appelant B reçoit 404, aucune écriture en base.
- Échantillon de routes sans chemin (zylo_liquid, zylo_tanker, files) : en-tête de B refusé pour un membre de A seul.
- Membre de A et B reste autorisé selon ses droits sur chacune.
- Non-régression : `tests/test_rbac*.py`, `tests/test_modules.py`.
- Playwright sur build prod : `proprietaire-02` et `-04` passent (configuration de T-008).

## Critères d'acceptation
- Les 13 routes de `identite-permissions.md` refusent le cross-tenant, avec au moins 13 cas de test.
- Une route sans chemin d'organisation qui accepte un en-tête étranger fait échouer le test.
- Aucune route d'organisation sans dépendance d'appartenance (contrôle par T-023).

## Risque et retour arrière
Élevé : 13 routes et tout le frontend envoient l'en-tête. Une validation trop stricte casse les parcours. Retour arrière : revert de la dépendance ; le test cross-tenant reste pour mesurer.

## Livrable documentaire
- `docs/architecture/securite/isolation-organisations.md` (créé)
- `docs/questions/rbac/code-http-acces-interdit.md`

## Réalisation (T-010)
- Réponse uniforme 404 `organization_not_found` pour une organisation étrangère, inexistante, supprimée, sans appartenance, ou désignée de façon incohérente entre chemin et en-tête ; 403 `permission_denied` réservé au refus de droit dans une organisation dont l'utilisateur est membre (`docs/questions/rbac/code-http-acces-interdit.md`, option A).
- Attribution de rôle et création de grant : 404 `user_not_found` si la cible n'est pas membre de l'organisation.
- Preuves : avant correctif, 13 routes sur 13 répondent 200/201/204 à un administrateur de A visant B (`tests/test_isolation_organisations.py`) ; après, 23 tests de cette fiche passent et la suite ciblée (rbac, identity, modules, billing, auth) reste verte (53 tests).
- Non traité ici : `_assert_no_privilege_escalation` et `require_permission_scoped` restent évalués sur l'organisation validée (pas de contrôle objet par objet supplémentaire) ; IAM-002, IAM-012 (deny sans garde-fou) restent ouverts.

## Parallélisable avec
T-006, T-007, T-011 à T-016 (fichiers distincts ; `rbac/` n'est touché par aucune de ces tâches).

## Statut au lot 2 (2026-10-09) : À vérifier
- Critères 1 et 2 satisfaits : 13 cas paramétrés sur les routes par chemin, en-tête étranger refusé (`tests/test_isolation_organisations.py`).
- Critère 3 non satisfait : « aucune route d'organisation sans dépendance d'appartenance » relève du contrôle de T-023, pas encore réalisé.
- Défaut trouvé après fusion et corrigé (commit `fix(gps)`) : le webhook Traccar `POST /gps/ingest`, sans utilisateur connecté, était refusé. Le webhook lit désormais l'en-tête d'organisation, le secret de passerelle reste la garde.
- Contrat : organisation étrangère répond 404 `organization_not_found` (option A), ce qui modifie des tests de T-014 et du poste pompiste (mis à jour).
