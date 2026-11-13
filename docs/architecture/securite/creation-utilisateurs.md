# Création d'utilisateurs par l'organisation, activation et cycle de vie minimal (T-021, T-049, T-048)

- **Statut** : en place sur `feat/T-021-creation-utilisateurs`, à vérifier (validation client avant fusion ; Playwright suspendu).
- **Code** : `app/identity/invitations.py`, `app/identity/router.py`, `app/identity/schemas.py`, `app/identity/permissions.py`, `app/auth/router.py` (`POST /auth/activate`), `app/shared/email.py`, `app/core/config.py`, migration `alembic/versions/e7f8a9b0c1d2_creation_utilisateurs_invitations.py`.
- **Tests** : `tests/test_creation_utilisateurs.py` (36 cas) ; contournement des rôles de module : `tests/test_contournement_role_module.py` (5 cas).
- **Décision** : `docs/questions/rbac/activation-compte.md` (option A, création désactivée tant que l'envoi n'est pas configuré).
- **Flux pour le module** : `docs/modules/identite/flux-creation-activation.md`.

## 1. Principe

Le créateur ne connaît jamais le secret du titulaire. Aucun mot de passe temporaire n'est généré pour être affiché. Le compte est créé `pending` avec un mot de passe aléatoire que personne ne connaît. Le titulaire choisit son mot de passe avec un lien à usage unique, transmis hors de l'API.

## 2. Routes

| Méthode et chemin | Permission | Effet | Réponse |
|---|---|---|---|
| `POST /api/v1/organizations/{id}/users` | `identity.user.manage` | Crée le compte `pending`, l'appartenance, un jeton, envoie le lien | 201 `{id, email, fullName, status, organizationId, invitationExpiresAt}` |
| `POST /api/v1/organizations/{id}/users/{userId}/invitation` | `identity.user.manage` | Révoque les jetons ouverts, en émet un nouveau (compte `pending` seulement) | 201 `{userId, invitationExpiresAt}` |
| `PATCH /api/v1/organizations/{id}/users/{userId}` | `identity.user.manage` | `active` ou `suspended` (réversible) | 200 `{id, email, fullName, status}` |
| `POST /api/v1/auth/activate` | aucune (le jeton est la preuve) | Consomme le jeton, fixe le mot de passe, passe `active` | 200 `{id, email, status}` |

Une route sans X-Organization-Id valide ou sans appartenance répond 404 `organization_not_found` (T-010). Sans permission : 403 `permission_denied`.

## 3. Jeton d'activation

- 256 bits (`secrets.token_urlsafe(32)`), transmis uniquement dans le message : `<ACTIVATION_URL_BASE>#token=<jeton>`. Le fragment n'est pas envoyé au serveur ni journalisé par les serveurs web.
- Base : seule l'empreinte SHA-256 est stockée (`userInvitation.tokenHash`, unique). Un test vérifie qu'aucune colonne ne contient le jeton en clair.
- Durée : `USER_INVITATION_TTL_HOURS` (72 h par défaut).
- Usage unique : `usedAt` est posé par une mise à jour conditionnelle (non utilisé, non révoqué, non expiré). Deux requêtes concurrentes ne peuvent pas réussir toutes les deux.
- Un seul jeton ouvert par compte : index unique partiel `uq_userInvitation_open_per_user` (contrainte en base, pas seulement dans le code).
- Réémission : révoque l'ancien jeton (`revokedAt`). Un jeton expiré se remplace par une réémission.
- Erreurs d'activation : toujours `400 invitation_invalid`, sans distinguer inconnu, expiré, utilisé ou révoqué. Pas d'énumération.

## 4. Envoi (`app/shared/email.py`)

Le module ne connaît que `EmailSender.send`. Trois adaptateurs, choisis par `EMAIL_BACKEND` :

| Valeur | Usage | Garde |
|---|---|---|
| `none` (défaut) | production tant que le fournisseur n'est pas choisi | création refusée en 503 `user_creation_disabled` avant toute écriture |
| `console` | développement local | refusé hors `ENVIRONMENT=development` (le message contient le jeton) |
| `memory` | tests | refusé hors `ENVIRONMENT=test` |

