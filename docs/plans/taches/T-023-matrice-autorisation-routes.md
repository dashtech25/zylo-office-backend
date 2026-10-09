# T-023 : Matrice d'autorisation et inventaire des routes protégées

- **Statut** : À vérifier · **Priorité** : P2 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : test
- **Branche suggérée** : `test/T-023-matrice-autorisation` · **Base de test** : `zylo_t023_test` · **Ports** : back 3123
- **Dépendances** : T-010, T-019
- **Décisions requises** : `securite/catalogues-publics.md` (recommandation : authentifiés)

## Objectif
Un test parcourt les routes FastAPI et échoue si une route métier n'a ni garde d'appartenance ni permission. Une matrice écrite à la main (utilisateur × organisation × module × action) sert de référence.

## Problèmes résolus
- IAM-013, IAM-018 (tests d'isolation insuffisants), IAM-020 (catalogues publics), REV-S-23 (critère « aucun changement de comportement » contradictoire)

## Dépendances : justification
T-010 (gardes en place), T-019 (garde-fous). Ne modifie aucun comportement métier.

## Fichiers / modules concernés
- `tests/test_route_inventory.py` (créé), `tests/test_authorization_matrix.py` (créé)
- Liste d'exceptions publiques : `/health`, `/`, clé VAPID publique, routes signées de téléchargement. Catalogues : authentifiés (IAM-020) si la décision est confirmée.

## Stratégie
1. Parcourir `app.routes`, extraire les dépendances, marquer les routes sans garde.
2. Liste d'exceptions dans un fichier unique, chaque entrée justifiée et datée.
3. Matrice : cas écrits à la main, pas générés.
4. `GET /modules` et `GET /billing/plans` deviennent authentifiés si la décision est confirmée : changement de comportement limité à ces deux routes, écrit explicitement.

## Tests attendus
- Test d'inventaire vert ; chaque exception listée.
- Matrice : au moins 20 cas (3 organisations de test, 3 modules, 3 niveaux de droits).

## Critères d'acceptation
- Aucune route métier sans garde.
- Liste d'exceptions publiée dans `docs/architecture/securite/routes-publiques.md`.
- Changements de comportement limités aux routes listées ci-dessus.

## Risque et retour arrière
Faible pour le code. Le test d'inventaire peut échouer massivement au début : liste d'exceptions datée, réduite à chaque tâche.

## Livrable documentaire
- `docs/architecture/securite/routes-publiques.md` (créé)
- `docs/questions/securite/catalogues-publics.md`

## Parallélisable avec
T-017, T-018, T-020, T-021 (tests seulement).
