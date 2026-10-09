# Base de test zylo_t097_test : à créer avant d'exécuter les tests du lot B-L2/B-L3

- **État** : ouverte (2026-10-09). Bloque l'exécution de la suite DB-dépendante (`pytest`) sur `feat/T-004b-lot-liquid`.
- **Constat** : `zylo_t097_test` n'existe pas (liste des bases : `zylo_t003_test` à `zylo_t096_test` seulement). Aucune autre base n'a été utilisée : `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette` et `zylo_office_test` ne sont jamais la cible d'un test.

## Ce qui reste à faire (manuel, depuis le compte remy)

Recommandation vérifiée : créer la base avec le propriétaire du rôle applicatif, comme `scripts/dev/env_tache.sh creer` (le garde de `tests/conftest.py` n'accepte que `zylo_t<NNN>[a-z]?_test`).

```bash
psql -d postgres -c "CREATE DATABASE zylo_t097_test OWNER zylo_office;"
cd "<dépôt backend>"
export TEST_DATABASE_URL="postgresql+asyncpg://<utilisateur>:<mot-de-passe>@localhost:5432/zylo_t097_test"
.venv/bin/pytest -q
```

`DATABASE_URL` est alignée sur `TEST_DATABASE_URL` par `tests/conftest.py`. Ne jamais recopier l'URL d'un `.env` dans un document : le fichier `.env` du dépôt contient une URL distante avec son mot de passe (voir le point de sécurité ci-dessous).

## Attendu une fois la base créée

- `pytest` : référence remy 618 réussis, 0 échec ; la branche T-034 comptait 666. Après B-L2 et B-L3, le total attendu est plus élevé (tests du snapshot adaptés). Tout écart sur les tests existants est à analyser avant commit.
- Tests les plus sensibles : `test_route_inventory.py`, `test_authorization_matrix.py`, `test_zylo_liquid_facade_lot1.py`, `test_zylo_liquid_station_staff.py`, `test_zylo_liquid_staff_batch.py`.

## Point de sécurité constaté (hors lot)

- `.env` (ignoré par git) contient, en commentaire de la ligne 6, l'URL d'une base distante avec le mot de passe en clair. Il faut le faire tourner (rotation) et retirer la ligne. Non modifié dans ce lot.
