# Politique de mot de passe (T-013)

- **Statut** : en place (T-013). Décision `docs/questions/securite/politique-mot-de-passe.md` : option B, appliquée provisoirement, à valider par le client.
- **Code** : `app/auth/politique_mot_de_passe.py` (module unique), `app/auth/schemas.py`, `app/auth/service.py`, `app/auth/router.py`, `app/core/security.py`, `app/identity/invitations.py`, `app/identity/service.py`, `app/modules/zylo_liquid/service.py` (personnel).
- **Frontend** : `src/shared/lib/validation.ts` (mêmes règles, sans la liste de mots courants). Le backend fait autorité.
- **Tests** : `tests/test_politique_mot_de_passe.py`.
- **Audit couvert** : BCK-005 (P1, longueur et règles), IAM-024 (P3, mot de passe temporaire), FRT-013 (P2, règles divergentes entre front et back), partiellement T-020 (révocation des sessions au changement).

## 1. Règles

| Règle | Valeur | Remarque |
|---|---|---|
| Longueur minimale | 12 caractères | comptés en caractères Unicode, pas en octets |
| Longueur maximale | 72 octets UTF-8 | limite de bcrypt : au-delà, le hachage ignore la fin en silence |
| Mots de passe courants | liste locale, sans casse ni accents | liste de formes de 12 caractères ou plus |
| E-mail | partie locale (5 caractères ou plus) interdite | comparaison insensible à la casse |
| Nom | mots du nom de 5 caractères ou plus interdits | séparateurs : espaces, `-`, `'`, `.` |
| Répétition | un seul caractère répété refusé | |
| Composition | aucune exigence | ni majuscule, ni chiffre, ni symbole |
| Changement | nouveau mot de passe différent de l'ancien | |

Pourquoi pas de composition : NIST SP 800-63B demande une longueur et une liste de mots courants, et déconseille les règles de composition, qui poussent à des mots de passe prévisibles.

## 2. Où elle s'applique

| Flux | Où | Quand le contrôle a lieu |
|---|---|---|
| Inscription `POST /auth/register` | schéma `RegisterRequest` | avant tout accès à la base (422) ; e-mail et nom connus |
| Activation `POST /auth/activate` (T-021, T-049) | schéma (longueur, liste) puis service | après résolution du jeton, e-mail et nom du titulaire connus ; **en cas de refus, le jeton n'est pas consommé** (rollback) |
| Changement `POST /auth/change-password` | schéma (longueur, liste) puis service (e-mail, nom, différence) | après vérification de l'ancien mot de passe |
| Réinitialisation `POST /auth/password-reset/confirm` | schéma (longueur, liste) puis service (e-mail et nom du titulaire) | après validation du jeton à usage unique, sans le consommer si la politique refuse |
| Personnel de station (création, réinitialisation) | non appliquée à une saisie : le mot de passe est généré (`secrets.token_urlsafe(9)`, 12 caractères) | test : 200 générés respectent la règle |

Erreurs : 422. Les refus de schéma passent par `validation_error` (le message de chaque règle est dans `details[].msg`). Les refus du service (activation, changement) passent par `password_policy_violation`, avec un `details[]` par règle.

Connexion : **non soumise à la politique**. Un compte ancien avec un mot de passe court doit pouvoir se connecter ; la politique ne s'applique qu'à la création et au changement.

## 3. Adresse e-mail

- Stockée en minuscules à l'inscription (`register_user`) et à la création de compte.
- Connexion et disponibilité comparées en `lower(email)`.
- Index unique `uq_user_email_lower` (migration `c5a1d9e3f7b2`). La migration refuse de s'appliquer s'il existe des doublons qui ne diffèrent que par la casse, et les liste. Le nettoyage est à faire par l'opérateur.

## 4. mustChangePassword appliqué côté backend

