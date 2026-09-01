# Zylo Liquid — Phase 2 : API

> Document vivant, complété endpoint par endpoint au fur et à mesure de leur
> construction (procédure : `Point 3 — Définir la procédure de développement
> endpoint par endpoint.md`, `nouveau-station-simulator/etude-nouveau-zylo/`).
> Un seul endpoint en cours de développement à la fois — cette section ne
> couvre que les endpoints déjà `TERMINÉ` selon le cycle d'état du §19 de
> Point 3.

## 1. Quelle architecture est appliquée

Modular Monolith with Layered Domain Model (`grande_phases.md` §5-6) : le
module `app/modules/zylo_liquid/` porte ses propres `models.py`,
`schemas.py`, `service.py`, `router.py`, `permissions.py`, `seed.py` —
jamais mêlés au Core. Pagination `limit`/`offset` + enveloppe
`{"data","meta"}`, erreurs `{"error":{"code","message","details"}}`,
authentification JWT + `X-Organization-Id` + `require_permission` +
`require_module_active("zylo_liquid")` — repris tels quels du socle
(`grande_phases.md` §14, §7-9).

## 2. Ce qui a été construit

### Endpoint 1 — Produits carburant (`fuel-products`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 1.5.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/fuel-products` | `zyloLiquid.fuelProduct.manage` |
| GET | `/api/v1/zylo-liquid/fuel-products` | `zyloLiquid.fuelProduct.read` |
| GET | `/api/v1/zylo-liquid/fuel-products/{id}` | `zyloLiquid.fuelProduct.read` |
| PATCH | `/api/v1/zylo-liquid/fuel-products/{id}` | `zyloLiquid.fuelProduct.manage` |

Fichiers : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
câblage dans `app/api/v1/router.py` (préfixe `/zylo-liquid`).

Tests : `tests/test_zylo_liquid_fuel_products.py` (8 cas : création/lecture,
pagination + isolation multi-tenant, code dupliqué → 409, modification,
404, permission manquante → 403, en-tête organisation manquant → 422, non
authentifié → 401).

## 3. Ce qui a été factorisé dans le Core (correction de portée, pas une extension du périmètre initial)

**`app/modules_registry/service.grant_module_permissions_to_owner`** —
constat fait en construisant cet endpoint 1 : aucun endpoint HTTP RBAC
n'existe pour attribuer une permission à un rôle (`app/rbac/` n'a ni
`router.py` ni `schemas.py`) — un module activé restait donc inutilisable
par quiconque, y compris son propre owner, tant qu'aucune permission ne lui
était accordée manuellement en base. Corrigé dans le Core (`modules_registry`,
pas dans `zylo_liquid`, car applicable à tout module futur) : l'activation
d'un module accorde désormais automatiquement au rôle `owner` de
l'organisation toutes les permissions déjà déclarées (table `permission`)
pour ce `moduleCode`. Testé dans `tests/test_modules.py::test_activating_module_grants_its_permissions_to_owner`.

**`app/modules/zylo_liquid/seed.py::seed_known_permissions`** — permissions
zylo_liquid pré-enregistrées au démarrage (`app/main.py`), symétrique à
`seed_known_modules` déjà existant — nécessaire pour que
`grant_module_permissions_to_owner` trouve des lignes `Permission` à
accorder dès la première activation.

## 4. Ce qui reste propre au module

Le modèle `FuelProduct`, son service, ses schémas et son router restent
entièrement dans `app/modules/zylo_liquid/` — aucune notion Core nouvelle
introduite par cet endpoint hors la correction RBAC ci-dessus.

## 5. Comparaison aux sources de vérité

- `schema_complet_base_de_donnees.sql` : table `fuel_products`, aucune
  colonne d'organisation (schéma source pensé pour un réseau unique).
- Base réelle `zylo_liquid` : `fuel_products.code` UNIQUE globalement,
  confirmé identique au schéma (Phase 1, `phase_1_database.md`).
- `niveau_1_base_de_donnees_et_monetisation.md` : ne couvre pas
  l'isolation multi-tenant de `FuelProduct` (hors de son périmètre, centré
  sur le sujet monétaire) — décision ci-dessous prise indépendamment.

## 6. Décisions prises

**`FuelProduct.organizationId` ajouté (ÉTENDRE, pas CRÉER)** — absent du
schéma source et de la base réelle testée (réseau unique, jamais
multi-tenant dans ce contexte), mais requis par cohérence avec l'isolation
déjà appliquée à `Station`, `Tank`, `HolykellAccount` et toute autre table
Zylo Liquid : sans cette colonne, une organisation aurait vu et modifié le
référentiel carburant de toutes les autres. `code` redevient unique par
organisation (`uq_zlFuelProduct_org_code`) plutôt que globalement unique.
Migration `7ffb9473d45e_fuel_product_organization_id.py` — une seule ligne
de développement supprimée (`TRUNCATE ... CASCADE`), aucune donnée de
production concernée. Décision prise dans le cadre de la procédure §8/§9.3
de Point 3 (vérification du modèle avant tout endpoint), pas une
alternative business — c'est une exigence d'isolation déjà actée pour
toutes les tables sœurs.

**Permissions de module accordées automatiquement au owner à l'activation**
— voir §3 ci-dessus. Décision structurelle du socle, pas spécifique à Zylo
Liquid, mais découverte et corrigée à l'occasion de ce premier endpoint.

## 7. Points encore à confirmer

- Aucun rôle autre que `owner` ne peut aujourd'hui recevoir une permission
  zylo_liquid (aucun endpoint RBAC HTTP pour associer un rôle non-owner à
  une permission) — hors périmètre de l'endpoint 1, à traiter si/quand un
  besoin de rôle non-owner apparaît sur un module métier.

## 8. Rapport final — Endpoint 1

- Fichiers créés : `app/modules/zylo_liquid/{schemas,service,router,permissions,seed}.py`,
  `tests/test_zylo_liquid_fuel_products.py`, cette documentation.
- Fichiers modifiés : `app/modules/zylo_liquid/models.py` (colonne
  `organizationId`), `app/api/v1/router.py` (câblage), `app/main.py` (seed
  des permissions), `app/modules_registry/service.py`
  (`grant_module_permissions_to_owner`), `tests/conftest.py` (fixture
  `zylo_liquid_organization`), `tests/test_modules.py` (test de
  régression du nouveau comportement d'activation).
- Migration : `7ffb9473d45e_fuel_product_organization_id.py`, appliquée en
  développement.
- Tests : 22/22 verts (`python -m pytest`), y compris les 21 tests
  préexistants (non-régression).
- Vérification réelle : suite `curl` complète (create/get/list/patch,
  code dupliqué → 409, introuvable → 404, permission manquante → 403 avant
  correction RBAC puis 201 après) contre le serveur de développement
  (`uvicorn`, base `zylo_office`).
- Statut : **TERMINÉ**.
