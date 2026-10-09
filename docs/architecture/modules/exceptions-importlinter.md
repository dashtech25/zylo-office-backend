# Exceptions et contrats import-linter (T-036)

- **Date** : 2026-10-09. **Tâche** : T-036 (base `base-T004`, branche `refactor/T-036-contrats`).
- **Règle** : aucune exception silencieuse. Chaque `ignore_imports` ajouté dans `.importlinter` porte un commentaire d'intention, et chaque exception est listée ici avec sa date, sa raison et sa résorption. La décision de niveau (`forbidden` en erreur, exceptions datées, réduites à chaque PR) est dans `docs/questions/architecture/contrats-importlinter.md`.

## 1. Contrats en vigueur

`lint-imports` : **13 KEPT, 0 BROKEN** (avant T-036 : 10).

| # | Contrat | Type | Statut T-036 |
|---|---|---|---|
| 1 | zylo_liquid ne dépend jamais des détails internes d'identity/rbac | forbidden | inchangé |
| 2 | zylo_liquid n'accède à Files que via son service public | forbidden | inchangé (1 exception historique) |
| 3 | Files ne dépend jamais de zylo_liquid | forbidden | inchangé |
| 4 | zylo_liquid **et zylo_tanker** n'accèdent à Location que via son service public | forbidden | **étendu** à zylo_tanker (ARC-006) |
| 5 | Location ne dépend jamais de la logique/routes de zylo_liquid ou zylo_tanker | forbidden | inchangé |
| 6 | zylo_liquid, **zylo_tanker** et location n'accèdent à Alertes que via son service public | forbidden | **étendu** à zylo_tanker (ARC-006) |
| 7 | Alertes ne dépend jamais de la logique/routes de zylo_liquid ou zylo_tanker | forbidden | inchangé |
| 8 | app.alerts.models n'importe rien de zylo_liquid/zylo_tanker/location | forbidden | inchangé |
| 9 | Holykell ne dépend jamais de zylo_liquid | forbidden | inchangé |
| 10 | Files/Location/Alertes/Holykell ne s'importent jamais entre eux | independence | inchangé (2 exceptions historiques) |
| 11 | Alertes ne dépend pas de zylo_liquid ni zylo_tanker, hors jointures de portée (ARC-005) | forbidden | **nouveau** (4 exceptions, §2) |
| 12 | Location ne dépend pas de zylo_liquid ni zylo_tanker, hors dépendances documentées (ARC-005/006) | forbidden | **nouveau** (6 exceptions, §2) |
| 13 | Les modules métier (zylo_liquid, zylo_tanker) ne forment aucun cycle | acyclic_siblings (`ancestors = app.modules`) | **nouveau** |

## 2. Exceptions posées dans T-036

Chaque ligne correspond à un `ignore_imports` de `.importlinter`.

| Import toléré | Contrat | Raison | Référence | Résorption |
|---|---|---|---|---|
| `app.alerts.service -> app.modules.zylo_liquid.models` | 11 | Jointure de portée (`Station`, `Tank`, `Truck`) de `list_alerts` et `_get_alert_and_tank`. Déjà documentée dans `app/alerts/service.py`. Supprimer le couplage demande un identifiant d'organisation dénormalisé sur `Alert` (migration) ou un type partagé : trop risqué pour T-036. | ARC-005 | Lot dédié : `organizationId` sur `Alert` (ou type partagé), puis suppression de l'exception. |
| `app.alerts.service -> app.modules.zylo_tanker.models` | 11 | Même raison, pour `Vessel`. | ARC-005 | Même lot. |
| `app.location.service -> app.modules.zylo_liquid.models` | 12 | `Truck` pour le rattachement des positions et arrêts à un camion (contrôle `TRUCK_READ`). Dépendance délibérée documentée dans `app/location/service.py`. | ARC-005 | Type partagé ou identifiant, lot dédié. |
| `app.location.service -> app.modules.zylo_liquid.permissions` | 12 | `TRUCK_READ`, constante de permission de zylo_liquid utilisée pour le contrôle d'accès. | ARC-005 | Déplacer les constantes de permission partagées (`app/shared/permissions.py`, ARC-018) ou accepter la constante. |
| `app.location.service -> app.modules.zylo_tanker.models` | 12 | `Vessel`, comme `Truck` ci-dessus. | ARC-006 | Même lot que `Truck`. |
| `app.location.service -> app.modules.zylo_tanker.permissions` | 12 | `VESSEL_READ`, comme `TRUCK_READ`. | ARC-006 | Même lot que `TRUCK_READ`. |
| `app.modules_registry.service -> app.modules.zylo_liquid.roles_seed` (x2 contrats) | 11, 12 (et contrat `capabilities-never-import-each-other` déjà existant) | Chaîne transitive : `alerts.router` / `location.router` -> `modules_registry.service` (`require_module_active`) -> `roles_seed` d'un module, importé paresseusement à l'activation. Le socle dépend encore d'un module. | ARC-008 | Registre de seeders injecté (`register_module_seeder`) appelé depuis `app/main.py`. |
| `app.modules_registry.service -> app.modules.zylo_tanker.roles_seed` (x2 contrats) | 11, 12 | Même raison pour zylo_tanker. | ARC-008 | Même lot. |

