# Catalogue des anti-patterns — Zylo Office / Zylo Liquid

Chaque entrée cite un cas réel trouvé lors de l'audit `phase-1-audit.md`, avec le correctif appliqué ou décidé (`phase-2-architecture-decision.md`). Objectif : ne jamais réintroduire ces patterns, même localement, même "temporairement".

## a) N+1 : boucle par entité au lieu d'un `IN (...)` batché

**Cas réel 1 — `get_tank_current_state` (avant correctif).** Pour chaque cuve, jusqu'à 8 requêtes séquentielles (capteur niveau, calibration, capteur eau, capteur température, produit, prix station, prix réseau par défaut — lui-même une chaîne station→ville→région→pays→devise —, devise). Avec 13 cuves : ~65-100 allers-retours séquentiels × ~200 ms = 27,4 s mesurés sur `network/summary`.

```python
# FAUX — une requête par cuve, répétée pour chaque sous-donnée
for tank in tanks:
    level = await get_level_sensor(tank.id)
    calibration = await get_calibration(tank.id)
    water = await get_water_sensor(tank.id)
    price = await resolve_price_chain(tank.station_id)  # elle-même 4-6 requêtes
    ...
```

**Correctif appliqué : `get_tanks_current_state_batch`.** Une requête `IN (...)` par type de donnée pour l'ensemble des cuves d'un coup, résolution des prix en mémoire à partir de données déjà chargées.

```python
# JUSTE — une requête par type de donnée, pour toutes les cuves d'un coup
tank_ids = [t.id for t in tanks]
levels = await get_level_sensors_batch(tank_ids)      # 1 requête, IN (...)
calibrations = await get_calibrations_batch(tank_ids)  # 1 requête
prices = await resolve_prices_batch(station_ids)       # résolu en mémoire une fois
```

**Cas réel 2 — `_resolve_applicable_price` par frontière de segment (caisse, non corrigé au moment de l'audit).** `_price_sub_segments_for_sale_window` (service.py ~L3044) rappelle la chaîne complète de résolution prix/devise (jusqu'à 6 requêtes) à **chaque frontière de segment de vente, par cuve, par jour**. Sur 30 jours : timeout (>60 s).

**Correctif décidé : `_CashPriceContext`.** Charger une fois par période demandée l'ensemble des prix/devises applicables, puis résoudre chaque segment en mémoire contre ce contexte pré-chargé, sans requête supplémentaire.

**Pourquoi** : le coût d'un aller-retour réseau vers Neon (~150-270 ms mesuré, plancher physique non lié au code) domine largement le coût de traitement en mémoire. Multiplier ce plancher par le nombre d'entités est le vrai goulot, pas le volume de données.

## b) `limit: 100` sans pagination réelle

**Cas réel** : 43 occurrences côté frontend (Phase 1 §2.1) où une liste est bornée à 100 lignes sans mécanisme de pagination serveur en face (pas de curseur, pas de `total_count`, pas de bouton "suivant" relié à un offset serveur réel).

```ts
// FAUX — un plafond silencieux, pas une pagination
const { data } = await api.get(`/equipements?limit=100`);
// au-delà de 100 lignes pour l'organisation, le reste disparaît sans avertissement
```

```ts
// JUSTE — pagination réelle, l'utilisateur/le code sait qu'il y a plus de données
const { data, total, hasMore } = await api.get(`/equipements?limit=50&cursor=${cursor}`);
if (hasMore) { /* afficher un indicateur, pas un silence */ }
```

**Pourquoi** : ce n'est pas qu'un problème de vitesse — au-delà de 100 lignes réelles, les données manquantes ne déclenchent aucune erreur. Une organisation qui grossit perd silencieusement des lignes dans ses listes.

## c) `useEffect` + `useState` fetch-on-mount sans cache

**Cas réel** : 41 hooks sur 45 en Phase 1 (seuls 4, dans `station-detail/`, utilisent React Query). Conséquence mesurée : changer d'onglet Aperçu → Pompes → Aperçu redéclenche le fetch à chaque fois (`PumpsTab.tsx:28`, `StaffTab.tsx:20`, `AtgTab.tsx:63`), car les `Tabs` Radix démontent le contenu inactif.

```tsx
// FAUX — pas de cache, refetch à chaque remount du composant
function PumpsTab({ stationId }) {
  const [data, setData] = useState(null);
  useEffect(() => { fetchPumps(stationId).then(setData); }, [stationId]);
  // remonté à chaque changement d'onglet → refetch complet à chaque fois
}
```

```tsx
// JUSTE — React Query, déjà configuré dans le projet (QueryProvider.tsx)
function PumpsTab({ stationId }) {
  const { data } = useQuery({
    queryKey: ["pumps", stationId],
    queryFn: () => fetchPumps(stationId),
    staleTime: 60_000, // config déjà saine dans le projet, juste pas adoptée partout
  });
}
```

**Pourquoi flag "à ne jamais réintroduire"** : l'infrastructure React Query existe déjà et sa config est correcte (Phase 2 §3.4) — le seul travail restant est l'adoption. Tout nouveau hook écrit en `useEffect`+`useState` brut est une régression consciente, pas un oubli excusable.

## d) Un seul `loading` global bloquant toute la page

**Cas implicite du pattern (c)** : un composant page qui attend que toutes ses sections soient chargées avant d'afficher quoi que ce soit, au lieu de laisser chaque widget indépendant afficher son propre état.

```tsx
// FAUX
function Dashboard() {
  const [loading, setLoading] = useState(true);
  // ... un seul spinner plein écran tant que TOUT n'est pas prêt
  if (loading) return <FullPageSpinner />;
}
```

```tsx
// JUSTE — chaque widget gère son propre chargement
function Dashboard() {
  return (
    <>
      <NetworkSummaryWidget />  {/* son propre useQuery, son propre skeleton */}
      <AlertsWidget />
      <CashWidget />
    </>
  );
}
```

**Pourquoi** : Phase 2 §3.5 — pas de refonte Suspense/Server Components à ce stade, mais la règle "aucun `loading` global" est exigible dès maintenant sans chantier de réécriture, et déjà largement possible vu que les widgets sont structurellement indépendants.

## e) Sur-interrogation de données quasi statiques à chaque requête

**Cas réel** : aucun cache serveur nulle part (`grep` négatif sur `Cache-Control`, `lru_cache`, `redis`, `cachetools` dans `app/`, Phase 1 §2.1). Des données quasi statiques (produits carburant, villes, devises, config organisation) sont recalculées/relues depuis zéro à chaque requête.

```python
# FAUX — relit la table des devises à chaque appel, alors qu'elle change rarement
async def get_currency(code: str):
    return await db.fetch_one("SELECT * FROM currencies WHERE code = :code", {"code": code})
```

```python
# JUSTE — cache TTL en mémoire du processus (décision Phase 2 §3.3, pas Redis : aucune preuve qu'un cache partagé entre workers soit nécessaire à cette échelle)
_currency_cache: dict[str, Currency] = {}
_currency_cache_ttl = 300  # secondes

async def get_currency(code: str):
    if code in _currency_cache and not expired(code):
        return _currency_cache[code]
    value = await db.fetch_one(...)
    _currency_cache[code] = value
    return value
# invalidation explicite à l'écriture — jamais de donnée périmée servie après modification dans le même processus
```

**Pourquoi pas Redis** : Phase 2 §3.3 — priorité "simplicité avant sophistication" (règle §30 de la mission) ; à revisiter seulement si l'app tourne un jour sur plusieurs workers/instances (limite documentée, pas ignorée).
