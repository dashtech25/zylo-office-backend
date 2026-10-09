# T-048 : Cycle de vie utilisateur : désactivation, retrait de l'organisation, retrait d'un module

- **Statut** : Planifiée, en attente de validation client · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-048-cycle-de-vie` · **Base de test** : `zylo_t048_test` · **Ports** : back 3148
- **Dépendances** : T-020, T-021, T-022
- **Décisions requises** : `rbac/cycle-de-vie-utilisateur.md`

## Objectif
Un départ d'employé se traite dans l'application : désactivation d'un utilisateur (sessions révoquées), retrait de son appartenance à l'organisation, retrait de ses affectations à un module. Aucune suppression physique.

## Problèmes résolus
- REV-A-06 (cycle de vie absent du chemin critique), IAM-008 (partie : sessions d'un compte désactivé)

## Dépendances : justification
T-020 (révocation de sessions), T-021 (statut `pending`/`active`), T-022 (affectations à retirer).

## Fichiers / modules concernés
- `app/identity/router.py` : `PATCH /organizations/{id}/users/{userId}` (statut : `active`, `suspended`)
- `app/rbac/router.py`, `app/rbac/service.py` : `DELETE` d'une affectation de module ; retrait de l'appartenance (`OrganizationUser`)
- `tests/test_cycle_vie_utilisateur.py` (créé)

## Stratégie
1. Désactivation réversible (`suspended`) : sessions révoquées (T-020), connexion refusée.
2. Retrait de l'appartenance : interdit pour le dernier propriétaire (garde-fou T-019). Les données créées par l'utilisateur restent, rattachées à l'organisation.
3. Retrait d'une affectation de module : interdit de déduire un droit ailleurs ; historisé dans l'audit.
4. Toutes les routes passent par `get_organization_context` (T-010) et sont listées dans l'inventaire de T-023.

## Tests attendus
- Suspension : sessions révoquées, connexion refusée, réactivation possible.
- Retrait d'appartenance : le dernier propriétaire est refusé.
- Retrait d'affectation : les droits du module disparaissent immédiatement ; un autre module n'est pas touché.
- Cross-tenant sur chaque route (404), via T-047.

## Critères d'acceptation
- Chaque action tracée dans l'audit.
- Décision de conservation des données consignée par le client.

## Risque et retour arrière
Moyen. Retour arrière : réactivation (`active`) ; le retrait d'appartenance est réversible par nouvelle invitation.

## Livrable documentaire
- `docs/architecture/securite/cycle-de-vie-utilisateur.md` (créé)
- `docs/questions/rbac/cycle-de-vie-utilisateur.md`

## Parallélisable avec
T-024, T-025 (frontend, après le contrat d'API).
