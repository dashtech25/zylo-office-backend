# Guide développeur — Performance (Zylo Office / Zylo Liquid)

Règles issues des 15 problèmes mesurés en `phase-1-audit.md` et de l'architecture retenue en `phase-2-architecture-decision.md`. Chaque règle a une cause réelle documentée dans `anti-patterns.md` — s'y référer en cas de doute sur le "pourquoi".

## 1. Frontend — fetch de données

**Interdit** : `fetch()`/`axios` directement dans un composant via `useEffect`+`useState`, sans passer par React Query.
**Interdit** : refetch complet après chaque petite modification (ex. relire toute une liste après avoir modifié une seule ligne) — invalider/mettre à jour seulement la donnée concernée (`queryClient.setQueryData` ou invalidation ciblée par `queryKey`).
**Interdit** : charger 1000 lignes alors que 20 sont affichées à l'écran — paginer côté serveur avec un vrai curseur/offset, jamais un `limit` fixe sans indication qu'il reste des données (voir `anti-patterns.md` §b).
**Interdit** : un seul état `loading` bloquant toute une page — chaque section/widget indépendant a son propre état de chargement (`anti-patterns.md` §d).
**Interdit** : appeler le même endpoint plusieurs fois dans le même écran pour des vues légèrement différentes des mêmes données (ex. `CaisseScreen.tsx` appelant `useNetworkCash` 3 fois, Phase 1 §2.2) — un seul fetch, dérivations calculées côté client ou en mémoire.

**Obligatoire** : toute nouvelle donnée fetchée doit définir explicitement, avant merge :
- **source** — quel endpoint, quel service backend
- **cache** — React Query avec quel `queryKey` (doit inclure toutes les variables dont dépend la donnée, ex. `["pumps", stationId]`)
- **fraîcheur** — `staleTime` explicite (la config projet par défaut est `staleTime: 60s`, `gcTime: 10min`, `refetchOnWindowFocus: true` — `QueryProvider.tsx:36-52` ; ne pas la redéfinir sans raison)
- **pagination** — curseur/offset réel si la liste peut dépasser ~50-100 lignes, pas un `limit` silencieux
- **invalidation** — quelle mutation invalide quelle `queryKey`, explicitement listé
- **stratégie de chargement** — le composant affiche-t-il un skeleton local, ou dépend-il d'un parent ? Jamais un spinner plein écran par défaut

**Obligatoire** : toute nouvelle requête coûteuse (agrégat multi-entités, période multi-jours, jointures multiples) doit être mesurée avant merge, avec la méthode décrite dans `benchmark.md`, et comparée au budget correspondant dans `performance-budget.md`.

## 2. Backend — requêtes DB

**Interdit** : une requête DB à l'intérieur d'une boucle Python sur une liste d'entités (`for tank in tanks: await db.fetch(...)`) — voir le cas réel `get_tank_current_state` dans `anti-patterns.md` §a (27,4 s mesurés, causés exactement par ce pattern).
**Interdit** : résoudre une chaîne de données liées (prix → station → ville → région → pays → devise) à répétition pour chaque itération d'un calcul, au lieu de la charger une fois et de la garder en mémoire pour le reste du calcul (cas `_resolve_applicable_price`, `anti-patterns.md` §a).
**Interdit** : ajouter du cache (mémoire ou Redis) pour "masquer" un N+1 au lieu de le corriger à la source — Phase 2 a explicitement rejeté cette approche (architecture C, §2) : le nombre de requêtes doit être O(1) en nombre d'entités, pas simplement moins souvent exécuté.

**Obligatoire** : toute nouvelle requête coûteuse (touchant potentiellement des milliers de lignes, ou appelée dans une boucle sur des entités métier) doit être vérifiée par `EXPLAIN (ANALYZE, BUFFERS)` avant merge — méthode dans `benchmark.md` §2. Vérifier en particulier l'absence de `Rows Removed by Filter` élevé (signe d'index manquant).
**Obligatoire** : toute nouvelle table à forte volumétrie prévisible (télémétrie, logs, historique) doit avoir son index de requête principal pensé dès la création (ex. `(clé_étrangère, colonne_de_tri DESC)`), pas ajouté après coup — le cas `TankMeasurement` documentait déjà le besoin de partitionnement dans le modèle lui-même et ne l'a jamais implémenté (Phase 1 §2.1, ligne 21).

## 3. Checklist — avant d'ajouter un nouvel appel API (frontend)

1. Cette donnée est-elle déjà fetchée ailleurs sur cet écran ? Si oui, réutiliser le `queryKey` existant plutôt que dupliquer l'appel.
2. Quel `staleTime` a du sens pour cette donnée ? (quasi statique → plusieurs minutes ; temps réel perçu → court, mais jamais 0 sans raison)
3. La liste retournée peut-elle dépasser ~50-100 lignes en production dans 6 mois ? Si oui, pagination réelle obligatoire dès maintenant, pas "à ajouter plus tard".
4. Ce composant peut-il être démonté/remonté sans perdre son cache (changement d'onglet, navigation retour) ? Si oui, s'assurer que React Query (pas `useState` local) porte les données.
5. Cet écran affiche-t-il un `loading` par section ou un seul global ? Si un seul global existe déjà sur la page, ne pas y ajouter une dépendance de plus sans le découper.

## 4. Checklist — avant d'ajouter une boucle sur des entités appelant la DB (backend)

1. Cette boucle peut-elle être remplacée par une seule requête `WHERE x IN (...)` ? (quasi toujours oui pour des lectures)
2. Si la boucle résout une chaîne de données liées (prix, devise, hiérarchie géographique...), ces données peuvent-elles être chargées une fois en amont et tenues en mémoire (dict indexé par clé) plutôt que re-résolues à chaque itération ?
3. Combien d'entités cette boucle traite-t-elle aujourd'hui, et combien dans un scénario de croissance raisonnable (×5, ×10) ? Un P0 de Phase 1 était déjà sévère à 13 cuves — ne pas attendre que ça devienne visible en production pour corriger un pattern connu.
4. Cette requête a-t-elle été mesurée (`benchmark.md`) et comparée au budget (`performance-budget.md`) correspondant à sa catégorie ?
5. Si la réponse à 1-2 est "non, ce n'est pas possible" — documenter explicitement pourquoi dans le code (commentaire), pas seulement l'écrire et espérer que personne ne demande.

## 5. Ce qui n'est volontairement pas exigé (voir Phase 2 §4)

Pas de WebSocket/SSE, pas de Redis, pas de migration Server Components pour le fetch, pas de partitionnement immédiat de `TankMeasurement` — ces choix sont documentés et justifiés dans `phase-2-architecture-decision.md` §4, pas oubliés. Ne pas les réintroduire par réflexe "c'est plus moderne" sans un besoin mesuré qui dépasse ce que l'architecture actuelle (§1-2 ci-dessus) peut couvrir.
