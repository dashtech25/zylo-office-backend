# T-024 : Frontend : création d'utilisateurs par l'administrateur d'organisation

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-024-front-creation-utilisateurs` · **Base de test** : `zylo_t024_test` · **Ports** : back 3124, front dev 3224, front prod 3324
- **Dépendances** : T-013, T-021, T-030
- **Décisions requises** : aucune (dépend de la validation client de T-021)

## Objectif
Un formulaire de création (e-mail, nom, rôle de l'organisation) dans l'écran « Utilisateurs ». Après création, l'écran indique que le titulaire recevra un lien d'activation : **aucun mot de passe n'est affiché**. Le bouton n'apparaît que si la permission existe.

## Problèmes résolus
- IAM-006 (côté interface), IAM-014 (boutons affichés sans portée), FRT-013 (validation partagée, T-013)

## Dépendances : justification
- T-013 : règles de mot de passe affichées au formulaire.
- T-021 : contrat de l'API de création.
- T-030 : coquille unique qui porte la page `users`.
- Retirées (confort ou CI, pas de prérequis technique) : T-012 (pas d'artefact front) ; T-042 (confort : tests unitaires non requis) ; T-008 (confort).

## Fichiers / modules concernés
- `src/app/(app)/users/page.tsx` (une ligne, délègue à l'écran)
- `src/core/screens/UsersScreen.tsx` (créé ; `core` car le socle n'est pas un module métier)
- `src/core/api/client.ts` (utilisation de `apiFetch` ; pas de modification ici)
- `src/core/rbac/PermissionContext.tsx` (lecture de `can()`)

## Stratégie
1. Composant d'écran dans `screens/`, page d'une ligne.
2. `shared/ui` (Modal, FormField, Button) sans nouveau CSS.
3. Affichage de l'état « en attente d'activation », jamais de secret côté client.
4. États de chargement et d'erreur (`isError`) gérés.

## Tests attendus
- Unitaires : validation partagée (e-mail, champs requis).
- Tests pytest / tsc / lint / build locaux (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`) ; comportement non couvert par un test automatisé : propriétaire crée un utilisateur ; le formulaire ne montre aucun mot de passe ; le bouton est absent pour un membre sans permission.
- Scénario d'activation complet : porté par T-026.
- `tsc`, `build`, `test:unit`.

## Critères d'acceptation
- Bouton visible seulement si la permission existe ; vérification à deux comptes non automatisée (Playwright suspendu, voir `docs/process/decision-playwright-suspendu.md`).
- Aucune donnée secrète affichée ou stockée côté client.

## Risque et retour arrière
Moyen : la page `users` existe déjà (230 lignes, ARC-013). Retour arrière : revert de l'écran ; la page précédente reste.

## Livrable documentaire
- `docs/process/frontend-screens.md` (complété).

## Parallélisable avec
T-022 et T-049 (backend) ; après T-030 sur `users/page.tsx`.
