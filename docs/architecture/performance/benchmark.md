# Méthodologie de mesure de performance

Ce document décrit **comment** reproduire les mesures de `phase-1-audit.md`, pas les résultats eux-mêmes. Pour des résultats, voir `phase-1-audit.md` §2.1 (baseline) et, s'il existe au moment de la lecture, un fichier `phase-4-benchmark-results.md` ou équivalent dans ce même dossier (vérifier avec `ls docs/architecture/performance/`) — ne pas dupliquer ces chiffres ici.

## 1. Mesure HTTP bout-en-bout (chronométrage applicatif)

Technique utilisée en Phase 1 pour les endpoints (`network/summary`, `cash/network-summary`, etc.) :

1. Authentifier une seule fois (POST `/auth/login` ou équivalent) pour obtenir un JWT, réutilisé pour tous les appels suivants — ne pas mesurer le coût de login à chaque itération, sauf si c'est précisément l'endpoint testé.
2. Avec `httpx` en Python (client déjà utilisé dans le projet pour ce type de script — cohérent avec les dépendances backend existantes) :
   - Créer un client `httpx.Client(base_url=..., headers={"Authorization": f"Bearer {token}"})`.
   - Boucler N fois (N ≥ 5 pour amortir la variance réseau, davantage si l'endpoint est rapide) sur l'appel de l'endpoint cible.
   - Chronométrer chaque appel individuellement avec `time.perf_counter()` avant/après l'appel (pas `time.time()` — insensible aux ajustements d'horloge système).
   - Enregistrer chaque mesure en millisecondes, pas seulement une moyenne — Phase 1 a rapporté des plages (ex. "5,3–8,1 s") précisément parce que la variance de contention réseau/pool est significative à cette échelle.
3. Distinguer explicitement "avec contention" (autres requêtes en cours, pool de connexions partagé) et "sans contention" (script seul) — les deux plages ont été rapportées séparément en Phase 1 car elles ne racontent pas la même chose.
4. Ne jamais mesurer un seul appel et l'annoncer comme représentatif — le premier appel après un redémarrage inclut souvent l'établissement de connexion TCP/SSL (~1,2 s mesuré séparément), ce qui fausse la moyenne s'il n'est pas isolé ou répété.

## 2. Mesure au niveau base de données (EXPLAIN ANALYZE)

Technique utilisée en Phase 1 pour prouver l'absence d'index (`TankMeasurement`, §2.1 ligne 21) :

1. Se connecter directement via `asyncpg` (pas via l'ORM SQLAlchemy — on veut voir la requête SQL brute, pas la couche d'abstraction) à l'URL de connexion exposée par `app.core.config.settings` (`DATABASE_URL` ou équivalent défini dans ce module — lire `app/core/config.py` pour le nom exact du champ courant plutôt que de le deviner).
2. Exécuter la requête cible préfixée par `EXPLAIN (ANALYZE, BUFFERS)` — `BUFFERS` est indispensable pour voir les lectures physiques vs cache (`shared hit`/`read`), pas seulement le temps.
3. Lire spécifiquement les lignes `Rows Removed by Filter` (signe d'un index manquant ou mal ciblé — c'est ce qui a révélé le scan quasi complet sur `TankMeasurement` : 17 473 lignes filtrées sur 17 636) et `Execution Time`.
4. Toujours exécuter deux fois : la première mesure inclut potentiellement un remplissage de cache disque/mémoire côté Postgres, la seconde reflète mieux le régime stable.
5. Fermer proprement la connexion asyncpg après usage (`await conn.close()`) — ce sont des scripts d'audit ponctuels, pas un pool applicatif.

## 3. Comptage du nombre de requêtes SQL (pour valider le passage en O(1))

Pour vérifier qu'un endpoint batché (ex. `get_tanks_current_state_batch`) ne régresse pas vers un pattern N+1 : activer temporairement `echo=True` sur le moteur SQLAlchemy concerné (déjà actif par défaut en développement, `app/core/database.py:18`, voir Phase 1 §2.1) et compter les lignes de log par appel d'endpoint. Le nombre de requêtes doit rester constant quand le nombre d'entités (cuves, stations) varie — c'est la définition opérationnelle de "O(1) en nombre de requêtes" utilisée dans `performance-budget.md` §2.

## 4. Génération d'un jeu de données synthétique à l'échelle

Aucun script de seeding pour test de montée en charge n'a été trouvé dans le dépôt au moment de la rédaction (recherche `find . -iname "*seed*synth*" -o -iname "*scale_test*"` infructueuse). Recommandation pour quiconque en écrit un :

- **Toujours créer une organisation de test séparée** (nouvel `Organization` avec son propre `id`), jamais injecter de volumétrie synthétique dans l'organisation de démo réelle utilisée pour les présentations — un jeu de données gonflé fausserait les captures d'écran et démonstrations, et une suppression accidentelle de l'org de test ne doit jamais pouvoir toucher les vraies données.
- Générer un ratio réaliste par rapport à la baseline mesurée (13 cuves / 17,8K mesures pour 5 stations en Phase 1) plutôt qu'un nombre rond arbitraire — viser au moins un ordre de grandeur au-dessus (ex. 50-100 stations, plusieurs centaines de cuves, millions de mesures) pour exercer réellement les budgets O(1) du document `performance-budget.md`.
- Si un script de ce type apparaît dans une session parallèle sous ce même dossier ou ailleurs dans le dépôt, le citer ici par son chemin plutôt que d'en écrire un second.

## 5. Où recoller les résultats

Ce fichier ne contient pas de chiffres de résultats. Un fichier séparé (ex. `phase-4-benchmark-results.md`) est le bon endroit pour toute nouvelle campagne de mesure suivant cette méthodologie — voir `README.md` pour la liste à jour des fichiers du dossier.
