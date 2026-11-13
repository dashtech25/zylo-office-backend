# Sessions : cookies HttpOnly, rotation et révocation (T-020, T-037a, T-037b)

- **Statut** : implémenté sur `feat/T-020-T-037-sessions-cookies`, à vérifier (voir §9).
- **Code** : `app/core/session_http.py` (cookies, CSRF, Origin), `app/core/security.py` (lecture du cookie), `app/auth/service.py` (famille, rotation), `app/auth/router.py` (login, refresh, logout).
- **Décisions** : `docs/questions/securite/stockage-jetons.md` (option A : cookies posés par l'API, même site). Protection CSRF : recommandation R10 de `docs/architecture/bonnes-pratiques/securite-rbac-multitenant.md`.
- **Audit couvert** : IAM-010 (révocation), IAM-011 (jetons dans `localStorage`), IAM-021 (réutilisation et verrou), FRT-001 (côté interface), REV-S-19 et REV-S-20 (en-têtes et transition).

## 1. Cookies

| Cookie | Contenu | Attributs | Chemin |
|---|---|---|---|
| `zylo_access` | JWT d'accès (15 min par défaut) | `HttpOnly`, `Secure`, `SameSite=Lax` | `/` |
| `zylo_refresh` | JWT de rafraîchissement (30 jours par défaut) | `HttpOnly`, `Secure`, `SameSite=Lax` | `/api/v1/auth` |
| `zylo_csrf` | Jeton CSRF, aléatoire, renouvelé à chaque émission | `Secure`, `SameSite=Lax`, **sans** `HttpOnly` | `/` |

- `Secure` est vrai hors `ENVIRONMENT=development` (`AUTH_COOKIE_SECURE` peut le désactiver, uniquement en development).
- Le cookie de rafraîchissement n'accompagne que les routes `/api/v1/auth/*`. Le reste de l'API ne le reçoit jamais.
- Les réponses de connexion et de rafraîchissement portent `Cache-Control: no-store`.
- Aucun cookie n'a de `Domain` par défaut : il est lié à l'hôte exact (`AUTH_COOKIE_DOMAIN` pour changer).

## 2. Protection CSRF

Une requête **non sûre** (POST, PUT, PATCH, DELETE) portée par cookie est refusée si :

1. son en-tête `Origin` est présent et absent de `CORS_ORIGINS` → 403 `origin_refused` ;
2. le cookie `zylo_csrf` et l'en-tête `X-CSRF-Token` sont absents ou différents (comparaison à temps constant) → 403 `csrf_invalid`.

« Portée par cookie » veut dire : jeton d'accès lu dans le cookie (pas dans l'en-tête `Authorization`), ou cookie de rafraîchissement utilisé sur `/auth/refresh`, `/auth/logout` et `/auth/change-password`. Une requête avec `Authorization` n'est jamais contrôlée : un navigateur ne l'envoie pas automatiquement, donc elle ne peut pas être forgée par un site tiers.

Le client (`src/core/api/client.ts`) recopie `zylo_csrf` dans `X-CSRF-Token` sur chaque requête non sûre.

## 3. Rotation, famille et réutilisation

- Chaque connexion ouvre une **famille** (`refreshToken.familyId`). Chaque rotation émet un jeton de même famille et révoque l'ancien.
- Présenter un jeton **déjà révoqué** est traité comme une réutilisation : toute la famille est révoquée, y compris le jeton légitime suivant. Réponse 401 `invalid_refresh_token`. La révocation est commitée avant l'erreur.
- Deux renouvellements concurrents du même jeton : `SELECT ... FOR UPDATE` les sérialise ; le second voit le jeton révoqué, donc il est traité comme une réutilisation. Un seul réussit.
- Un jeton expiré est refusé sans révoquer la famille.

Conséquence assumée : un double envoi concurrent du même rafraîchissement, depuis le même navigateur, déconnecte la session. Le client évite ce cas : un seul appel de rafraîchissement est en cours à la fois (`rafraichirSession`, promesse partagée).

## 4. Transition

Variable : `AUTH_HEADER_ACCEPTED_UNTIL` (date avec fuseau). **Valeur proposée : 2026-11-30 00:00 UTC, à confirmer avant déploiement.**

| Avant la date | Après la date |
|---|---|
| `Authorization: Bearer` accepté (clients existants) | en-tête ignoré : seul le cookie authentifie |
| `accessToken` et `refreshToken` présents dans le JSON de login et de refresh | JSON sans jeton (`{}`) |
| `refreshToken` accepté dans le corps de `/auth/refresh` et `/auth/logout` | corps ignoré : cookie seul |

