# T-012 : Limitation de débit et verrouillage progressif de l'authentification

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `feat/T-012-rate-limit-auth` · **Base de test** : `zylo_t012_test` · **Ports** : back 3112
- **Dépendances** : T-002, T-005
- **Décisions requises** : `securite/limitation-authentification.md` (recommandation appliquée)

## Objectif
Limiter les tentatives sur `POST /auth/login`, `/auth/register` et `/auth/refresh`. La limite porte sur le couple (IP, compte) et sur l'IP seule. Un verrou ne bloque jamais un titulaire légitime depuis une IP déjà connue.

## Problèmes résolus
- BCK-004 (P1), IAM-008 (P1), REV-S-07 (verrou par compte utilisable comme déni de service)

## Dépendances : justification
T-002 (configuration validée), T-005 (base de test). Bloque T-013 et T-020 (même zone `app/auth/`).

## Fichiers / modules concernés
- `app/auth/router.py`, `app/auth/service.py`
- `app/core/config.py` (seuils en variables)
- Table `loginAttempt` (migration additive) ou stockage PostgreSQL existant
- `tests/test_auth_rate_limit.py` (créé)

## Stratégie
1. Stockage dans PostgreSQL au départ (pas d'infrastructure supplémentaire), limite par IP en plus, à l'échelle du proxy (`X-Forwarded-For` lu seulement depuis un proxy déclaré).
2. Limite par couple (IP, compte) avec backoff ; limite globale par IP, indépendante du compte. Un verrou par compte est limité en durée et ne bloque pas une IP déjà connue du titulaire.
3. Réponse identique (code, corps, temps) pour compte inconnu et mauvais mot de passe : hachage factice.
4. Journaliser les verrouillages sans enregistrer le mot de passe.

## Tests attendus
- Unitaires : 10 échecs sur un couple (IP, compte) donnent 429 ; compte inconnu et mauvais mot de passe : même corps.
- Intégration : une tentative massive depuis IP A ne verrouille pas le compte pour IP B (test explicite, REV-S-07).
- Intégration : une IP qui dépasse la limite globale reçoit 429, les autres IP ne sont pas touchées.
- Playwright sur build prod : connexion refusée avec message générique.

## Critères d'acceptation
- Brute force bloqué par couple et par IP.
- Aucune différence observable entre compte inconnu et mauvais mot de passe.
- Seuils configurables, documentés dans `docs/process/configuration.md`.

## Risque et retour arrière
Moyen : un verrouillage mal calibré bloque des utilisateurs réels. Retour arrière : désactiver la limite par variable de configuration (valeur documentée), sans revert.

## Livrable documentaire
- `docs/architecture/securite/authentification.md` (créé ou complété)
- `docs/questions/securite/limitation-authentification.md`

## Parallélisable avec
T-006, T-007, T-008, T-011, T-014, T-015 (fichiers distincts).
