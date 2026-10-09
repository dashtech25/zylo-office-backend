# T-015 : Dépendances CVE, OpenAPI désactivé hors développement, CORS restreint

- **Statut** : Terminée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `chore/T-015-dependances-api` · **Base de test** : `zylo_t015_test` · **Ports** : back 3115
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
Réduire la surface d'attaque sans changer le comportement métier : dépendances sans CVE connue, documentation OpenAPI désactivée hors développement, CORS restreint, identifiants de démonstration retirés du dépôt. Le conteneur, les routeurs et les routes de démonstration sont traités par T-051.

## Problèmes résolus
- BCK-009 (P1, `python-jose` 3.3.0, `Pillow` 11.0.0, dépendances de test en production), BCK-010 (partie identifiants de démo), BCK-014 (P2, OpenAPI public), BCK-022 (P3, CORS), BCK-023 (P3), REV-S-03 (littéraux de développement suivis), REV-S-11 (critère « aucune CVE » non vérifiable)

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-002 (ordre de fusion) ; T-005 (confort).

## Fichiers / modules concernés
- `requirements.txt` ; `requirements-dev.txt` (créé)
- `app/main.py` (`docs_url`, `openapi_url`, CORS)
- `scripts/bootstrap_demo_org.py` (mot de passe lu depuis l'environnement)
- `tests/conftest.py`, `.github/workflows/ci.yml` (littéraux remplacés par des variables, secrets GitHub)
- `app/core/config.py` (valeur de repli de `DATABASE_URL` supprimée)

## Stratégie
1. `pip-audit` dans un environnement propre (T-005) ; sortie jointe au document `surface-api.md`.
2. Mise à jour de `python-jose` et `Pillow` ; tests de connexion, refresh et rejet de jeton mal signé avant et après.
3. Séparer les dépendances de développement.
4. OpenAPI désactivé si `ENVIRONMENT` n'est pas `development`.
5. CORS : méthodes et en-têtes explicites ; origines lues depuis la configuration (T-003).
6. Recenser tous les littéraux de secret (`git grep`), les remplacer par des variables d'environnement, et tourner les identifiants si le même mot de passe sert ailleurs (lien avec `questions/securite/rotation-credentials.md`).

## Tests attendus
- `pip-audit` sans CVE connue sur les dépendances de production, sortie consignée.
- `GET /docs` et `/openapi.json` : 404 hors développement.
- `OPTIONS` avec une méthode non listée : refusé.
- Connexion, refresh, et rejet d'un jeton mal signé : identiques avant et après la mise à jour.

## Critères d'acceptation
- Sortie `pip-audit` jointe à `surface-api.md` ; aucune CVE connue sur les deux bibliothèques citées.
- Aucun identifiant en dur dans le dépôt (contrôle `git grep` scripté).
- OpenAPI absent hors développement.

## Risque et retour arrière
Moyen : `python-jose` et `Pillow` peuvent changer d'API. Retour arrière : revert de la mise à jour de dépendance, seule partie non additive.

## Livrable documentaire
- `docs/architecture/securite/surface-api.md` (créé)
- `docs/process/configuration.md` (mise à jour)

## Parallélisable avec
T-006 à T-014 (fichiers distincts ; `app/main.py` séquencé avec T-028 et T-029).
