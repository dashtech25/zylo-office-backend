# Phase 1 — Base de données du module Zylo Liquid dans le nouveau Zylo Office

> Produit en application de `instruction_2_base_donnees_phase_1.md`. Portée
> strictement limitée à la base de données — aucune API, aucun frontend,
> aucun algorithme métier, aucune migration fonctionnelle.

---

## 20.1 Architecture

**Modular Monolith with Layered Domain Model** — décision déjà établie pour
le nouveau Zylo Office (pas réinventée ici). Appliquée à Zylo Liquid : les
données réellement communes à plusieurs modules futurs sont factorisées dans
le **Core** (`app/shared/`, `app/identity/`), les données spécifiques au
domaine pétrolier/station-service restent dans le **module Zylo Liquid**
(`app/modules/zylo_liquid/`), sans dépendance inversée — un futur module peut
utiliser `country`/`region`/`city`/`organization` sans que Zylo Liquid soit
installé (vérifié en §7 ci-dessous).

## 20.2 Base de données

- PostgreSQL, schéma unique (`public`), SQLAlchemy 2.0 async + Alembic
  (convention déjà posée en Phase 3 du socle Zylo Office).
- Noms de tables/colonnes en camelCase anglais (`grande_phases.md` §5.3),
  appliqué ici aux tables Core géographiques et au module Zylo Liquid — la
  base source (`zylo_liquid`) est en snake_case français, traduite ici
  sans changement de sémantique, structure ou contrainte.
- Tables créées dans cette phase (migration `0240c128e5de`) :
  - Core : `country`, `region`, `city`.
  - Zylo Liquid : `zyloLiquidHolykellAccount`, `zyloLiquidHolykellDeviceRegistry`,
    `zyloLiquidTankMeasurement`, `zyloLiquidFuelProduct`, `zyloLiquidStation`,
    `zyloLiquidTank`, `zyloLiquidTankSensorMapping`, `zyloLiquidTankCalibrationPoint`.
- Partitionnement : le schéma source partitionne `tank_measurements` par
  mois (`PARTITION BY RANGE (measured_at)`). **Non reproduit dans cette
  phase** — SQLAlchemy déclaratif ne modélise pas nativement une table
  partitionnée ; `zyloLiquidTankMeasurement` est créée comme table simple.
  Le partitionnement réel devra être ajouté via une migration Alembic dédiée
  avec DDL manuel (`op.execute(...)`) avant la mise en production, une fois
  le volume de données du nouveau système confirmé.
- Fonctions/triggers PL/pgSQL du schéma source (calcul de checksum,
  interpolation hauteur→volume, trigger d'audit générique, résolveur de
  configuration hiérarchique) : **volontairement non portés**. Ce sont des
  algorithmes métier, explicitement hors périmètre de cette phase
  (`instruction_2...md` §18). Les colonnes qu'ils alimentaient (`checksum`,
  `networkDelaySec`) existent dans les modèles, vides de logique de calcul.

## 20.3 Core partagé

| Table | Rôle | Pourquoi elle est commune | Modules pouvant l'utiliser | Dépendances | Données initiales |
|---|---|---|---|---|---|
| `country` | Référentiel des pays | Un pays n'est pas spécifique à Zylo Liquid — CRM, RH, comptabilité, logistique en auront besoin | Tout module futur | Aucune | Aucune insérée automatiquement dans cette phase (à faire en Phase 2/données de référence — voir §7) |
| `region` | Découpage administratif régional | Idem — dépend uniquement de `country` | Tout module futur | `country` | — |
| `city` | Ville rattachée à une région | Idem | Tout module futur | `region` | — |
| `organization` | Tenant racine (déjà existant, Phase 6 du socle) | Réutilisé tel quel comme "propriétaire de réseau" Zylo Liquid — voir §6 | Tout module | Aucune | — |

`country`/`region`/`city` sont **absentes du schéma initialement validé**
(`schema_complet_base_de_donnees.sql`) mais présentes et peuplées dans la
base PostgreSQL réellement testée (`zylo_liquid` : 6 pays, 16 régions, 16
villes, couverture Cameroun/Côte d'Ivoire/Sénégal/Nigeria/Kenya/Afrique du
Sud) — c'est une évolution réelle du schéma, confirmée par inspection
directe, pas une supposition (voir §5).

## 20.4 Zylo Liquid

