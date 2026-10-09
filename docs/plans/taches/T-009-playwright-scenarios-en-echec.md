# T-009 : Corriger les 10 scénarios Playwright en échec

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : frontend (+ backend si la donnée manque) · **Domaine** : zylo-liquid · **Type** : test
- **Branche suggérée** : `fix/T-009-playwright-echecs` · **Base de test** : `zylo_t009_test` · **Ports** : back 3109, front prod 3309
- **Dépendances** : T-046
- **Décisions requises** : `tests/holykell-simulateur.md`

## Objectif
Trier les 10 échecs de la baseline (9 scénarios gérant et P7 Holykell) : pour chacun, identifier si le défaut est dans le test, les données, le backend ou l'interface. Corriger ou requalifier, sans affaiblir une assertion.

## Problèmes résolus
- Baseline section 3 : `gerant-01`, `gerant-affectation-pompistes`, `gerant-fermeture-index`, `gerant-jaugeage-cuves`, `gerant-ouverture-tour`, `gerant-planning-grille`, `gerant-pointage-passation`, `gerant-remplacement-pauses`, `gerant-tours-tableau`, `proprietaire-07-connexion-holykell`
- REV-S-17, REV-S-25 (identifiants externes), REV-D-22 (P7 et tag inexistant), REV-D-24 (sélecteurs couplés)

## Dépendances : justification
- T-046 : fixtures e2e isolées importées par les scénarios corrigés.

## Fichiers / modules concernés
- `e2e/` : specs gérant et P7
- Écrans `src/modules/zylo-liquid/screens/station-*` (si défaut UI), endpoints de tours, pointage, jaugeage (lecture seule au départ)
- `playwright.config.ts` : tag `@external`

## Stratégie
1. Relancer les 10 specs sur base vierge, capturer trace et vidéo.
2. Classer chaque échec : (a) donnée manquante ; (b) sélecteur ou message changé ; (c) défaut backend ; (d) défaut UI. Tableau dans la PR.
3. Corriger (a) et (b) dans les specs. Ouvrir (c) et (d) dans la tâche concernée, ou ici si le correctif est petit.
4. P7 : tag `@external`, exclu de la CI par `--grep-invert @external`. Les identifiants Holykell de test sont lus depuis l'environnement, jamais versionnés.
5. Sélecteurs : rôle et nom accessible d'abord, `data-testid` ensuite, jamais de `locator("..")`, `xpath=` ni `option:checked` non vérifiée contre le composant rendu (`SearchableSelect` ou `<select>`).
6. Retirer les entrées de `known_failures.txt` au fur et à mesure.

## Tests attendus
- 9 scénarios gérant verts sur build prod ; P7 exclu par tag.
- `git diff` des fichiers `e2e/` : aucune assertion supprimée (contrôle scripté, consigné dans la PR).

## Critères d'acceptation
- 26 tests passent, 1 test P7 est marqué `@external` et exclu explicitement (la cible est « 26 passent et 1 exclu », pas « 26/27 »).
- Aucun échec sans cause écrite dans la PR.
- Aucun `waitForTimeout` ajouté.
- `docs/questions/tests/holykell-simulateur.md` tranché ou en attente, avec son état.

## Risque et retour arrière
Faible pour le code de production. Risque de faux vert si l'on assouplit une assertion : interdit par le contrôle scripté.

## Livrable documentaire
- `docs/questions/tests/holykell-simulateur.md`
- `docs/process/tests.md` (classement des échecs)

## Parallélisable avec
T-006, T-007, T-010 à T-015 (pas les specs partagées avec T-026 et T-024).
