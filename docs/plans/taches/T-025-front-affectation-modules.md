# T-025 : Frontend : affecter un utilisateur à un module et aligner la permission affichée

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : iam · **Type** : feature
- **Branche suggérée** : `feat/T-025-front-affectation-modules` · **Base de test** : `zylo_t025_test` · **Ports** : back 3125, front dev 3225, front prod 3325
- **Dépendances** : T-022, T-024, T-030
- **Décisions requises** : aucune

## Objectif
Dans chaque module, l'administrateur choisit un utilisateur et lui attribue des rôles propres au module. `PermissionContext` reflète la portée par module et le `deny`, pour que l'interface n'affiche aucun bouton qui échouerait en 403.

## Problèmes résolus
- IAM-014 (`can()` ignore la portée et le `deny`), FRT-015 (tanker sans contrôle de permission)

## Dépendances : justification
- T-022 : contrat de l'API d'affectation.
- T-024 : `PermissionContext` créé par T-024 et étendu ici.
- T-030 : coquille avec providers.

## Fichiers / modules concernés
- `src/core/rbac/PermissionContext.tsx`, `src/core/api/rbac.ts`
- `src/modules/zylo-liquid/screens/` : écran « Utilisateurs du module » (créé)
- `src/modules/zylo-tanker/components/ZyloTankerShell.tsx` (filtrage de navigation)

## Stratégie
1. Signature cible : `can(permissionCode: string, moduleCode?: string)`. La portée module est un paramètre explicite.
2. Table « module × permission » attendue pour les rôles par défaut, écrite dans la fiche et dans `docs/process/frontend-permissions.md`. Le critère Playwright s'appuie sur cette table.
3. Navigation filtrée par module actif et permission.
4. Écran d'affectation : liste des utilisateurs, cases des rôles du module, état vide et erreur.

## Tests attendus
- Unitaires : `can()` avec module et `deny` (`test:unit`).
- Playwright prod : utilisateur affecté au module A ne voit pas le module B ; le refus est visible.
- `tsc`, `build`.

## Critères d'acceptation
- Aucun bouton visible sans permission réelle pour le module (vérifié par la table).
- Tanker : navigation filtrée, mêmes providers que zylo-liquid.

## Risque et retour arrière
Moyen : filtrer la navigation peut masquer des écrans pour les comptes existants. Vérifier les rôles par défaut avant fusion.

## Livrable documentaire
- `docs/process/frontend-permissions.md` (créé : règle `can()` par module et table).

## Parallélisable avec
T-023 (backend tests) ; après T-030.
