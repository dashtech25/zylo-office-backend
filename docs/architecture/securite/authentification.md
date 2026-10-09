# Authentification : limitation de débit et verrouillage (T-012)

- **Statut** : en place (T-012, à vérifier : Playwright sur build prod non fait, voir §6).
- **Code** : `app/auth/ratelimit.py`, `app/auth/router.py`, `app/auth/service.py`.
- **Décision** : `docs/questions/securite/limitation-authentification.md` (stockage PostgreSQL, sans Redis).
- **Audit couvert** : BCK-004 (P1), IAM-008 (P1), REV-S-07 (verrou utilisable comme déni de service).
- **Configuration** : `docs/process/configuration.md` §5.

## 1. Ce qui est limité

| Endpoint | Portée IP seule | Portée couple (IP, compte) | Ce qui compte comme échec |
|---|---|---|---|
| `POST /auth/login` | oui | oui (sauf IP déjà connue du titulaire) | identifiants refusés (401) |
| `POST /auth/register` | oui | oui | email déjà utilisé (409) |
| `POST /auth/refresh` | oui | non (pas d'email dans la requête) | jeton invalide, expiré, révoqué ou utilisateur inactif (401) |

Les réponses 422 (validation) et 5xx ne sont jamais comptées.

## 2. Algorithme

1. Avant l'action : pour chaque portée applicable, compter les échecs dans la fenêtre glissante `AUTH_RATE_LIMIT_WINDOW_SECONDS`.
2. Si le nombre atteint le seuil, le verrou dure jusqu'à `dernier échec + base x 2^(échecs - seuil)`, plafonné à `AUTH_RATE_LIMIT_LOCK_MAX_SECONDS`. Pendant ce verrou : 429 avec `Retry-After`.
3. Après un échec d'identifiants : une ligne pour l'IP et une pour le couple.
4. Après un succès de login : les échecs du couple sont supprimés, et le couple est marqué « connu » (ligne `outcome=success`). Une IP connue du titulaire ne subit plus le verrou par couple.
5. Purge : à chaque échec, les échecs hors fenêtre des clés concernées sont supprimés.

Les clés sont des empreintes SHA-256 de (action, portée, IP, email normalisé). La table ne contient ni email ni mot de passe en clair.

## 3. Messages et temps de réponse

- Compte inconnu et mauvais mot de passe : même statut (401), même corps (`invalid_credentials`).
- Le verrou se déclenche aussi pour un email inconnu : le 429 ne révèle pas l'existence du compte.
- Temps de réponse : un email inconnu déclenche un contrôle de mot de passe contre un hachage factice (`_hachage_factice`, service `authenticate_user`). Un mot de passe correct sur un compte inactif répond toujours 403 `account_inactive` : ce cas n'est atteint qu'après la preuve du mot de passe.

## 4. Adresse IP

- L'adresse retenue est celle du pair TCP, sauf si ce pair figure dans `AUTH_RATE_LIMIT_TRUSTED_PROXIES`.
- Dans ce cas, `X-Forwarded-For` est parcouru de droite à gauche en ignorant les proxys de confiance. La première adresse valide est le client.
- Une valeur invalide retombe sur le pair direct.

## 5. Journal de sécurité

Logger `zylo_office.security` (format JSON du socle) :

- `auth_failure` (niveau WARNING) : action, IP, portée.
- `auth_rate_limited` (WARNING) : action, portée, IP, empreinte tronquée de la clé, attente en secondes.

Aucun mot de passe, aucun email. Le journal ne remplace pas une rétention de sécurité : les logs sont ceux du processus.

## 6. Limites connues (à traiter ailleurs)

- **Register : le 409 `email_already_used` révèle toujours l'existence d'un compte** (IAM-015). La réponse neutre exige une confirmation par email, qui n'existe pas. Hors T-012 ; la limitation réduit seulement le rythme d'énumération.
- **Attaque distribuée sur un compte** : chaque IP a son propre compteur. Un verrou global par compte est volontairement absent (REV-S-07 : il servirait de déni de service). Une attaque depuis de nombreuses IP n'est donc freinée que par le plafond par IP.
- **Pas de route de réinitialisation de mot de passe** dans le code actuel : rien à limiter sur ce point.
- **Partage d'IP (NAT, entreprise)** : un plafond par IP peut bloquer des utilisateurs légitimes derrière la même adresse. Calibrer `AUTH_RATE_LIMIT_MAX_FAILURES_PER_IP` en production.
- **Non vérifié ici** : le comportement derrière le proxy de production (`TRUSTED_PROXIES` à renseigner), et le test Playwright sur build prod (T-012, critère « connexion refusée avec message générique ») : le frontend n'est pas modifié par cette tâche.
- **Multi-instance** : les compteurs sont dans PostgreSQL, donc partagés entre processus. Un verrou n'est pas perdu au redémarrage.

## 6 bis. Mot de passe et sessions (T-013)

- Politique commune à l'inscription, à l'activation, au changement et au personnel : `docs/architecture/securite/politique-mot-de-passe.md`.
- `mustChangePassword` est appliqué côté backend : tant qu'il est vrai, seuls `GET /auth/me` et `POST /auth/change-password` répondent (sinon 403 `password_change_required`).
- Le changement révoque les refresh tokens des autres sessions (`refreshToken` optionnel dans le corps pour garder la session courante).

## 7. Retour arrière

`AUTH_RATE_LIMIT_ENABLED=false` désactive les contrôles sans modifier le code. Les échecs continuent d'être enregistrés pour que la réactivation prenne effet immédiatement.
