# T-037a : Jetons dans des cookies HttpOnly, partie backend

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `feat/T-037a-cookies-backend` · **Base de test** : `zylo_t037a_test` · **Ports** : back 3137
- **Dépendances** : T-020, T-002
- **Décisions requises** : `securite/stockage-jetons.md` (en attente : infrastructure de même site)

## Objectif
Le backend pose les jetons d'accès et de rafraîchissement en cookies `HttpOnly; Secure; SameSite`, le rafraîchissement restreint au chemin `/auth`. Il accepte cookie **et** en-tête pendant la transition, avec une date de fin fixée. Une protection CSRF accompagne les cookies.

## Problèmes résolus
- FRT-001 (partie backend), BCK-015 (partie backend), IAM-011, REV-S-20 (transition, CSRF, `Secure` en local)

## Dépendances : justification
T-020 (rotation et famille de tokens). T-002 (configuration des domaines).

## Fichiers / modules concernés
- `app/auth/router.py`, `app/auth/service.py`
- `app/core/security.py` (lecture du cookie en plus de l'en-tête)
- `app/core/config.py` (domaine du cookie, CORS avec identifiants)

## Stratégie
1. Date de fin d'acceptation de l'en-tête `Authorization` : fixée dans la question et dans la configuration (`AUTH_HEADER_ACCEPTED_UNTIL`).
2. `Secure` en dehors de `development`. En développement, le parcours est documenté (même origine via le proxy) ; la question précise le comportement de chaque navigateur, car Safari a historiquement refusé `Secure` sur `http://localhost`.
3. CSRF : jeton double-soumis sur les méthodes non sûres, et vérification de l'en-tête `Origin`. Test sur `/auth/refresh` et `/auth/logout`.
4. Déconnexion : suppression des cookies.

## Tests attendus
- Réponse de connexion : `Set-Cookie` avec `HttpOnly`, `Secure`, `SameSite` ; aucun jeton dans le JSON.
- Requête non sûre sans jeton CSRF : refusée (sur `/auth/refresh` et `/auth/logout` explicitement).
- Déconnexion : cookies effacés.

## Critères d'acceptation
- Aucun jeton dans le corps des réponses après la date de fin.
- Date de fin consignée et configurée.

## Risque et retour arrière
Élevé : toute l'authentification change. Retour arrière : réactiver l'en-tête (la transition le permet tant que la date n'est pas passée).

## Livrable documentaire
- `docs/architecture/securite/jetons.md` (créé, section Retour arrière)
- `docs/questions/securite/stockage-jetons.md`

## Parallélisable avec
T-018, T-021, T-023 (fichiers distincts ; `auth/` séquentiel avec T-020).
