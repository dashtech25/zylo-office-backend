# Endpoints 14 à 16 : devises, prix, valeur monétaire

> Découpé depuis [`docs/archive/zylo-liquid/phase-2-api.md`](../../../archive/zylo-liquid/phase-2-api.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

### Endpoint 14 — Devises et taux de change (Core, `currencies`/`exchange-rates`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre
7.1-7.2. **Premier endpoint Core, pas Zylo Liquid** — routes non préfixées
`/zylo-liquid`, fichiers dans `app/shared/`.

| Méthode | Route | Permission |
|---|---|---|
| GET | `/api/v1/currencies` | `shared.currency.read` |
| POST | `/api/v1/currencies` | `shared.currency.manage` |
| PATCH | `/api/v1/currencies/{id}` | `shared.currency.manage` |
| GET | `/api/v1/exchange-rates` | `shared.exchangeRate.read` |
| POST | `/api/v1/exchange-rates` | `shared.exchangeRate.manage` |

**Modèles créés** : `Currency`, `ExchangeRate` (`app/shared/currency.py`,
confirmés Core par `niveau_1_base_de_donnees_et_monetisation.md` §17,
§25) — aucune isolation tenant, donnée globale au système.

**Décision de bootstrap des permissions (issue #49)** : le socle n'a pas
de concept de « super-admin plateforme ». Plutôt que d'en inventer un,
les 4 permissions Core (`shared.currency.*`, `shared.exchangeRate.*`)
ont été ajoutées à `OWNER_DEFAULT_PERMISSIONS` (`app/identity/service.py`)
— chaque owner d'organisation peut administrer le référentiel global,
exactement comme il administre déjà `MODULE_MANAGE`/`SUBSCRIPTION_MANAGE`.

**Règles respectées sans invention** :
- `Currency.code` immuable après création (`UpdateCurrencyRequest` ne
  l'expose pas) ; jamais de `DELETE` (référencée potentiellement par un
  pays ou une future ligne de prix).
- `ExchangeRate` toujours une insertion, jamais une correction — aucun
  endpoint `PATCH`/`PUT`, conforme à Point 2 §7.2 (« aucune source n'a
  identifié ce besoin à ce jour »).
- Contrainte `sourceCurrencyId != targetCurrencyId` en base (pas
  seulement en validation applicative).

**Point à valider métier non résolu ici** (`niveau_1_...md` §22, §27,
rappelé explicitement dans Point 2 §7.2) : quelle règle de sélection pour
une consolidation historique multi-devises — non tranché, cet endpoint se
limite à stocker les données nécessaires à chacune des options possibles.

Tests : `tests/test_shared_currency.py` (10 cas). Preuve à 3 niveaux :
`validation_log.md` (aucun algorithme, référentiel pur).

### Endpoint 15 — Prix (`zylo-liquid/prices`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre
7.3-7.5.

| Méthode | Route | Permission |
|---|---|---|
| POST | `/api/v1/zylo-liquid/prices` | `zyloLiquid.priceHistory.create` |
| GET | `/api/v1/zylo-liquid/prices` | `zyloLiquid.priceHistory.read` |
| GET | `/api/v1/zylo-liquid/prices/{id}` | `zyloLiquid.priceHistory.read` |
| PATCH | `/api/v1/zylo-liquid/prices/{id}` | `zyloLiquid.priceHistory.create` |

**Extension de modèle** (`niveau_1_...md` §24) : `PriceHistory` (schéma
source `price_history`, déjà audité en Phase 1) étendu — `price_fcfa`/
`cost_fcfa` remplacés par `priceAmount`/`costAmount` + `currencyId` (Core,
endpoint 14), pour supporter le multi-devise réel du réseau (4 devises
déjà observées sur 22 stations, Phase 1). `createdBy` référence
directement le Core `User` déjà authentifié par JWT — aucune dépendance
sur la tension `users`/`gérant` de Phase 1, qui concerne un besoin
différent (contrat Point 2 §7.3, confirmé).

**Résolution de la devise par défaut** (`_resolve_station_default_currency`) :
`Station.cityId → City → Region → Country.currencyCode` (chaîne déjà
existante, jamais dupliquée) → `Currency` correspondante. Si la chaîne est
incomplète (pas de ville) ou si la `Currency` n'existe pas encore →
erreur explicite (`station_currency_not_resolvable` / `currency_not_found`),
jamais une devise inventée.

**Distinction changement réel / correction, non négociable (Point 2
§7.3-7.4)** :
- `POST /prices` → toujours une insertion. Conflit si une ligne existe
  déjà pour la même station+produit+période (`price_conflict_same_period`,
  409). Date future acceptée et signalée (`isFuture: true`), jamais
  rejetée (prix planifiable à l'avance).
- `PATCH /prices/{id}` → correction ciblée uniquement ; le schéma
  `UpdatePriceHistoryRequest` n'expose ni `effectiveFrom`, ni `stationId`,
  ni `fuelProductId` — aucune autre ligne ne peut jamais être affectée,
  garanti par construction (pas seulement par validation).
- **Même permission pour créer et corriger** (`zyloLiquid.priceHistory.create`)
  — qui a le droit de corriger un prix historique n'est pas tranché
  (`niveau_1_...md` §27, Point 2 §7.4) ; option la plus restrictive par
  défaut, jamais un code de permission distinct et potentiellement plus
  permissif inventé par supposition. Une contradiction sur ce point entre
  Point 3 §14 (rédigé avant le Chapitre 7) et Point 2 §7.4 (rédigé après)
  a été identifiée et corrigée dans Point 3 à l'occasion de cet endpoint.

Tests : `tests/test_zylo_liquid_prices.py` (9 cas, incluant la résolution
de devise via la chaîne géographique réelle). Preuve à 3 niveaux :
`validation_log.md` (aucun algorithme, logique de résolution/contrainte
pure).

### Endpoint 16 — Valeur monétaire (extension de `current-state`/`network/summary`/`network/snapshot`)

Contrat : `Point 2 — Architecture API — Zylo Liquid MVP.md`, chapitre 7.6.
**Aucun nouvel endpoint** — dernier item du Niveau 1 (Point 3 §12/§21) :
champs calculés ajoutés aux réponses des endpoints 7, 9 et 13.

**Résolution du prix** (`_resolve_applicable_price`) : la ligne
`PriceHistory` dont `effectiveFrom` est la plus récente antérieure ou
égale à l'instant demandé — jamais un prix postérieur, jamais le prix
courant en cache pour une date passée. Testé explicitement : un prix
planifié dans le futur n'est jamais utilisé pour l'instant présent
(`test_current_state_monetary_value_uses_price_effective_before_now`).

**`current-state` (endpoint 7)** : `monetaryValue` = volume net (déjà
calculé) × prix applicable, dans la devise de ce prix. Sans prix
applicable → `monetaryValue: null`, `monetaryValueNotCalculableReason`
explicite (`no_applicable_price` / `volume_not_calculable`), jamais un 0
(cohérent avec la règle déjà établie pour le volume, endpoint 7).

**`network/summary` (endpoint 9) et `network/snapshot` (endpoint 13)** :
total monétaire par produit calculé **uniquement si toutes les cuves de ce
produit ont un prix applicable dans une seule et même devise** — sinon la
ligne l'indique explicitement (`mixed_currencies` si plusieurs devises,
`incomplete_pricing` si au moins une cuve n'a pas de prix, jamais une
somme partielle silencieuse). Décision documentée : une agrégation
partiellement calculée serait trompeuse — préférée à une exclusion
silencieuse des cuves sans prix, qui donnerait un total incomplet sans le
signaler. Testé explicitement (`test_network_summary_monetary_incomplete_when_one_tank_has_no_price`).

**Consolidation multi-devises** (paramètre de devise de consolidation sur
`network/summary`/`network/snapshot`) : **non implémentée**, conforme au
contrat — bloquée tant que la règle de sélection du taux de change
historique n'est pas tranchée (`niveau_1_...md` §22, §27).

Tests : `tests/test_zylo_liquid_monetary_value.py` (6 cas). Preuve à 3
niveaux : `validation_log.md` (réutilisation complète de la résolution de
prix, aucun nouvel algorithme physique).
