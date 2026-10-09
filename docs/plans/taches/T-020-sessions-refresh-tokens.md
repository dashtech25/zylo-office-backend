# T-020 : Sessions, révocation et réutilisation des refresh tokens

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `fix/T-020-sessions` · **Base de test** : `zylo_t020_test` · **Ports** : back 3120
- **Dépendances** : T-012, T-013
- **Décisions requises** : aucune

## Objectif
Une session volée ne survit pas à un changement ou une réinitialisation de mot de passe. Une réutilisation d'un refresh token révoqué coupe toute la chaîne. Le renouvellement concurrent est sérialisé. La révocation sert aussi à la désactivation d'un utilisateur (T-048).

## Problèmes résolus
- IAM-010 (P2), IAM-021 (P3), BCK-015 (partie backend ; le stockage côté client est traité par T-037a et T-037b), REV-A-06 (révocation à la désactivation)

## Dépendances : justification
T-012 et T-013 (même zone `app/auth/`, séquentiel). Bloque T-037a, T-048, T-049.

## Fichiers / modules concernés
- `app/auth/service.py`, `app/auth/models.py` (`refreshToken`, champ de famille, migration additive)
- `app/modules/zylo_liquid/service.py` (`reset_station_staff_password`, lecture et appel)

## Stratégie
1. Révocation de tous les refresh tokens de l'utilisateur lors du changement, de la réinitialisation ou de la désactivation.
2. Famille de tokens : un identifiant partagé par la chaîne de rotation ; la réutilisation d'un token révoqué révoque la famille.
3. Verrou ligne (`SELECT ... FOR UPDATE`) au renouvellement.
4. Migration additive ; `downgrade` testé.

## Tests attendus
- Changement de mot de passe : anciens refresh tokens refusés.
- Rejeu d'un refresh token : 401, famille révoquée (le token légitime suivant aussi refusé).
- Deux renouvellements concurrents : un seul réussit.
- Désactivation d'un utilisateur : ses sessions sont révoquées (test préparé ici, utilisé par T-048).

## Critères d'acceptation
- Les trois comportements testés ; pas de régression sur la connexion et la rotation normale.
- Section « Retour arrière » dans `authentification.md`.

## Risque et retour arrière
Moyen : la révocation au changement de mot de passe déconnecte l'utilisateur actif (attendu). Retour arrière : revert ; la migration est additive.

## Livrable documentaire
- Complément de `docs/architecture/securite/authentification.md` (T-012).

## Parallélisable avec
T-017, T-018, T-019, T-023 (si le fichier auth n'est pas touché).