Un échec d'envoi annule la création (503 `email_delivery_failed`, transaction annulée). Un adaptateur de production (SMTP ou API) s'ajoute derrière un nouveau nom de `EMAIL_BACKEND`, sans changer les appelants.

## 5. Règles et garde-fous

- Email en minuscules à la création. Email déjà utilisé : 409 `email_already_used` (message générique). Voir §7, risque résiduel.
- Validation : email valide (`EmailStr`), nom 1 à 255 caractères après suppression des espaces, token 20 à 200 caractères, mot de passe 8 à 255 (aligné sur le changement de mot de passe ; la politique T-013 n'est pas fusionnée).
- Un compte `pending` ne peut ouvrir aucune session : pas de connexion (jamais de jeton de session émis) et `get_current_user` exige `active`, même avec un jeton d'accès forgé.
- Désactivation (`suspended`) : refresh tokens révoqués immédiatement, `get_current_user` coupe aussi les jetons d'accès restants, réactivation possible. Aucune suppression physique.
- Refusés en 409 : statut d'un compte `pending` (`user_not_activated`), auto-suspension (`self_status_change_forbidden`), dernier propriétaire actif (`last_owner`), compte aussi membre d'une autre organisation (`user_member_of_other_organizations`). Le compte étant global, une désactivation décidée par une organisation toucherait les autres : elle est donc refusée.
- Réémission sur un compte déjà actif : 409 `user_not_pending`.
- Chaque action est journalisée (`auditLog`) : `identity.user.create`, `identity.user.invitation.reissue`, `identity.user.activate` (acteur : le titulaire), `identity.user.suspend`, `identity.user.reactivate`. Ni le jeton ni un secret n'entrent dans le journal.

## 6. Permission et migration

- `identity.user.manage` (`app/identity/permissions.py`) : donnée au propriétaire à la création d'une organisation et déclarée au catalogue au démarrage (`app/identity/seed.py`).
- Propriétaires existants : migration `e7f8a9b0c1d2`, explicite et rejouable (`accorde_permission_aux_proprietaires`, test de second passage). Limite : `backfill_owner_default_permissions` s'exécute aussi au démarrage et reprend la même liste ; la suppression de ce backfill relève de T-028.
- Retour arrière : `alembic downgrade` supprime la table. La permission reste (sans effet sans les routes).

## 7. Limites et risques résiduels

1. **Énumération par les administrateurs** : un titulaire d'`identity.user.manage` apprend si une adresse a déjà un compte (409). Une réponse uniforme exigerait un flux d'ajout d'un compte existant, non décidé. Décision client à consigner.
2. **Pas de fournisseur d'e-mail** : tant que `EMAIL_BACKEND=none`, aucun compte ne peut être créé. Le choix du fournisseur est en attente (`docs/questions/rbac/activation-compte.md`).
3. **Pas de limitation de débit sur `POST /auth/activate`** : le jeton (256 bits) rend la recherche infaisable, mais une limite par IP reste à ajouter (T-012 à étendre).
4. **Personnel de station** : `create_station_staff_member` (module zylo_liquid) crée toujours ses comptes avec un mot de passe temporaire affiché au créateur (IAM-007). Il n'est pas migré dans cette tâche, ce qui laisse ce défaut ouvert pour ce chemin.
5. **Politique de mot de passe** : longueur 8 seulement, en attente de T-013.
6. **Migration de tête** : la révision `e7f8a9b0c1d2` suit `b4e1c7d2a9f3` (tête de `remy` après la fusion de T-018). Une seule tête Alembic.
7. **Rôles de module (T-018)** : `assign_role` (route générique `POST /rbac/organizations/{id}/user-roles`) ne contourne plus la règle « un rôle par module et par utilisateur ». Rôle de module à l'échelle de l'organisation : délégué à `assign_module_role`. Rôle de module avec portée ressource (station, zylo_liquid / zylo_tanker) : compatibilité explicite, un autre rôle du même module est refusé (409 `module_role_already_assigned`) ; décision à confirmer, car un gérant ne peut plus avoir un rôle de module sur deux stations. Tests : `tests/test_contournement_role_module.py`.
