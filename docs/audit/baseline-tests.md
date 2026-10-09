# Baseline des tests — zylo-office

État réel des suites, relevé le 2026-10-08 (agent de vérification, aucun fichier de code source modifié).

## 0. Environnement et sécurité

- **Backend venv** : `.venv` (ignoré par git, `.gitignore` ligne 7) recréé avec `python3 -m venv .venv` (Python 3.13.5) puis `pip install -r requirements.txt`. Versions vérifiées : FastAPI 0.141.1, SQLAlchemy 2.0.36, pytest 8.3.4.
- **Frontend** : `npm ci` (lockfile), Node v24.18.0, npm 11.16.0.
- **Base de test** : `zylo_office_test` uniquement (PostgreSQL local, port 5432, 114 tables, alembic head `f1a3b5c7d849`). Aucune autre base n'a été lue ni écrite.
- **Choix de base par les tests** : `tests/conftest.py` lignes 5-7 force `os.environ["DATABASE_URL"]` depuis `TEST_DATABASE_URL`, avec pour défaut `zylo_office_test`. Cette variable d'environnement écrase le `.env` du backend, qui pointe vers une autre base (`zylo_office`, port 5433). Toutes les commandes ont été lancées avec `TEST_DATABASE_URL` explicite ou avec le défaut ; le serveur backend de l'e2e a reçu `DATABASE_URL` explicite.
- **Attention** : `conftest.py` `_wipe()` exécute `TRUNCATE ... CASCADE` sur **toutes** les tables de la base cible à chaque session pytest. Les données de référentiel (pays, devises) sont donc effacées à chaque run pytest.
- **Seed ajouté (base de test uniquement)** : après le run pytest, `scripts/seed_world_reference_data.py` a été lancé avec `DATABASE_URL` pointant sur `zylo_office_test` (idempotent, 251 pays et 168 devises créés). Sans ce seed, le global-setup e2e échoue (voir section 3).

## 1. Backend

| Suite | Commande exacte | Résultat réel | Durée |
|---|---|---|---|
| Pytest complet | `cd zylo-office-backend && TEST_DATABASE_URL='postgresql+asyncpg://zylo_office:***@localhost:5432/zylo_office_test' .venv/bin/pytest -q -p no:cacheprovider -rfEs` | **490 passés, 22 échoués, 0 ignoré** (512 tests) | 1377 s |
| Import-linter | `cd zylo-office-backend && .venv/bin/lint-imports` | **10 contrats KEPT, 0 cassé** (120 fichiers, 362 dépendances) | < 1 min |

### 1.1 Tests backend échoués (22)

Toutes les causes ci-dessous sont des **écarts test / contrat d'API**, mesurés dans le log. La cause n'a pas été vérifiée côté code applicatif.

**Groupe A — payload sans `lines` (12 tests, HTTP 422 `validation_error`, champ `body.lines` requis).** Le test envoie une commande ou une déclaration sans la liste `lines` que l'API exige désormais.

- `tests/test_zylo_liquid_approvisionnement.py::test_purchase_order_requires_active_supplier` (attendu `supplier_inactive`, obtenu `validation_error`)
- `tests/test_zylo_liquid_approvisionnement.py::test_delivery_link_coherence_controls`
- `tests/test_zylo_liquid_approvisionnement.py::test_order_received_only_on_completing_lock`
- `tests/test_zylo_liquid_declarations.py::test_create_delivery_declaration`
- `tests/test_zylo_liquid_delivery_flow.py::test_declaration_creation_triggers_discrepancy_alert`
- `tests/test_zylo_liquid_delivery_flow.py::test_stale_pending_declaration_creates_lighter_alert`
- `tests/test_zylo_liquid_delivery_flow.py::test_matched_delivery_creates_no_alert`
- `tests/test_zylo_liquid_purchase_order_document.py::test_generate_purchase_order_document_pdf`
- `tests/test_zylo_liquid_purchase_order_document.py::test_generate_purchase_order_document_docx`
- `tests/test_zylo_liquid_purchase_order_document.py::test_generate_purchase_order_document_invalid_format`
- `tests/test_zylo_liquid_purchase_order_document.py::test_generate_purchase_order_document_requires_permission`
- `tests/test_zylo_liquid_tracking_business_flows.py::test_truck_order_assignment_is_many_to_many_and_bidirectional`

