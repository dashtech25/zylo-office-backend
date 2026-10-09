# Identité : flux création, activation, affectation (T-021, T-049, T-022)

- **Statut** : création et activation en place (branche `feat/T-021-creation-utilisateurs`, à vérifier). Affectation à un module : API en attente (T-022).
- **Détail technique** : `docs/architecture/securite/creation-utilisateurs.md`.

## 1. Création (propriétaire ou gestionnaire)

1. Un utilisateur doté de `identity.user.manage` appelle `POST /api/v1/organizations/{id}/users` avec `email` et `fullName`, en-tête `X-Organization-Id` égal à `{id}`.
2. Le serveur crée le compte `pending` (mot de passe aléatoire inconnu de tous), l'appartenance à l'organisation, un jeton à usage unique valable 72 h.
3. Le titulaire reçoit le lien `…/activer#token=…` par le canal d'envoi. La réponse de l'API ne contient aucun secret.

## 2. Activation (titulaire, sans compte connecté)

1. Il ouvre le lien. Le frontend lit le fragment et appelle `POST /api/v1/auth/activate` avec `{token, password}`.
2. Le serveur consomme le jeton, enregistre le mot de passe choisi, passe le compte à `active`.
3. Il peut ensuite se connecter normalement (`POST /api/v1/auth/login`).

Cas d'erreur : lien inconnu, expiré, déjà utilisé ou révoqué → 400 `invitation_invalid`. Lien expiré : le créateur réémet (`POST …/users/{userId}/invitation`), l'ancien lien est révoqué.

## 3. Cycle de vie

- Désactiver : `PATCH /api/v1/organizations/{id}/users/{userId}` avec `{"status": "suspended"}`. Sessions révoquées, connexion refusée. Réversible.
- Réactiver : même route avec `{"status": "active"}`.
- Refus : compte encore `pending`, soi-même, dernier propriétaire, compte membre d'une autre organisation.

## 4. Affectation à un module (T-022, à venir)

Pour un compte `active`, l'affectation de module (rôle par module, branche `feat/T-018-roles-par-module`) se fera après l'activation : le compte doit être membre de l'organisation et le module actif pour elle. Un compte `pending` n'a aucun droit effectif, donc aucune affectation utile avant activation.

## 5. Ce que le créateur ne voit jamais

- Le mot de passe du titulaire (il ne le choisit pas).
- Le jeton d'activation (ni dans la réponse de création, ni dans celle de réémission, ni dans le journal d'audit).
