# Cache invalidation — Zylo Liquid

Date : 2026-09-11. Détail par type de donnée des tableaux `caching.md`. Trois mécanismes
d'invalidation coexistent, à deux niveaux (client React Query, serveur `TTLCache`) — jamais mélangés
pour une même donnée.

## 1. Serveur — invalidation à l'écriture (`TTLCache`)

| Donnée | Clé | TTL | Déclencheur d'invalidation |
|---|---|---|---|
| Devises (`currency_list_cache`) | implicite (une seule liste) | 60s | `clear()` complet dans `create_currency` et `update_currency` (`app/shared/currency_service.py:23,41`) |
| Villes (`_city_list_cache`) | `q:{q}:limit:{limit}:offset:{offset}` | 60s | **Aucune** — pas d'endpoint d'écriture sur `City`/`Region`/`Country` dans l'app (vérifié par grep, commenté dans `geo_router.py:20-25`). Le TTL seul borne toute dérive si la donnée change par un autre canal (migration, accès DB direct). |
| Produits carburant (`fuel_product_list_cache`) | `org:{organizationId}:limit:{limit}:offset:{offset}` | 60s | `invalidate_prefix(f"org:{organization_id}:")` dans `create_fuel_product` (`service.py:360`) et `update_fuel_product` (`service.py:384`) — toutes les pages en cache pour cette organisation sont purgées, pas seulement l'entrée exacte modifiée. |

Le `get`/`set` du cache produits carburant vit dans le routeur, pas le service :
`app/modules/zylo_liquid/router.py:263,268` (`list_fuel_products`). C'est le service qui invalide,
car c'est lui qui connaît le moment de l'écriture.

Principe : **jamais de donnée périmée servie après une modification dans le même process** — c'est
la garantie tenue par ce design (Phase 2 §3.3), au prix de la limite multi-worker déjà documentée
dans `caching.md` §2.

## 2. Client — trois mécanismes React Query, jamais confondus

### 2.1 Invalidation déclenchée par mutation (`invalidateQueries`)

Le pattern réel, présent dans 4 hooks (`grep invalidateQueries` sous `src/modules/zylo-liquid/`,
2026-09-11) :

- `src/modules/zylo-liquid/screens/station-detail/useRegulation.ts:72`
- `src/modules/zylo-liquid/screens/station-detail/useDeliveryFlow.ts:87`
- `src/modules/zylo-liquid/screens/station-detail/useSuppliers.ts:67`
- `src/modules/zylo-liquid/screens/trucks/useTrucks.ts:61`

Chacun appelle `queryClient.invalidateQueries({ queryKey })` juste après une mutation réussie
(création/mise à jour), avec la **même `queryKey`** que celle utilisée par le `useQuery` de lecture
correspondant — garantit qu'un prochain rendu du même écran redemande la donnée fraîche au lieu de
continuer à servir le cache jusqu'à expiration du `staleTime`.

### 2.2 Expiration temporelle (`staleTime`)

Par défaut pour tout ce qui n'est pas explicitement invalidé par une mutation : après 60s
(`QueryProvider.tsx:36-52`), la prochaine consultation du composant déclenche une revalidation
silencieuse en arrière-plan (la donnée en cache s'affiche immédiatement pendant ce temps). C'est le
mécanisme de repli pour toute donnée modifiée en dehors du flux de mutation suivi par le hook (ex.
par un autre utilisateur, un autre onglet).

### 2.3 Revalidation au focus (`refetchOnWindowFocus`)

`true` globalement — revient sur l'onglet du navigateur après une absence déclenche une
revalidation en arrière-plan, indépendamment du `staleTime`. Couvre le cas d'un utilisateur qui
laisse l'écran ouvert pendant qu'une donnée change ailleurs (autre utilisateur, autre poste).

## 3. Ce qui n'est jamais invalidé, par construction

`current-state`, `cash/*` (client et serveur) : aucune invalidation à documenter, car aucune donnée
n'est mise en cache à ce niveau — chaque requête recalcule depuis les données transactionnelles
actuelles (voir `caching.md` §3). La question de l'invalidation ne se pose pas pour une donnée jamais
mise en cache.

## 4. Statut de ce document

Les trois entrées serveur (§1) et les quatre entrées client (§2.1) sont vérifiées directement dans
le code à la date ci-dessus, pas déduites. Si un nouveau type de donnée référentielle est ajouté au
cache serveur, ajouter une ligne ici avec sa clé, son TTL et son déclencheur réel — jamais par
supposition.
