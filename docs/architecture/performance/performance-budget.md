# Budget de performance — Zylo Office / Zylo Liquid

Date : 2026-09-11. Dérivé des mesures de `phase-1-audit.md` §2.1 et de l'architecture retenue en `phase-2-architecture-decision.md`. Aucun chiffre ici n'est arbitraire : chacun est justifié contre une mesure réelle ci-dessous.

Au moment de la rédaction, aucun `phase-4-benchmark-results.md` n'existait encore dans ce dossier (vérifié par `ls`). Si un tel fichier apparaît plus tard avec des mesures "après" plus précises que celles listées ici, il devient la source de vérité pour la colonne "actuel" — ce document garde la colonne "budget cible".

## 1. Plancher physique (non négociable)

Mesuré en Phase 1 : connexion TCP/SSL initiale vers Neon (Frankfurt) ~1,2 s ; `SELECT 1` isolé hors logique applicative : 130–270 ms. **Aucun budget ci-dessous ne peut descendre sous ~150 ms par endpoint** — c'est la latence réseau incompressible tant que l'environnement de dev n'est pas co-localisé avec Neon. Un budget de 0 requête = latence connexion seule ; un budget à 1 requête = ~150-270 ms plancher.

## 2. Budgets par catégorie d'endpoint

| Catégorie | Exemple | Mesuré (baseline / après correctif partiel) | Budget cible P95 | Justification |
|---|---|---|---|---|
| Auth / login | login | ~1,2–1,5 s (déduit du plancher connexion + hash + JWT, cohérent avec le plancher Neon mesuré) | **< 2 s** | 1 connexion + vérif mot de passe (bcrypt) + 1-2 requêtes ; laisse une marge de ~500ms-800ms au-dessus du plancher mesuré pour le hachage et la latence réseau utilisateur réel (pas seulement dev→Neon) |
| Liste / détail simple | endpoints CRUD standards (stations, équipements, utilisateurs) | Non chronométré isolément en Phase 1, mais borné par le plancher (~150-270ms) + 1-3 requêtes non batchées typiques | **P95 < 1 s** | Un endpoint simple = 1-3 allers-retours DB. Au plancher mesuré (150-270ms/requête), 3 requêtes séquentielles ≈ 450-810ms ; 1s laisse une marge raisonnable sans autoriser un pattern N+1 à se glisser dedans |
| Agrégat réseau (O(1) requêtes) | `network/summary`, `*/current-state` | 27,4 s avant correctif → 5,3–8,1 s après batching partiel (Phase 1 §2.1, ligne 18) | **P95 < 2 s, indépendant du nombre de stations/cuves** | Le but du batching (`get_tanks_current_state_batch`, Phase 2 §3.1) est de rendre le coût O(1) en nombre de requêtes, pas O(n). 5,3-8,1s aujourd'hui prouve que le batching partiel n'est pas encore complet — le budget de 2s n'est PAS le chiffre actuel, c'est la cible qui **valide** que l'architecture est bien passée en O(1) requêtes. Si l'endpoint dépasse 2s alors que le nombre de requêtes SQL a été vérifié constant, le problème est ailleurs (réseau, taille de payload) ; s'il dépasse 2s ET que le nombre de requêtes croît avec les stations, le batching n'est pas terminé |
| Caisse (jour) | `cash/network-summary` (today) | 34,8–37,9 s (non corrigé au moment de l'audit ; Phase 2 §3.1 indique une correction en cours) | **P95 < 3 s** | Une seule journée = un seul passage dans `_CashPriceContext` par cuve, pas une boucle sur N jours. Budget aligné sur la catégorie "agrégat" (2s) + marge (+1s) car la caisse combine plusieurs cuves et une résolution prix/devise plus lourde que le simple état courant |
| Caisse (7 jours) | `cash/network-summary` (7j) | 45–53 s (non corrigé) | **P95 < 5 s** | Proportionnalité : si le coût par jour est ramené en O(1) requêtes (résolution prix en mémoire, Phase 2 §3.1), 7 jours ne doit plus multiplier linéairement le nombre d'allers-retours réseau, seulement le volume de calcul en mémoire (rapide). 5s = budget jour (3s) + marge pour l'agrégation multi-jours |
| Caisse (30 jours) | `cash/network-summary` (30j) | **timeout (>60s)** avant correctif — cas le plus sévère mesuré | **P95 < 8 s** | C'est le test décisif de l'architecture : passer de "timeout à 30 jours" à "<8s à 30 jours" démontre que le nombre de requêtes ne scale plus avec le nombre de jours × cuves × frontières de segment. Un dépassement de ce budget à 30 jours avec un volume de cuves stable signale un retour au pattern O(n×jours) |

## 3. Budget de payload

Aucune mesure de taille de payload n'a été faite en Phase 1 (l'audit a identifié le goulot comme le nombre d'allers-retours, pas le volume — §5 de `phase-1-audit.md` : "le goulot est le nombre d'allers-retours séquentiels... pas le volume de données transférées"). En l'absence de mesure, budget fixé par prudence raisonnable plutôt qu'inventé au hasard :

- **Aucun endpoint ne doit renvoyer plus de 500 KB non compressés pour le chargement initial d'une page.** À la volumétrie actuelle (13 cuves, 17,8K mesures, 5 stations), aucun écran ne devrait s'en approcher — une liste de 43 endpoints à `limit: 100` (Phase 1 §2.1) sur des entités à quelques dizaines de champs reste largement sous ce seuil. Le budget sert de garde-fou pour la croissance future (plus de stations, plus de cuves, historique de mesures étendu), pas un problème déjà mesuré.
- Corollaire direct du problème #6 de Phase 1 (`limit: 100` × 43 sans pagination réelle) : tant que la pagination serveur réelle n'est pas en place, ce budget de payload est la seule protection contre une réponse qui grossit silencieusement avec le nombre de lignes en base.

## 4. Comment lire ce document

Un budget dépassé n'est pas automatiquement une régression de code — vérifier d'abord si le nombre de requêtes SQL a changé (méthode : `benchmark.md`). Un budget respecté avec un nombre de requêtes qui croît avec les entités est un budget qui va casser au prochain palier de croissance : voir `anti-patterns.md`.
