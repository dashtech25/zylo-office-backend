# Real-time — décision et état actuel

Date : 2026-09-11. Décision source : `phase-2-architecture-decision.md` §4 — « Pas de WebSocket/SSE ».

## 1. La décision

Aucun mécanisme de push (WebSocket, Server-Sent Events) n'est en place ni prévu à ce stade.
Justification (Phase 2 §4, citée) : « l'ingestion télémétrie arrive déjà par polling 5s
(`sync_holykell_live.py`), et aucun écran actuel n'affiche de promesse de fraîcheur sub-5s.
Introduire du push serait de la sophistication sans besoin prouvé (règle §30 : ne jamais choisir une
techno parce qu'elle est moderne). »

C'était déjà identifié comme problème ouvert en Phase 1 (§3, ligne 15 : « Pas de stratégie temps
réel définie (polling/SSE/WebSocket) », classé P3 — impact futur, pas actuel).

## 2. Ce que « quasi temps réel » signifie concrètement aujourd'hui

Trois couches, chacune avec sa propre fraîcheur — jamais confondues :

1. **Ingestion télémétrie (Holykell → base)** : `scripts/sync_holykell_live.py` interroge l'API
   Holykell (ou son simulateur en dev) en boucle, avec `POLL_INTERVAL_SEC = 5` (ligne 73, vérifié
   dans le fichier à la date de ce document) — `await asyncio.sleep(POLL_INTERVAL_SEC)` en fin de
   boucle (ligne 257). C'est la limite physique de fraîcheur de la donnée capteur : une mesure ne
   peut jamais être plus récente que ~5s dans la base, quel que soit le reste de l'architecture.

2. **Calcul serveur (état courant, caisse)** : `get_tank_current_state`, `get_network_summary`,
   `get_network_cash_summary`, `get_station_cash_detail` (voir `caching.md` §3) sont recalculés à
   chaque requête HTTP, jamais mis en cache — donc jamais de décalage introduit par une couche de
   cache serveur. La fraîcheur de ces endpoints est bornée uniquement par (a) la fraîcheur de la
   télémétrie en base (point 1) et (b) le moment de la requête.

3. **Client** : la donnée n'apparaît à l'écran qu'au prochain fetch — montage de composant, retour
   d'onglet (`refetchOnWindowFocus`), expiration de `staleTime` (60s), ou `invalidateQueries` après
   une mutation locale (voir `cache-invalidation.md` §2). **Il n'y a aucun push serveur → client** :
   si une mesure change côté base pendant qu'un écran est ouvert et inactif, l'utilisateur ne le
   verra qu'au prochain déclencheur ci-dessus — au pire après `staleTime` (60s) s'il reste sur
   l'onglet sans le quitter ni le refocaliser.

Fraîcheur bout-en-bout dans le pire cas actuel : ~5s (ingestion) + jusqu'à 60s (cache client avant
revalidation automatique) si l'utilisateur reste immobile sur un écran déjà ouvert. C'est cohérent
avec le TTL du cache serveur (aligné à 60s, `caching.md` §2) — les trois couches ne dérivent pas les
unes par rapport aux autres.

## 3. Ce que ça exclut, explicitement

- Pas de notification poussée au client quand une alerte se déclenche, une livraison démarre, ou
  une mesure arrive — l'utilisateur doit rouvrir/refocaliser l'écran concerné, ou attendre
  l'expiration naturelle du cache.
- Pas de garantie de fraîcheur sub-5s sur aucun écran : la limite est celle de l'ingestion Holykell,
  pas de l'architecture applicative.

## 4. Quand revisiter cette décision

Seulement si un écran demande explicitement une fraîcheur sub-5s ou un push (ex. un mode
« supervision live » avec alerte sonore immédiate) — avec un besoin mesuré et concret, jamais de
manière préventive. Dans ce cas, réévaluer d'abord si un polling client plus agressif sur cet écran
précis suffit (coût nul en infra) avant d'introduire SSE/WebSocket (nouvelle infra, nouvelle classe
de bugs — reconnexion, état de connexion, fan-out serveur).
