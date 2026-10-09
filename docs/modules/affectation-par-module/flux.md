# Affectation d'un utilisateur à un module (flux)

- **Statut** : implémenté sur `feat/T-022-affectation-module` (T-018 + T-022), à valider par le client.
- **Code** : `app/rbac/module_affectation.py`, routes dans `app/rbac/module_router.py`.

## Étapes

1. **Activer le module** pour l'organisation : `POST /api/v1/modules/organizations/{id}/activate`.
   Les rôles par défaut du module sont créés avec `moduleCode` renseigné (T-018).
2. **Créer un rôle de module** (si besoin) : `POST /api/v1/rbac/organizations/{id}/module-roles`
   (permission `rbac.role.manage`). Les permissions doivent appartenir au module ou au socle partagé.
3. **Voir les membres et leur rôle sur le module** :
   `GET /api/v1/rbac/organizations/{id}/modules/{code}/members`.
   Chaque membre liste son rôle courant sur ce module, ou `null`.
4. **Prévisualiser** un changement, sans écriture :
   `GET /api/v1/rbac/organizations/{id}/modules/{code}/users/{userId}/role-preview?roleId=...`.
   Réponse : droits avant/après, permissions gagnées et perdues, `allowed` et `refusal`.
   Sans `roleId`, la prévisualisation porte sur un retrait.
5. **Affecter ou changer** le rôle (remplacement, un seul rôle par module) :
   `PUT /api/v1/rbac/organizations/{id}/modules/{code}/users/{userId}/role` avec `{"roleId": ...}`.
6. **Retirer** le rôle du module : `DELETE /api/v1/rbac/organizations/{id}/modules/{code}/users/{userId}/role`
   (204). Répond 404 si l'utilisateur n'a pas de rôle sur ce module.
7. **Contrôler les droits effectifs** : `GET /api/v1/rbac/organizations/{id}/users/{userId}/module-rights`
   (soi-même, ou `rbac.role.manage`).

Toutes les routes exigent l'en-tête `X-Organization-Id` égal au chemin (sinon 404 uniforme, T-010).
Les règles de refus sont dans `garde-fous.md`, la résolution des droits dans `resolution-permissions.md`.

## Ce qui n'est pas implémenté ici

- Aucun écran : les écrans par module relèvent de T-025.
- Pas d'affectation implicite au premier accès : interdite.
- `POST .../module-roles/assignments` (T-018) reste disponible : il crée une affectation sans remplacer
  l'existante, donc refuse un second rôle sur le même module (409).
