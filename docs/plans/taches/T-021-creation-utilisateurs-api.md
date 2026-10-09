# T-021 : Création d'utilisateurs par le propriétaire (API), compte en attente sans mot de passe connu du créateur

- **Statut** : À vérifier (implémentée sur `feat/T-021-creation-utilisateurs`, validation client avant fusion) · **Priorité** : P1 · **Vague** : 2 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-021-creation-utilisateurs` · **Base de test** : `zylo_t021_test` · **Ports** : back 3121
- **Dépendances** : T-010, T-013, T-018, T-019
- **Décisions requises** : `rbac/activation-compte.md` (recommandation : compte en attente, activation par lien à usage unique, validation client avant fusion)

## Objectif
Un propriétaire ou un administrateur d'organisation crée un utilisateur au niveau de l'organisation. Le compte est créé en statut `pending` **sans mot de passe utilisable** et sans mot de passe affiché : le créateur ne connaît jamais le secret du titulaire. L'activation est l'objet de T-049.

## Problèmes résolus
- IAM-006 (P1), IAM-007 (P1, `mustChangePassword` seulement côté frontend), REV-S-06 (mot de passe temporaire connu du créateur), REV-A-07, DOC-021 (exigence « créer ses utilisateurs »)

## Dépendances : justification
T-010 (isolation), T-013 (règle de mot de passe), T-018 (rôles par module), T-019 (appartenance et garde-fous). L'activation (T-049) et la révocation (T-020) suivent.

## Fichiers / modules concernés
- `app/identity/router.py` (`POST /organizations/{id}/users`), `app/identity/service.py`, `app/identity/schemas.py`
- `app/identity/permissions.py` (`identity.user.manage`, créée)
- `app/core/security.py` (contrôle de l'état `pending` et de `mustChangePassword`)
- Migration explicite et idempotente : accorde `identity.user.manage` aux propriétaires existants (`backfill_owner_default_permissions` n'est plus appelé au démarrage ; T-028)
- `app/modules/zylo_liquid/service.py` (lecture ; le personnel de station reste une extension de ce socle, sans rupture)

## Stratégie
1. Question `rbac/activation-compte.md` : recommandation : compte `pending`, activation par lien à usage unique envoyé hors application (infrastructure d'e-mail décidée par le client) ; à défaut, option documentée avec son risque résiduel.
2. Route réservée à `identity.user.manage`. Réponse : identifiant du compte et statut, **jamais** de secret.
3. `pending` : aucune connexion par mot de passe tant que l'activation n'a pas eu lieu.
4. Migration explicite pour les propriétaires existants (idempotente, journalisée) : pas de backfill de démarrage.
5. Création du personnel de station : même chemin, sans rupture pour les scripts existants.

## Tests attendus
- Propriétaire crée un utilisateur : 201, statut `pending`, aucun secret dans la réponse.
- Membre sans permission : 403 ; utilisateur d'une autre organisation : 404 (T-010).
- Le créateur ne peut pas se connecter comme le compte créé (test explicite, REV-S-06).
- Migration des propriétaires : rejouable, sans effet au second passage.
- Non-régression : création du personnel de station.

## Critères d'acceptation
- Aucun mot de passe temporaire renvoyé ni journalisé.
- Un compte `pending` ne peut ouvrir aucune session.
- Validation client consignée avant fusion.

## Risque et retour arrière
Élevé pour le personnel de station existant : compatibilité gardée. Retour arrière : désactiver la route par configuration ; le statut `pending` reste sans effet sur les comptes existants.

## Livrable documentaire
- `docs/architecture/securite/creation-utilisateurs.md` (créé, section Retour arrière)
- `docs/questions/rbac/activation-compte.md`

## Parallélisable avec
T-017, T-020, T-023 (fichiers distincts) ; séquencer avec T-020 sur `auth/`.

## Réalisation (T-021, lot 3, 2026-10-09) : À vérifier
- Routes : `POST /organizations/{id}/users` (201, `pending`, sans secret), `POST …/users/{userId}/invitation` (réémission), `PATCH …/users/{userId}` (suspension et réactivation), `POST /auth/activate` (T-049 minimal). Détail : `docs/architecture/securite/creation-utilisateurs.md`.
- Tests : `tests/test_creation_utilisateurs.py` (36 cas). Non-régression : voir le rapport de lot.
- Décision recommandée appliquée (`rbac/activation-compte.md`, option A) ; création désactivée tant que `EMAIL_BACKEND=none` (503). Fournisseur d'e-mail non choisi.
- Migration `e7f8a9b0c1d2` : table `userInvitation` (jeton haché, usage unique, index partiel) et permission accordée aux propriétaires existants (rejouable).
- Écarts à valider : énumération par les administrateurs (409 `email_already_used`) ; personnel de station non migré (mot de passe temporaire inchangé, IAM-007 ouvert) ; politique de mot de passe 8 caractères en attendant T-013.