**Groupe B — cascade (7 tests, `KeyError: 'id'` ou `assert 0 == 1`).** La création de l'entité échoue (même cause que le groupe A), donc l'identifiant renvoyé est absent.

- `tests/test_zylo_liquid_declarations.py::test_delivery_declaration_can_be_updated_by_author_while_declared`
- `tests/test_zylo_liquid_declarations.py::test_delivery_declaration_lock_is_irreversible_and_blocks_further_update`
- `tests/test_zylo_liquid_declarations.py::test_delivery_declaration_correction_references_original_via_correctsDeclarationId`
- `tests/test_zylo_liquid_declarations.py::test_delivery_declaration_update_by_non_author_is_denied`
- `tests/test_zylo_liquid_declarations.py::test_list_delivery_declarations_filtered_by_station` (`assert 0 == 1`)
- `tests/test_zylo_liquid_delivery_flow.py::test_detection_creation_resolves_pending_declaration`
- `tests/test_zylo_liquid_reconciliation_engine.py::test_delivery_reconciliation_matched_within_tolerance`
- `tests/test_zylo_liquid_reconciliation_engine.py::test_delivery_reconciliation_discrepancy_beyond_tolerance`
- `tests/test_zylo_liquid_reconciliation_engine.py::test_delivery_reconciliation_pending_when_no_counterpart`

Total : 12 (groupe A) + 9 (groupe B) + 1 (groupe C) = 22. Les `KeyError: 'id'` viennent de la lecture de la réponse d'une création (`tests/test_zylo_liquid_declarations.py:131` et équivalents) qui a échoué en 422 ; le fixture `zylo_liquid_organization` fonctionne.

**Groupe C — droits du rôle manager (1 test).**

- `tests/test_zylo_liquid_staff_batch.py::test_shift_manager_role_rights_and_manager_superset` : `all(...)` est faux. Le rôle manager ne contient pas toutes les permissions `zyloLiquid.*.manage` attendues (cash, pompes, shiftAttendance, etc.). Cause probable : permissions de module ajoutées sans être reportées sur le rôle par défaut, ou test non mis à jour. **À trancher par le propriétaire du domaine RBAC** : ce n'est pas forcément un bug de test.

### 1.2 Suites backend impossibles à exécuter

Aucune. Toutes les suites pytest ont tourné.

## 2. Frontend

| Suite | Commande exacte | Résultat réel |
|---|---|---|
| Installation | `cd zylo-office-frontend && npm ci` | OK (exit 0) |
| TypeScript | `npx tsc --noEmit` | **OK, 0 erreur** (exit 0) |
| ESLint (script du projet) | `npm run lint` | **Échec, exit 1 : 580 erreurs, 24 018 avertissements**. Toutes les erreurs sont dans `storybook-static/` (sortie générée, non exclue par `eslint.config.mjs`). |
| ESLint (sources seules) | `npx eslint src e2e .storybook` | **0 erreur, 8 avertissements** |
| Vitest (projet storybook, Chromium headless) | `npx vitest run --reporter=default` | **223 tests passés, 0 échoué, 120 fichiers** (exit 0). Des erreurs console (`MISSING_MESSAGE administration.users.status.undefined`, `TypeError ... 'length'`) apparaissent sans faire échouer de test. |
| Build de production | `npm run build` (`next build --turbopack`) | **OK** (exit 0), avec avertissements `react-hooks/exhaustive-deps` et `no-img-element` |

**Action corrective suggérée (non faite, hors périmètre)** : ajouter `storybook-static` aux `ignores` de `eslint.config.mjs` pour que `npm run lint` soit vert.

## 3. End-to-end Playwright (build de production)

**Méthode** : `next build` puis `next start -p 3055` (Playwright lancé avec une config externe au dépôt, `scratchpad/playwright.prod.config.cjs`, identique à `playwright.config.ts` sauf `webServer` = `next start`). Le backend tourne sur `localhost:3007` (`NEXT_PUBLIC_API_URL` de `.env.local`), base `zylo_office_test`, `uvicorn app.main:app --port 3007`. Le `playwright.config.ts` du dépôt n'a pas été utilisé tel quel, car son `webServer` lance `npm run dev`.

