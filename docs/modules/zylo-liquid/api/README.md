# Zylo Liquid : API, vue d'ensemble

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.


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

**`Tank` : 3 champs pourcentage remplacés par 3 champs millimètres
(ÉTENDRE)** — `alertLowPercent`/`alertCriticalPercent`/`alertHighPercent`
(Phase 1) remplacés par `heightAlarmMm`/`heightAlertMm`/`lowAlarmMm`.
`fonctionnalite-mvp.md` §1.2 et Point 2 §1.2 exigent explicitement des
seuils en millimètres, saisis par cuve — cohérent avec l'algorithme
d'alarme du Point 13 qui compare `H_net` directement à des seuils en mm,
jamais à un pourcentage de capacité. Les champs pourcentage n'avaient
jamais été exposés par aucun endpoint (`tanks` est le premier endpoint à
toucher ce modèle) et la table était vide en développement — remplacement
sans donnée perdue, migration `82fd37bd908f_tank_mm_alarm_thresholds.py`.
`alertWaterMaxMm` déjà conforme (mm), conservé sans changement.

**Permissions de module accordées automatiquement au owner à l'activation**
— voir §3 ci-dessus. Décision structurelle du socle, pas spécifique à Zylo
Liquid, mais découverte et corrigée à l'occasion de ce premier endpoint.

## 7. Points encore à confirmer

- Aucun rôle autre que `owner` ne peut aujourd'hui recevoir une permission
  zylo_liquid (aucun endpoint RBAC HTTP pour associer un rôle non-owner à
  une permission) — hors périmètre de l'endpoint 1, à traiter si/quand un
  besoin de rôle non-owner apparaît sur un module métier.

## Domaines d'API

- [Produits carburant](produits-carburant.md) : endpoint 1
- [Stations](stations.md) : endpoint 2
- [Cuves et calibration](cuves-et-calibration.md) : endpoints 3 à 5
- [Synchronisation Holykell](holykell-synchronisation.md) : endpoint 6
- [État courant et mesures](etat-courant-et-mesures.md) : endpoints 7 et 8
- [Vue réseau et snapshot](reseau.md) : endpoints 9 et 13
- [Livraisons, fuites et alertes](livraisons-fuites-alertes.md) : endpoints 10 à 12
- [Devises, prix et valeur monétaire](devises-prix-valeur.md) : endpoints 14 à 16

Les rapports de livraison « Rapport final — Endpoint N » sont dans l'archive : [`phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md), sections 8 à 23 (lignes 645 à 907).