| Table | Rôle | Couche source |
|---|---|---|
| `zyloLiquidHolykellAccount` | Credentials et état de sync d'un compte Holykell | 1 — Télémétrie |
| `zyloLiquidHolykellDeviceRegistry` | Registre des sensors Holykell (device + sensor dénormalisés) | 1 — Télémétrie |
| `zyloLiquidTankMeasurement` | Journal immuable des mesures physiques brutes | 1 — Télémétrie |
| `zyloLiquidFuelProduct` | Référentiel des carburants | 2 — Référentiel |
| `zyloLiquidStation` | Station-service physique | 3 — Gold 1 (incluse ici car les cuves en dépendent directement) |
| `zyloLiquidTank` | Cuve physique | 2 — Référentiel |
| `zyloLiquidTankSensorMapping` | Pont capteur Holykell ↔ cuve | 2 — Référentiel |
| `zyloLiquidTankCalibrationPoint` | Points de calibration hauteur→volume | 2 — Référentiel |

Ces 8 tables sont classées Zylo Liquid **sans aucune ambiguïté** : aucune
n'a de recoupement possible avec une donnée générique déjà prévue dans le
Core. Ce sont les couches 1 (Télémétrie) et 2 (Référentiel) du schéma
source, plus `station` (nécessaire aux cuves).

## 20.5 Comparaison — `schema_complet_base_de_donnees.sql` vs base réelle `zylo_liquid`

### Méthode

Lecture intégrale du fichier SQL (3183 lignes, 25 tables, 9 vues, 5
fonctions, plusieurs triggers, 7 couches documentées) puis inspection directe
de la base PostgreSQL réelle (`\dt`, `\d <table>`, `information_schema.columns`,
comptage de lignes) — schéma par schéma, table par table.

### Ce qui est identique

Les 25 tables du schéma source existent toutes dans la base réelle avec la
même structure (vérifié en détail sur `tanks`, `alerts`, `fuel_products`,
`tank_calibration_points`, `tank_sensor_mapping` — colonnes, types,
contraintes CHECK, valeurs par défaut identiques au caractère près).

### Ce qui a été ajouté (présent dans la base réelle, absent du schéma source)

| Élément | Nature | Origine probable |
|---|---|---|
| Table `pays` | Référentiel pays (ISO2/ISO3, devise, fuseau) | Évolution post-schéma-source — le schéma source documentait explicitement l'absence de colonne pays dédiée sur `stations` ("le pays précis est encodé dans notes") ; la base réelle a depuis normalisé cette information |
| Table `regions` | Découpage régional, FK vers `pays` | Idem |
| Table `villes` | Villes, FK vers `regions` | Idem |
| Table `societes` | Entité juridique (raison sociale, RCCM, capital...) | Nouvelle couche organisationnelle entre `proprietaires` et `stations`/`reseaux` |
| Table `reseaux` | Réseau/marque de stations (segment, logo, couleur) | Nouvelle couche entre `societes` et `stations` |
| Vue `v_organisation_station` | Jointure pays→région→ville→société→réseau→station | Vue de commodité sur la nouvelle hiérarchie organisationnelle |
| `proprietaires.societe_principale_id` | FK vers `societes` | Rattachement d'un propriétaire à sa société principale |
| `stations.ville_id`, `.reseau_id`, `.societe_id`, `.pays_id` | FKs vers les 4 nouvelles tables | Normalisation géographique/organisationnelle de la station, en plus des colonnes `city`/`region` en texte libre déjà présentes (coexistence, pas de suppression) |
| `stations.exploitation_type`, `.has_shop`, `.shop_name`, `.shop_surface_m2`, `.has_lavage`, `.has_vidange`, `.has_gaz_domestique`, `.nb_pistes`, `.surface_totale_m2` | 9 colonnes | Extension "commerce/amenities" de la station (boutique, lavage, vidange, gaz domestique) — absente du schéma source |
| `users.role` — valeurs `finance`, `auditeur`, `hse` | Extension du CHECK constraint | Le schéma source limitait `role` à 5 valeurs (admin/proprietaire/gerant/pompiste/maintenance) ; la base réelle en autorise 8 |

### Ce qui n'a pas été trouvé supprimé ni modifié

Aucune table, colonne ou contrainte du schéma source n'a été retirée dans la
base réelle — l'évolution est strictement additive.

### Ce qui a réellement été utilisé pendant les tests (preuve d'une base "éprouvée", pas juste créée)

```
tank_measurements   : 590 972 lignes (8 partitions mensuelles actives)
shifts              : 9 516
reconciliations     : 9 516
alerts              : 1 255
delivery_notes      : 1 399
credit_ledger       : 5 690
stations            : 22
tanks               : 52
users               : 94
credit_customers    : 93
pays / regions / villes : 6 / 16 / 16
```

## 20.6 Décisions

