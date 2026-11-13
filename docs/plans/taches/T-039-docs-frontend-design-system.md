# T-039 : Documentation frontend en arborescence, design system de référence unique, arbre généré

- **Statut** : Terminée (docs frontend fusionnées dans le frontend `remy` : `e8a559f` ; critères tenus : une seule référence de design system, aucun chiffre daté, `CLAUDE.md` à 142 lignes, arbre généré vérifié par `generer_arbre.sh --verifier`) · **Priorité** : P2 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : docs · **Type** : docs
- **Branche suggérée** : `docs/T-039-frontend-arborescence` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-030, T-032, T-043
- **Décisions requises** : aucune

## Objectif
Régénérer l'arborescence réelle de `src/` dans la documentation (et non à la main dans `CLAUDE.md`), retirer les chiffres périmés, déplacer les analyses de design system en archive avec un statut de décision, et découper `docs/frontend-foundations.md`. Le catalogue de composants (T-043) est la seule liste des composants.

## Problèmes résolus
- DOC-007 (arborescence de `CLAUDE.md` obsolète), DOC-016 (deux sources de design system), DOC-009 et DOC-013 (partie frontend), DOC-014 (références `grande_phases.md`), REV-D-02 (partie), REV-D-29 (audit non à jour)

## Dépendances : justification
- T-030 : coquille décrite par la doc.
- T-032 : tokens décrits par la doc.
- T-043 : catalogue de composants cité par la doc.
- Retirées (confort ou CI, pas de prérequis technique) : T-011 (confort).

## Fichiers / modules concernés
- `docs/process/frontend-structure.md` (créé, généré)
- `docs/architecture/frontend/README.md` (créé)
- `docs/frontend-foundations.md` (découpé)
- `docs/design-system-zylo-liquid-reference-analysis.md` (déplacé dans `docs/archive/` avec statut)
- `docs/audit/frontend-design.md` : section « état à la date de la branche de référence » (REV-D-29)

## Stratégie
1. Script qui produit l'arbre de `src/` ; la doc l'inclut, elle n'en recopie pas.
2. Un seul design system de référence (T-032) ; l'analyse passe en archive avec « décidé » ou « rejeté » par écart.
3. Chaque règle renvoie vers une section de doc, sans la recopier.

## Tests attendus
- Script de vérification : les chemins cités existent.
- Relecture d'un échantillon.

## Critères d'acceptation
- Une seule référence de design system.
- Aucun chiffre périmé (« 10 écrans ») dans la doc.
- `CLAUDE.md` frontend allégé : moins de 200 lignes (détail dans T-040).

## Risque et retour arrière
Aucun pour le code. Risque d'obsolescence : la génération est automatisée.

## Livrable documentaire
- `docs/architecture/frontend/README.md`, `docs/process/frontend-structure.md`.

## Parallélisable avec
T-037b, T-040 (T-040 attend cette tâche).
