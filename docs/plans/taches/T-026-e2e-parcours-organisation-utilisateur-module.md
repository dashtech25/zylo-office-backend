# T-026 : Parcours E2E Playwright : organisation, utilisateur, affectation à un module

> **Suspendue le 2026-10-09** : Playwright suspendu par décision du client. Voir `docs/process/decision-playwright-suspendu.md`.

- **Statut** : Suspendue · **Priorité** : P1 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend et backend · **Domaine** : iam · **Type** : test
- **Branche suggérée** : `test/T-026-e2e-parcours-socle` · **Base de test** : `zylo_t026_test` · **Ports** : back 3126, front prod 3326
- **Dépendances** : T-024, T-025, T-046
- **Décisions requises** : aucune

## Objectif
Un parcours métier complet, sur build de production : créer une organisation, créer ses utilisateurs, affecter un utilisateur à un module avec des droits propres, activer le compte, puis vérifier que son droit s'applique au module A et pas au module B.

## Problèmes résolus
- Lacune « aucun E2E sur utilisateurs ni rôles » (DOC-021), REV-D-19 (partie UI : refus visible, URL directe)

## Dépendances : justification
- T-024 : écran de création testé.
- T-025 : écran d'affectation testé.
- T-046 : fixtures e2e isolées.
- Retirées (confort ou CI, pas de prérequis technique) : T-008 (confort) ; T-047 (confort : cas déjà couverts par T-047 et l'API).

## Fichiers / modules concernés
- `e2e/proprietaire-socle-utilisateurs-modules.spec.ts` (créé)
- `e2e/fixtures/` (données du parcours, créées par le test)

## Stratégie
1. Scénario : (a) propriétaire crée une organisation ; (b) crée deux utilisateurs (`pending`) ; (c) active les modules A et B ; (d) affecte l'utilisateur 1 au module A (gestion) et au module B (lecture) ; (e) active le compte de l'utilisateur 1 par le lien de T-049 ; (f) connexion, changement de mot de passe, vérification des droits par module.
2. Chaque étape est une assertion, avec capture et trace.
3. Données créées par le test, pas par le global-setup.

## Tests attendus
- `npm run e2e:prod` : scénario vert, trois exécutions consécutives sans échec.
- Refus visible sur un module non affecté ; URL directe refusée sans donnée affichée.

## Critères d'acceptation
- Parcours vert sur build prod, sans `waitForTimeout`, sur `zylo_t026_test`.
- Stabilité sur trois exécutions.

## Risque et retour arrière
Moyen : dépend de T-049 pour l'activation. Si l'envoi d'e-mail n'est pas décidé, le parcours utilise l'adaptateur journal de développement, déclaré explicitement dans la fiche de test.

## Livrable documentaire
- `docs/process/tests.md` (parcours et données).

## Parallélisable avec
T-037b, T-039, T-040 (fichiers distincts).