Le frontend livré avec cette tâche n'utilise plus l'en-tête ni le corps : il dépend des cookies dès maintenant. La transition ne sert donc qu'aux clients tiers ou non mis à jour.

## 5. Révocation

| Événement | Effet | Où |
|---|---|---|
| Déconnexion | refresh token de la session révoqué, cookies effacés (`Max-Age=0`) | `/auth/logout` |
| Changement de mot de passe | toutes les sessions révoquées, sauf la session courante (cookie ou `refreshToken` du corps) | `service.change_password` |
| Réinitialisation par un tiers (personnel) | toutes les sessions révoquées | `zylo_liquid.service.reset_station_staff_password` |
| Suspension d'un compte (T-021) | toutes les sessions révoquées, et `get_current_user` exige `status = active` | `identity.invitations.update_user_status` |
| Réutilisation d'un refresh token | famille entière révoquée | `service.rotate_refresh_token` |

Limite connue : un jeton d'accès déjà émis reste valable jusqu'à son expiration (15 min par défaut). Une suspension coupe immédiatement l'accès, car `get_current_user` relit l'utilisateur à chaque requête.

## 6. Configuration

Variables (`app/core/config.py`) :

- `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (15), `JWT_REFRESH_TOKEN_EXPIRE_DAYS` (30) : durées configurables.
- `AUTH_COOKIE_SECURE` (vide = vrai hors development), `AUTH_COOKIE_SAMESITE` (`lax` ou `strict`, jamais `none`), `AUTH_COOKIE_DOMAIN` (vide).
- `AUTH_HEADER_ACCEPTED_UNTIL` (voir §4).
- `CORS_ORIGINS` : liste explicite, sans `*`. En production, **l'origine de l'interface doit y figurer** : c'est elle qui passe la vérification `Origin` de §2.

Démarrage refusé si `AUTH_COOKIE_SECURE=false` hors development, si `CORS_ORIGINS` contient `*`, ou si `AUTH_HEADER_ACCEPTED_UNTIL` n'a pas de fuseau.

CORS : `allow_credentials=True`, méthodes et en-têtes listés (`Authorization`, `Content-Type`, `X-Organization-Id`, `X-CSRF-Token`, `Accept`).

## 7. Interface

- `src/core/api/client.ts` : seul point d'appel réseau (règle ESLint `no-restricted-globals`). Cookies envoyés (`credentials: "include"`), aucun en-tête `Authorization`, aucune lecture de `localStorage` pour la session.
- `localStorage` ne garde que l'identifiant d'organisation courante (préférence d'interface).
- État de session : `GET /auth/me` au chargement (sonde silencieuse, `silent401`).
- 401 : un rafraîchissement partagé, puis un rejeu. Si le rafraîchissement échoue, l'évènement `auth:session-expired` redirige vers la connexion.
- Déconnexion : appel à `/auth/logout`, puis vidage du cache de requêtes, même si l'appel échoue.

## 8. Retour arrière

- Réactiver l'en-tête et le corps : repousser `AUTH_HEADER_ACCEPTED_UNTIL`. Pas de revert de code.
- Revenir aux jetons en `localStorage` côté interface : revert du commit frontend (le backend accepte encore les deux modes tant que la date n'est pas passée).
- Schéma : la migration `a3f1c2d4e5b6` ajoute `refreshToken.familyId` (additive) ; `downgrade` la supprime. Testé sur la base de test.

## 9. Vérification

- `tests/test_sessions_cookies.py` : attributs des cookies, transition, CSRF, Origin, rejeu, concurrence, déconnexion, changement de mot de passe.
- `tests/test_config_sessions.py` : refus au démarrage hors development.
- `tests/test_auth.py` et `tests/test_creation_utilisateurs.py` (suspension) : non régressés.
- Frontend : `src/core/api/client.test.ts` (sans jeton, CSRF, rafraîchissement unique, `localStorage` piégé).
- Non couvert : parcours navigateur réel (Playwright suspendu, ADR 0006). Le parcours curl/httpx est dans le compte rendu de la tâche.

## 10. Limites

- Pas de Content-Security-Policy côté interface : non vérifiée sans navigateur. Les en-têtes `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy` sont en place.
- `SameSite=Lax` et `Secure` sur `http://localhost` : Safari refuse historiquement `Secure` sur http. Le développement local doit tourner en `ENVIRONMENT=development`, ou via un proxy HTTPS.
- Les tests Playwright de `e2e/` lisent encore `zylo_office_access_token` dans `localStorage` : ils sont à réécrire quand Playwright reprendra.
- Le sous-domaine partagé n'est pas couvert : `Domain` n'est pas posé, donc aucun partage de cookie entre sous-domaines.