Commande : `npx playwright test -c <config-externe>` (un seul run).

**Résultat : 17 passés, 10 échoués, 0 ignoré** (27 tests, 2,7 min, hors global-setup).

Échecs :

| Test | Erreur | Cause probable |
|---|---|---|
| `gerant-01-connexion-acces-station.spec.ts:44` (G1, connexion et accès limité) | timeout 120 s, attend le bouton « Nouveau » (l.77) | Non tranché. Flux réel sans mock, probablement données ou écran de station différents. |
| `gerant-affectation-pompistes.spec.ts:71` (B4) | `toHaveCount` : attendu 2, reçu 3 (lignes d'affectation) | Non tranché. Donnée résiduelle ou écart de comportement. |
| `gerant-fermeture-index.spec.ts:66` (D1) | `toBeVisible` échoue | Non tranché. Le flux d'enregistrement ne produit pas le message attendu. |
| `gerant-jaugeage-cuves.spec.ts:67` (D2) | `toBeVisible` échoue | Idem. |
| `gerant-ouverture-tour.spec.ts:27` (B3) | `toBeVisible` échoue | Idem. |
| `gerant-planning-grille.spec.ts:35` (A5) | `toBeVisible` échoue | Idem. |
| `gerant-pointage-passation.spec.ts:32` (B1/B2) | `toBeVisible` échoue | Idem. |
| `gerant-remplacement-pauses.spec.ts:64` (B5) | `toBeVisible` échoue | Idem. |
| `gerant-tours-tableau.spec.ts:15` (A9) | `getByText(/Tours enregistrés/)` introuvable (15 s) | Idem. Le message de succès n'apparaît pas. |
| `proprietaire-07-connexion-holykell.spec.ts:20` (P7) | `getByText('Connecté')` introuvable (20 s) | Dépend d'un compte Holykell réel (`h-smartlink.com` ou simulateur), absent de cet environnement. Voir section 3.1. |

Les 7 échecs `toBeVisible` du groupe gérant ont en commun un flux « enregistrer puis vérifier un message de succès ou une ligne » sur le backend réel. Un log détaillé est disponible dans le scratchpad de la session, à regarder pour les trancher.

### 3.1 Dépendances seed et configuration

- **Référentiel pays (corrigé pour le run)** : le global-setup (`e2e/global-setup.ts:55`) sélectionne l'option « Cameroon ». Après pytest, la table `country` ne contient que des lignes de test (`Testland ...`). Sans le seed, le global-setup échoue et **aucun** test e2e ne tourne (0 passé, 1 erreur globale). Remède appliqué : `DATABASE_URL=<zylo_office_test> .venv/bin/python scripts/seed_world_reference_data.py`. **À relancer après chaque run pytest**, puisque `conftest.py` vide toutes les tables.
- **Holykell réel (P7)** : le test attend une connexion à un compte Holykell réel. Impossible sans simulateur ou identifiants externes. Suite non exécutable dans cet environnement en l'état.
- **Mocks** : `alert-center.spec.ts` et plusieurs autres utilisent `e2e/mockBackend.ts` (pas de backend requis). Les specs « backend réel » attendent `localhost:3007`.
- **Effets de bord** : `e2e/.auth/` et `e2e/fixtures/` sont générés par le global-setup et apparaissent comme non suivis dans git (`?? e2e/.auth/`).

## 4. Synthèse

| Périmètre | Résultat |
|---|---|
| Backend pytest | 490 passés / 22 échoués (causes : payload sans `lines`, cascade, 1 droit de rôle manager) |
| Import-linter | 10/10 OK |
| tsc | OK |
| Lint (script du projet) | KO à cause de `storybook-static/` (sources : 0 erreur) |
| Vitest | 223/223 OK |
| Build de production | OK |
| Playwright (prod) | 17/27 OK, 10 KO ; nécessite un seed pays après chaque pytest |
