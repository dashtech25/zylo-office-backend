# T-050 : Permission plateforme explicite, et catalogue de plans administré hors API

- **Statut** : Planifiée, en attente de décision client · **Priorité** : P2 · **Vague** : 2 · **Taille** : S · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : security
- **Branche suggérée** : `feat/T-050-permission-plateforme` · **Base de test** : `zylo_t050_test` · **Ports** : back 3150
- **Dépendances** : T-010, T-019
- **Décisions requises** : `rbac/permission-plateforme.md`

## Objectif
Le plan de remise sur pied supposait une « permission plateforme » qui n'existe pas (`app/identity/service.py` : « sans concept de super-admin plateforme »). Cette tâche la rend explicite, ou confirme qu'elle n'est pas nécessaire : le catalogue de plans est seedé, et toute administration passe par une commande explicite.

## Problèmes résolus
- REV-A-08 (permission plateforme supposée), IAM-003 (partie administration des plans)

## Dépendances : justification
- T-010 : isolation des routes d'organisation.
- T-019 : suppression de la création de plan par API.

## Fichiers / modules concernés
- `app/identity/permissions.py` : `identity.platform.manage` (créée **seulement si** la décision le demande)
- `app/billing/seed.py` (catalogue seedé, idempotent)
- `scripts/platform/` (commandes d'administration, si besoin)

## Stratégie
1. Recommandation vérifiée : catalogue seedé, aucune route d'API pour créer un plan. Pas de super-admin en API.
2. Si le client demande une administration : une permission `identity.platform.manage`, attribuée par commande de seed à un compte nommé, jamais par API.
3. Test : aucune route ne crée un plan (inventaire T-023).

## Tests attendus
- Seed du catalogue : idempotent.
- Création de plan par API : impossible (test d'inventaire).

## Critères d'acceptation
- Décision consignée ; aucune permission plateforme créée sans décision écrite.

## Risque et retour arrière
Faible. Retour arrière : réintroduire la route, avec la permission.

## Livrable documentaire
- `docs/questions/rbac/permission-plateforme.md`

## Parallélisable avec
T-017, T-018, T-020, T-021, T-023.