| Décision | Source | Justification |
|---|---|---|
| `country`/`region`/`city` factorisés dans le Core, en camelCase anglais | Base réelle `zylo_liquid` (tables `pays`/`regions`/`villes`) + règle de factorisation `instruction_2...md` §3/§11 | Donnée géographique universelle, exactement l'exemple donné par l'instruction elle-même |
| `HolykellAccount`/`Station` référencent `organizationId` (Core, déjà existant) au lieu de recréer une table `proprietaire` | `organization` déjà implémentée en Phase 6 du socle Zylo Office (Organization → User → Role → Permission) | Un "propriétaire de réseau de stations" est, structurellement, une organisation-tenant au sens déjà défini par le socle — créer une seconde table "propriétaire" dupliquerait ce que le Core fait déjà (règle §3 : ne pas dupliquer une donnée commune dans un module) |
| `societes`, `reseaux`, `proprietaires` (tel quel), `users` (tel quel), `user_station_access`, `user_sessions`, `audit_logs` **non implémentés dans cette phase** | Recoupement direct avec `organization`/`user`/RBAC déjà existants dans le Core | Voir §7 — classification "À VALIDER", décision architecturale nécessitant une validation humaine explicite avant tout code, conformément à la règle absolue de l'instruction ("NE DÉCIDE PAS ARBITRAIREMENT") |
| Colonnes géographiques `city`/`region` en texte libre de `stations` (schéma source) remplacées par `cityId` (FK normalisée) | Base réelle testée, plus avancée que le schéma source sur ce point précis (§20.5) | L'instruction demande explicitement de ne pas supposer que le fichier SQL est la version finale ; la base réellement testée fait foi quand elle diverge |
| Fonctions PL/pgSQL et colonnes calculées non portées | `instruction_2...md` §18 (interdiction explicite de réimplémenter des algorithmes) | Une fonction de conversion, un trigger de checksum ou d'audit sont de la logique métier, pas de la structure |
| Partitionnement de `tankMeasurement` différé | Limite technique de SQLAlchemy déclaratif + absence d'urgence tant que le volume réel du nouveau système est nul | Documenté comme dette technique à traiter avant mise en production, pas oublié |

## 20.7 Points à confirmer

### Classification en attente de décision humaine (Catégorie C — « À VALIDER »)

| Table (schéma source) | Pourquoi elle ne peut pas être classée sans arbitrage |
|---|---|
| `proprietaires` | Recouvre conceptuellement `organization` (Core, déjà implémentée). Deux options : (a) ne jamais créer cette table, les modules Zylo Liquid référencent directement `organizationId` (déjà fait dans le code de cette phase) ; (b) créer une extension `zyloLiquidOrganizationProfile` portant les champs spécifiques (`subscriptionPlan`, `taxId`...) liée 1-1 à `organization`. Décision (a) déjà appliquée par défaut dans le code de cette phase faute d'extension demandée — à confirmer explicitement. |
| `users` | Recouvre `user`/RBAC (Core, déjà implémenté : rôles scopés par organisation via `userRole`). Mais `users` porte des champs absents du Core (`pin_hash` pour connexion tablette pompiste, `employee_number`) et des rôles métier (`gerant`/`pompiste`/`maintenance`/`finance`/`auditeur`/`hse`) qui ne sont pas des permissions RBAC génériques mais des rôles opérationnels de station. Décision à prendre : étendre le RBAC Core avec ces rôles comme `Role`/`Permission` standards du module Zylo Liquid, ou garder un mécanisme d'identification spécifique (PIN tablette) en plus du Core. **Non implémenté dans cette phase.** |
| `user_station_access` | Dépend entièrement de la décision sur `users` ci-dessus — table de droits scopés par station, à remodeler soit via le RBAC Core (scope = station comme "org unit"), soit comme extension Zylo Liquid. |
| `user_sessions` | Recouvre le mécanisme JWT access/refresh déjà implémenté dans le Core (`auth/`, table `refreshToken`). La table source ajoute une notion de session tablette pompiste (durée 16h) que le Core ne modélise pas explicitement aujourd'hui. |
| `audit_logs` | `grande_phases.md` §5.3 prévoit déjà une table `auditLog` au Core (pas encore implémentée à ce jour). Le schéma source a un besoin d'audit trigger générique très proche. Décision à prendre : implémenter `auditLog` au Core maintenant (bénéficierait à tous les modules) ou dans Zylo Liquid en attendant. |
| `societes` | Entité juridique générique (raison sociale, RCCM, capital social) — pourrait bénéficier à un futur module CRM/Comptabilité comme "tiers légal", donc candidate Core, mais son seul usage actuel observé est de structurer `proprietaires`/`reseaux`/`stations` de Zylo Liquid. Pas assez de preuve d'un besoin réellement transverse pour trancher. |
| `reseaux` | Marque/réseau de stations (segment, couleur, logo) — spécifique au commerce de détail carburant dans son contenu actuel (`segment` premium/standard/discount, `couleur_primaire`). Probable Zylo Liquid, mais dépend de la décision sur `societes`. |