Pourquoi ces exceptions et pas une correction de code : les jointures de portée et les constantes de permission sont des dépendances de types ; les supprimer impose une migration de schéma ou la création d'un paquet de types partagé. Pour T-036, le risque (perte de scope sur les alertes et les arrêts) dépasse le bénéfice ; ces points sont donc documentés, datés et pilotés par les ARC correspondants.

## 3. Violations réelles hors base-T004 (snapshot wip)

Le paquet `app/notifications` et le module `app/modules/zylo_tanker/dev_seed.py` n'existent pas dans `base-T004` : ils ne sont que dans le commit `a7329ec` de la branche `wip/2026-10-08-snapshot-backend` (snapshot non encore découpé en lots, T-004b). Vérification faite en copiant l'arbre `app/` de `a7329ec` dans un dossier temporaire et en lançant `lint-imports` avec le `.importlinter` de T-036 :

| Violation constatée | Contrat | Résultat | Correction attendue |
|---|---|---|---|
| `app/modules/zylo_tanker/dev_seed.py:21` : `-> app.location.models` (écriture directe de `TruckPositionPing`) | 4 (étendu à zylo_tanker) | **BROKEN** | Faire passer l'insertion par une fonction publique de `app.location.service` (même comportement), dans le lot zylo_tanker de T-004b. |
| `app/notifications/service.py:31` : `-> app.modules.zylo_liquid.models` (`Station`, `Truck`) | ARC-007 (contrat à poser) | **BROKEN** | Passer par l'événement `AlertCreated` enrichi de `organizationId` (ARC-007) ou par un service public de zylo_liquid ; dans le lot notifications de T-004b. |

Décision : le contrat `notifications-never-imports-zylo-liquid` n'est **pas posé** dans `.importlinter` de T-036. `import-linter` échoue à la lecture (`Module 'app.notifications' does not exist`) quand la source est absente. Le contrat (texte ci-dessous) est à poser avec le lot notifications, en même temps que la correction :

```ini
[importlinter:contract:notifications-never-imports-zylo-liquid]
name = Notifications ne dépend jamais de zylo_liquid (ARC-007)
type = forbidden
source_modules =
    app.notifications
forbidden_modules =
    app.modules.zylo_liquid
```

Le contrat de `zylo_tanker` vers `location.models` est, lui, déjà en vigueur : il attrape le dev_seed dès qu'il est réintroduit.

## 4. Contrats hors périmètre T-036 (dette connue)

- **Cycles du socle, ARC-009** : `core` -> `identity` (`core/security.py` importe `identity.models.User`), `identity` <-> `rbac`, `rbac` <-> `shared`, `shared` -> `core`. Non contractés dans T-036 ; contrat à poser après le déplacement du type `User` (`core/types`) et l'inversion de `shared/currency_router`.
- **FastAPI dans les services, ARC-010** : `rbac/service.py`, `identity/service.py`, `modules_registry/service.py` importent FastAPI. Non traité.
- **Lectures d'environnement hors `Settings`, ARC-017** : `location/service.py:340`. Non traité.
- **`shared/permissions.py`** : les constantes partagées restent à déplacer (ARC-018), voir §2.

## 5. Points à trancher (propriétaires)

- Propriétaire fonctionnel de `files`, `location`, `alerts`, `integrations/holykell` : non désigné dans le dépôt (voir `capacites-proprietaires.md`).
- Ordre des lots : jointure de portée `Alert` (ARC-005) et registre de seeders (ARC-008) sont les deux exceptions à résorber en priorité.
- Lot notifications et lot zylo_tanker de T-004b : à corriger avec les violations du §3 avant de poser le contrat.

## 6. Retour arrière

Pour repasser un contrat en avertissement pendant une correction, retirer la section concernée de `.importlinter` dans la même PR et réinscrire la ligne correspondante dans ce document.
