# Endpoints App Launcher — organisations de l'utilisateur + modules installés

Issue #55. Prérequis backend pour la refonte du tableau de bord frontend
(App Launcher) : les cartes d'application affichées doivent refléter les
modules réellement installés pour l'organisation, jamais une liste statique.

## 1. Architecture appliquée

Aucune nouvelle architecture — deux endpoints de lecture ajoutés au socle
existant (`identity`, `modules_registry`), suivant les patterns déjà en
place (`app.core.errors.AppError`, `Depends()`, réponses Pydantic).

## 2. Ce qui a été construit

- `GET /api/v1/organizations` — organisations de l'utilisateur courant.
  `app.identity.service.list_user_organizations`.
- `GET /api/v1/modules/organizations/{organization_id}` — catalogue complet
  des modules croisé avec le statut d'activation de l'organisation (défaut
  `"inactive"` si jamais activé). `app.modules_registry.service.list_installed_modules`,
  schéma `InstalledModuleResponse`.
- `app.identity.service.require_organization_member` — nouvelle dépendance
  d'appartenance à l'organisation (pas une permission), utilisée par le
  second endpoint : voir ses propres modules installés ne doit pas exiger
  une permission d'administration, contrairement à activer/désactiver
  (toujours derrière `MODULE_MANAGE`). Implémentée comme fonction directe
  (pas une fabrique comme `require_permission(code)`) car `organization_id`
  est un paramètre de chemin résolu par requête, pas une valeur fixe au
  chargement du module.

## 3. Factorisé dans le Core

Les deux endpoints vivent dans le Core (`identity`, `modules_registry`) —
aucune notion propre à un module métier.

## 4. Propre à un module

Rien — ces endpoints sont génériques, réutilisés par tout futur module.

## 5. Comparaison aux sources de vérité

Vérifié contre le code existant (`activate_module`/`deactivate_module`,
`require_permission`) : aucun endpoint de lecture n'existait avant pour
ni l'un ni l'autre besoin — confirmé par lecture de
`app/identity/router.py` et `app/modules_registry/router.py` avant
modification.

## 6. Décisions prises

- Un seul schéma de réponse (`InstalledModuleResponse`) sert à la fois au
  Dashboard (filtrer `status == "active"`) et à une future marketplace de
  modules (tout le catalogue avec son statut) — évite un troisième
  endpoint.
- Fusion catalogue ⋈ activations faite en Python (deux requêtes simples)
  plutôt qu'un LEFT JOIN SQL — le volume de modules reste faible et le code
  est plus lisible.

## 7. Points à confirmer

Aucun.

## 8. Rapport final

- Fichiers modifiés : `app/identity/service.py`, `app/identity/router.py`,
  `app/modules_registry/schemas.py`, `app/modules_registry/service.py`,
  `app/modules_registry/router.py`.
- Tests ajoutés : `tests/test_identity_organizations.py`,
  `tests/test_modules.py` (2 nouveaux cas).
- Vérifié par suite pytest complète + appels curl réels contre un serveur
  de développement live.
