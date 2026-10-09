# T-049 : Activation de compte par lien à usage unique (mot de passe choisi par le titulaire)

- **Statut** : Planifiée, en attente de validation client · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : iam · **Type** : security
- **Branche suggérée** : `feat/T-049-activation` · **Base de test** : `zylo_t049_test` · **Ports** : back 3149, front dev 3249, front prod 3349
- **Dépendances** : T-021, T-013, T-020
- **Décisions requises** : `rbac/activation-compte.md`

## Objectif
Le titulaire d'un compte `pending` choisit son mot de passe lui-même, via un jeton d'activation à usage unique, à durée limitée, stocké haché, et transmis hors de l'application. Le créateur ne peut jamais utiliser ce jeton.

## Problèmes résolus
- REV-S-06 (solution complète), IAM-007 (partie), REV-A-07 (correction)

## Dépendances : justification
T-021 (compte `pending`), T-013 (règle de mot de passe), T-020 (révocation des sessions à l'activation).

## Fichiers / modules concernés
- Backend : `app/auth/router.py` (`POST /auth/activate`), `app/auth/service.py`, table des jetons d'activation (migration additive, jeton haché, expiration, `usedAt`)
- Backend : `app/shared/email.py` (créé) : interface d'envoi ; adaptateur « journal » en développement uniquement, adaptateur SMTP ou fournisseur choisi par le client en production
- Frontend : écran d'activation (`src/app/(auth)/activer/page.tsx`, délégation d'une ligne vers un écran)

## Stratégie
1. Jeton de 256 bits, haché en base, valable 72 heures, à usage unique (`usedAt`).
2. L'envoi est fait hors application. **Tant que l'envoi n'est pas configuré en production, la création d'utilisateur (T-021) est désactivée par configuration** : pas de contournement par un mot de passe affiché.
3. À l'activation : mot de passe selon T-013, révocation de toutes les sessions (T-020), statut `active`.
4. Le créateur n'a aucun accès au jeton : sa réponse API ne le contient jamais.

## Tests attendus
- Jeton utilisé deux fois : refusé au second usage.
- Jeton expiré : refusé.
- Jeton d'un autre compte : refusé.
- Le créateur, connecté, ne peut ni lire ni utiliser le jeton (test explicite).
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : création (propriétaire), activation (titulaire), première connexion.

## Critères d'acceptation
- Aucun mot de passe connu du créateur dans le parcours.
- Désactivation de la création tant que l'envoi n'est pas configuré (test).
- Décision de l'envoi consignée par le client.

## Risque et retour arrière
Moyen : dépend d'une infrastructure d'e-mail non décidée. Retour arrière : désactiver la création (configuration) ; les comptes `pending` existants restent inactifs.

## Livrable documentaire
- `docs/architecture/securite/activation-compte.md` (créé)
- `docs/questions/rbac/activation-compte.md` (complété)

## Parallélisable avec
T-022, T-024 (fichiers distincts ; T-024 dépend de T-021 uniquement côté contrat).