**Aucune de ces 7 tables n'a été créée dans cette phase.** Les tables Zylo
Liquid déjà créées (§20.4) ne référencent aucune d'entre elles — seul
`organizationId` (Core existant) est utilisé, ce qui n'anticipe ni ne bloque
la décision à venir.

### Autres points ouverts

- Le partitionnement mensuel de `tankMeasurement` doit être implémenté avant
  tout import de volume réel (voir §20.2).
- Les données de référence géographiques (`country`/`region`/`city`) ne sont
  pas encore seedées dans le nouveau Zylo Office — à faire en Phase 2 ou via
  un script de données de référence dédié, en reprenant les 6 pays/16
  régions/16 villes confirmés dans la base réelle.
- Les vues du schéma source (`v_tank_current_state`, `v_reseau_proprietaire`,
  etc.) encapsulent des calculs (interpolation, agrégations) — non portées,
  à reconstruire en Phase 2 comme requêtes applicatives plutôt que comme
  vues SQL, une fois les tables des couches 3-7 tranchées.

---

# Rapport final (§23 de l'instruction)

### Base de référence

- Fichier SQL utilisé : `zylo_liquid_prototype/schema_complet_base_de_donnees.sql` (3183 lignes, lu intégralement).
- Base PostgreSQL analysée : `zylo_liquid` (locale, 38 relations dont 8 partitions de `tank_measurements`).
- Différences trouvées : 5 tables ajoutées (`pays`, `regions`, `villes`, `societes`, `reseaux`), 1 vue ajoutée, extensions sur `stations` (13 colonnes) et `users` (3 valeurs de rôle) — détail complet en §20.5.

### Tables

```
Nombre total identifié (schéma + base réelle, hors vues/partitions) : 30
Nombre Core (implémenté)                                            : 3  (country, region, city)
Nombre Zylo Liquid (implémenté)                                     : 8
Nombre à confirmer (non implémenté, décision humaine requise)       : 7  (proprietaires, users,
                                                                          user_station_access, user_sessions,
                                                                          audit_logs, societes, reseaux)
Nombre Zylo Liquid restant, non bloqué par une tension Core mais
non implémenté dans cette passe (couches 4-7, dépendent des tables
à confirmer via leurs FKs)                                          : 12 (price_history, shifts,
                                                                          shift_meter_readings,
                                                                          shift_cash_declarations,
                                                                          delivery_notes,
                                                                          delivery_reconciliations,
                                                                          reconciliations, alerts,
                                                                          sync_logs, system_config,
                                                                          credit_customers, credit_ledger)
```

### Données communes (factorisées)

`country`, `region`, `city` — créées, testées, indépendantes de Zylo Liquid
(vérifié : un pays s'insère sans qu'aucune table Zylo Liquid existe).

### Zylo Liquid

`zyloLiquidHolykellAccount`, `zyloLiquidHolykellDeviceRegistry`,
`zyloLiquidTankMeasurement`, `zyloLiquidFuelProduct`, `zyloLiquidStation`,
`zyloLiquidTank`, `zyloLiquidTankSensorMapping`, `zyloLiquidTankCalibrationPoint`.

### Problèmes

- 7 tables ne peuvent pas être classées sans décision humaine (recoupement
  avec le Core déjà existant — voir §20.7). C'est le problème principal de
  cette phase, et la raison pour laquelle les couches 3 à 7 du schéma source
  ne sont pas encore portées.
- Partitionnement et fonctions PL/pgSQL du schéma source volontairement non
  reproduits (hors périmètre "base de données seule").

### Modifications

Fichiers créés :
- `app/shared/geo.py` (Country, Region, City)
- `app/modules/__init__.py`, `app/modules/zylo_liquid/__init__.py`, `app/modules/zylo_liquid/models.py`
- `alembic/versions/0240c128e5de_core_geo_tables_and_zylo_liquid_layers_.py`
- `phase_1_database.md` (ce fichier)
- `docs/modules/zylo-liquid/phase-1-database.md`, `docs/README.md`

Fichiers modifiés :
- `alembic/env.py` (imports des nouveaux modules pour l'autogénération)

Aucun fichier métier existant modifié.

### Validation

```
BASE PARTIELLEMENT PRÊTE POUR LA PHASE 2
```

Les couches 1-2 (télémétrie + référentiel) et le socle géographique Core
sont créés, contraints (FK + CHECK vérifiés en réel), commentés et testés
sans régression sur la suite pytest existante (13/13). **Les couches 3 à 7
(propriétaires/utilisateurs/quarts/livraisons/réconciliation/alertes/audit/
crédit) restent bloquées** tant que la classification Core/Zylo Liquid des 7
tables du §20.7 n'a pas été validée explicitement — les implémenter avant
cette décision risquerait de dupliquer le Core ou de devoir être réécrit.