- Un compte créé par un tiers (personnel) a `mustChangePassword = true`. Connexion possible, mais le jeton d'accès ne donne accès à rien d'autre que :
  - `GET /auth/me` (lecture du drapeau par l'interface) ;
  - `POST /auth/change-password`.
- Tout autre endpoint protégé par `get_current_user` répond **403 `password_change_required`**.
- Une fois le changement fait, la restriction tombe immédiatement : le drapeau est lu à chaque requête, il n'y a pas de jeton à réémettre.
- Le frontend (`ForceChangePasswordScreen`) n'est qu'un relais : la restriction ne dépend pas de lui.

## 5. Révocation des sessions (T-020 partiel)

- Changement de mot de passe : tous les refresh tokens ouverts sont révoqués.
  - Si le corps contient `refreshToken` (session courante, transmise par l'interface), **cette session reste ouverte** et seules les autres sont révoquées.
  - Sans ce champ, toutes les sessions sont révoquées.
- Réinitialisation du mot de passe d'un membre du personnel : toutes les sessions sont révoquées.
- Limite : un **jeton d'accès** déjà émis reste valable jusqu'à son expiration (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`). C'est la conséquence d'un jeton sans état. La coupure immédiate demande un horodatage de changement par utilisateur et une comparaison à chaque requête : hors T-013.

## 6. Réinitialisation par e-mail (P0)

- `POST /auth/password-reset/request` reçoit `{email}` et répond toujours `202` avec le même texte neutre, que le compte soit absent/inactif ou que l'expéditeur soit désactivé. La limite de débit utilise IP + empreinte du compte; l'adresse n'est pas conservée par le limiteur.
- Un compte actif reçoit un jeton aléatoire de 256 bits, dont seule l'empreinte SHA-256 est stockée dans `passwordResetToken`. Un nouveau jeton révoque tout jeton ouvert précédent; la durée est configurable de 1 à 60 minutes (`PASSWORD_RESET_TTL_MINUTES`, défaut 30).
- `POST /auth/password-reset/confirm` reçoit `{token,newPassword}` et répond `204` au succès; jeton inconnu, expiré, révoqué ou déjà utilisé donne la même erreur `400 password_reset_invalid`. Les erreurs de règle de mot de passe restent `422`; un refus ne consomme pas le jeton.
- Après succès, tous les refresh tokens et les autres demandes ouvertes du titulaire sont révoqués. Les jetons d'accès JWT déjà émis restent valides jusqu'à leur expiration, comme pour le changement de mot de passe (T-013).
- Expéditeur : `none` reste le défaut et n'émet aucun jeton/lien; le message public reste neutre et ne prétend pas qu'un e-mail a été livré. `console` est limité à `development`; `memory` à `test`; `smtp` exige explicitement les variables SMTP et `PASSWORD_RESET_URL_BASE` en HTTPS en production. L'URL doit terminer par `/forgot-password`, chemin de l'écran frontend actuel; un préfixe d'application est permis (ex. `/zylo/forgot-password`). Le défaut local est `http://localhost:3001/forgot-password`. Aucun compte SMTP ni secret fournisseur n'est intégré au dépôt.
- L'envoi SMTP est exécuté après la réponse via une tâche ASGI en mémoire. Il n'y a pas encore d'outbox durable ni de suivi de livraison; les erreurs sont journalisées sans e-mail, contenu, jeton ou secret. Une requête répétée permet d'émettre un nouveau jeton.

## 7. Limites connues

- **Liste de mots courants réduite** (58 entrées, toutes de 12 caractères ou plus). À enrichir avec une liste publique complète ; le module est fait pour cela.
- **Pas de vérification contre les fuites** (service externe type « mots de passe compromis ») : option C de la question, non retenue.
- **Inscription : le 409 `email_already_used` révèle toujours l'existence d'un compte** (IAM-015). La réponse neutre exige un changement de contrat et une vérification par e-mail (T-049) : non faite ici.
- **Contrat frontend livré** : `/forgot-password` demande la réinitialisation via `POST /auth/password-reset/request`; `/reset-password` confirme le nouveau mot de passe via `POST /auth/password-reset/confirm`. `/account/security` permet le changement de mot de passe connecté selon le contrat existant. La réponse de demande reste générique et ne révèle pas si l'adresse existe. SMTP est configurable, mais l'envoi réel dépend de sa configuration et du fournisseur; aucun email livré ne doit être annoncé sans preuve. La tâche d'envoi est en mémoire, sans outbox durable ni suivi de livraison.
- Messages : le frontend affiche les règles locales ; un refus strictement serveur (liste de mots courants) s'affiche avec le message générique de validation si le client ne lit pas `details`.
- Mots de passe de test : les fixtures `Password123!` et `TestPassword123!` respectent la règle (12 caractères ou plus), mais figurent dans des listes publiques courantes. Ce sont des données de test.

## 7. Retour arrière

- Politique : revenir à la longueur précédente se fait dans `app/auth/politique_mot_de_passe.py` (constante `LONGUEUR_MINIMALE`) et dans `src/shared/lib/validation.ts`. Les deux doivent changer ensemble.
- Index : `alembic downgrade -1` supprime `uq_user_email_lower` (additif, aucune donnée touchée).
