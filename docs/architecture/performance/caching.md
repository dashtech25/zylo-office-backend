# Caching — Zylo Liquid

Date : 2026-09-11. Architecture retenue : `phase-2-architecture-decision.md` §3.3 et §3.4 (E hybride
— pas de Redis, pas de push). Voir aussi `data-fetching.md` pour l'adoption React Query et
`cache-invalidation.md` pour le détail clé/TTL/déclencheur par type de donnée.

## 1. Cache client — React Query

Un seul `QueryClient`, monté une fois à la racine (`src/core/api/QueryProvider.tsx:36-52`).
Valeurs réelles, choisies délibérément (commentaire du fichier lui-même) :

| Option | Valeur | Pourquoi |
|---|---|---|
| `staleTime` | `60_000` (60s) | Une donnée < 1 min est servie telle quelle sans aller-retour réseau — fenêtre où la lenteur perçue disparaît en navigation (station A → liste → station A). |
| `gcTime` | `10 * 60_000` (10 min) | Le cache d'un onglet quitté reste disponible pour un retour rapide sans grossir indéfiniment. |
| `refetchOnWindowFocus` | `true` | Revalidation silencieuse quand l'onglet redevient actif, sans jamais bloquer l'affichage du cache existant. |
| `retry` (queries) | 1 (sauf 401 → 0) | Sur une base distante déjà lente, 3 tentatives par défaut aggravent la lenteur perçue ; un 401 ne peut de toute façon pas réussir en retentant. |
| `retry` (mutations) | `false` | Une écriture retentée silencieusement est un risque de double effet, pas un gain de robustesse. |

Portée : ce cache vit uniquement dans le navigateur de chaque utilisateur, par onglet de session
(le `QueryClient` est recréé par `useState(createQueryClient)` à chaque montage du provider).

## 2. Cache serveur — TTL en mémoire du processus

Implémentation : `app/shared/simple_cache.py` (`zylo-office-backend`), classe `TTLCache` — ~25
lignes, pas de dépendance ajoutée (`cachetools` n'est pas dans `requirements.txt`, vérifié avant
d'écrire ce code, cf. docstring du fichier). Statut : **présent dans l'arbre de travail actuel**,
utilisé à trois endroits :

- `app/shared/currency_service.py:14` — `currency_list_cache`, TTL 60s, liste des devises (pas de
  scoping par organisation, la table `Currency` est globale).
- `app/shared/geo_router.py:28` — `_city_list_cache`, TTL 60s, liste des villes (référentiel
  géographique global, pas de `organizationId` sur `City`/`Region`/`Country`).
- `app/modules/zylo_liquid/service.py:24` — `fuel_product_list_cache`, TTL 60s, liste des produits
  carburant, scopée par organisation (clé préfixée `org:{organizationId}:`).

Choix explicite : **pas de Redis**. Justification documentée dans le fichier lui-même et en Phase 2
§3.3 — à l'échelle actuelle (5 stations, tables petites), un cache partagé entre workers n'a aucune
preuve de nécessité ; le process tourne actuellement en un seul worker de dev. Limite assumée et
documentée : avec plusieurs workers/instances, chaque worker aurait sa propre copie et pourrait
servir une valeur légèrement différente pendant la fenêtre TTL — acceptable pour du référentiel
quasi statique avec TTL court, à revisiter seulement si la mise à l'échelle horizontale devient
réelle (non le cas aujourd'hui).

TTL choisi à 60s pour s'aligner explicitement sur le `staleTime` de 60s côté React Query
(`simple_cache.py`, commentaire du module) — les deux couches expirent ensemble, pas de dérive entre
« ce que le client pense frais » et « ce que le serveur sert de son cache ».

## 3. Ce qui n'est explicitement PAS caché

- **`get_tank_current_state` / `get_station_current_state`** (`service.py:1379,1388`) — état courant
  des cuves (niveau, volume, valeur monétaire). Recalculé à chaque requête. Une valeur périmée ici
  serait directement visible par un opérateur sur le terrain (niveau de cuve affiché faux) — le
  risque métier d'une donnée périmée dépasse largement le coût de recalcul, une fois le N+1 éliminé
  (Phase 1 §2.1 / Phase 2 §3.1).
- **`get_network_cash_summary` / `get_station_cash_detail`** (`service.py:3619,3717`) — calculs de
  caisse. Une valeur de caisse en cache serait un risque direct d'erreur comptable si elle ne
  reflète pas une vente ou un ajustement tout juste enregistré. Toujours recalculé.
- **`get_network_summary`** (`service.py:1464`) — agrégat réseau construit à partir des états courants
  ci-dessus ; hérite de la même contrainte de fraîcheur.

Principe général : tout ce qui est **calculé à partir de données qui changent à chaque
transaction/mesure** reste toujours recalculé côté serveur ; seul le **référentiel quasi statique**
(produits carburant, villes, devises — modifié par un formulaire de configuration, rarement) passe
par le cache TTL.
