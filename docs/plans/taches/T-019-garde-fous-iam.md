# T-019 : Garde-fous IAM (dernier propriétaire, appartenance, deny, plans, soft-delete)

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : security
- **Branche suggérée** : `fix/T-019-garde-fous-iam` · **Base de test** : `zylo_t019_test` · **Ports** : back 3119
- **Dépendances** : T-010
- **Décisions requises** : `rbac/creation-organisation.md` (en attente, valeur du quota)

## Objectif
Corriger les défauts d'autorisation qui ne relèvent pas de l'isolation : retrait du dernier propriétaire, `deny` sur le rôle propriétaire, cible d'attribution sans appartenance, soft-delete ignoré à l'authentification, UUID invalide en 500, création d'organisation sans quota. Le catalogue de plans n'est plus créable par API (voir T-050).

## Problèmes résolus
- IAM-002 (P1), IAM-004 (P1), IAM-012 (P2), IAM-017 (P2), IAM-022 (P3), IAM-023 (P3), IAM-003 (partie : création de plans par API), REV-A-08 (permission plateforme supposée)

## Dépendances : justification
- T-010 : gardes d'isolation par organisation que T-019 étend.

## Fichiers / modules concernés
- `app/rbac/service.py` (retrait du dernier propriétaire, `deny`, délégation)
- `app/billing/router.py`, `app/billing/service.py` (création de plan supprimée de l'API)
- `app/identity/router.py`, `schemas.py` (création d'organisation, quota, validation de `name` et `slug`)
- `app/core/security.py` (filtre `deletedAt`)

## Stratégie
1. Retrait du dernier attribution `owner` active refusé ; même garde pour le dernier grant `ORGANIZATION_MANAGE`.
2. `deny` interdit sur le rôle owner ; délégation bornée par `validUntil` d'origine.
3. Plans de facturation : pas de création par API. Le catalogue est seedé (voir T-050 pour la permission plateforme si une administration est requise). `get_or_create` ne réécrit pas un prix existant : conflit 409.
4. Utilisateur soft-deleted : 401. UUID invalide dans un chemin ou une portée : 422 (typage).
5. Création d'organisation : tout utilisateur authentifié, quota par utilisateur (**valeur fixée par le client**, paramètre `ORG_CREATION_QUOTA` sans valeur par défaut hors seed de test). Le quota est testé à la limite.
6. Le propriétaire existant qui n'a pas `identity.user.manage` reçoit cette permission par la migration explicite de T-021 (pas par un backfill de démarrage).

## Tests attendus
- Retrait du dernier owner refusé ; avec deux owners, accepté.
- `deny` sur owner refusé ; délégation après expiration refusée.
- Création de plan par API : 403 ou 404 (route retirée) ; plan existant avec prix différent : 409.
- UUID invalide : 422, pas 500.
- Utilisateur soft-deleted : 401.
- Quota de création : dépassement refusé à la limite exacte.

## Critères d'acceptation
- Chaque garde-fou a un test qui échoue sans lui.
- Valeur du quota fournie par le client, ou tâche bloquée sur ce point (question en attente).

## Risque et retour arrière
Moyen : un garde-fou trop strict bloque l'administration légitime (transfert de propriété). Retour arrière : garde-fous activés par configuration pour le quota ; le reste par revert.

## Livrable documentaire
- `docs/architecture/securite/garde-fous-iam.md` (créé)
- `docs/questions/rbac/creation-organisation.md`

## Parallélisable avec
T-020, T-023 (fichiers distincts) ; séquencer avec T-018 sur `rbac/service.py`.

## Réalisation (branche fix/T-019-gardes-routes, 2026-10-09)
- Gardes de permission sur les 198 routes de module qui n'en avaient pas ; 4 restent sans permission, justifiées (`tests/route_baseline_sans_permission.txt`).
- `POST /billing/plans` retiré (option A de T-050) ; conflit de prix 409 `plan_conflict`.
- Garde-fous : dernier propriétaire (409), compte supprimé (401). Non traités : deny sur propriétaire (la règle §5.4 et ses tests l'autorisent : à trancher), quota d'organisation (valeur client), dernier grant `ORGANIZATION_MANAGE`.
- Suite complète (base zylo_t019_test, commit HEAD de fix/T-019-gardes-routes) : 519 passed, 2 failed. Les 2 échecs (tests/test_zylo_liquid_dev_seed.py) préexistent au commit de départ fc1f83e (MultipleResultsFound dans service.py:_measurement_height_at), hors périmètre.
- Statut : À vérifier.
