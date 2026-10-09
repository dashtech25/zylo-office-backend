# T-017 : Refonte de la documentation backend en arborescence de petits fichiers

- **Statut** : À vérifier · **Priorité** : P2 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : docs · **Type** : docs
- **Branche suggérée** : `docs/T-017-arborescence-backend` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-003, T-016
- **Décisions requises** : aucune

## Objectif
Remplacer les gros fichiers (`validation_log.md` 598 lignes, `phase-2-api.md` 907, `phase_1_database.md` 253, `ARCHITECTURE.md`) par une arborescence de petits fichiers reflétant le code réel. Un fichier, un sujet. Les rapports de livraison vont en archive.

## Problèmes résolus
- DOC-005 (`zylo_tanker` non documenté), DOC-006, DOC-009, DOC-010, DOC-011, DOC-013, DOC-015 (fichiers parasites), DOC-022, DOC-023, DOC-024, ARC-019

## Dépendances : justification
- T-003 : table des ports citée dans la documentation créée par T-003.
- T-016 : dossier `docs/process/` et script de liens créés par T-016.

## Fichiers / modules concernés
- `docs/` (réorganisation), `README.md`, `ARCHITECTURE.md`, `phase_1_database.md`, `validation_log.md` (déplacés ou remplacés par des liens)
- `docs/modules/zylo-tanker/README.md` (créé)
- `docs/architecture/packages.md` (arbre réel de `app/`, source unique)

## Stratégie
1. Arborescence cible : `architecture/`, `core/`, `modules/zylo-liquid/`, `modules/zylo-tanker/`, `requirements/`, `process/`, `archive/`.
2. Découper `phase-2-api.md` par domaine d'API. `validation_log.md` en trois niveaux plus un suivi, avec date et commit par ligne.
3. Déplacer les rapports « final » dans `archive/` sans les réécrire.
4. `docs/README.md` généré à partir de l'arborescence (liste, pas de texte recopié).
5. Supprimer `teste.html` (0 octet) et `test.txt`.

## Tests attendus
- Script de liens : tous les liens internes de `docs/` existent.
- Aucun fichier hors `archive/` au-dessus de 300 lignes (seuil à confirmer dans la PR).

## Critères d'acceptation
- Un seul arbre `packages.md` ; les README le référencent.
- `zylo_tanker` documenté.
- Aucun fichier hors `archive/` au-dessus du seuil.

## Risque et retour arrière
Aucun pour le code. Risque de perte d'information : déplacer sans réécrire, puis résumer.

## Livrable documentaire
- L'arborescence `docs/` et `docs/README.md` généré.

## Parallélisable avec
T-006 à T-015 (aucun code touché).
