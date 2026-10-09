# T-043 : Catalogue de composants dans docs/ (un fichier par composant partagé)

- **Statut** : Planifiée · **Priorité** : P1 · **Vague** : 0 · **Taille** : M · **Dépôt(s)** : frontend · **Domaine** : docs · **Type** : docs
- **Branche suggérée** : `docs/T-043-catalogue-composants` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : aucune
- **Décisions requises** : aucune

## Objectif
Remplacer le catalogue perdu avec Storybook : une arborescence `docs/architecture/frontend/catalogue-composants/` avec un fichier par composant exporté par `src/shared/ui/index.ts`, plus un index. Un script de contrôle échoue si un export n'a pas son fichier.

## Problèmes résolus
- REV-D-02 (aucune documentation des composants après le retrait), FRT-014 (remplacé)

## Dépendances : justification
- Retirées (confort ou CI, pas de prérequis technique) : T-041 (le catalogue ne lit pas les stories : pas d'artefact consommé).

## Fichiers / modules concernés
- `docs/architecture/frontend/catalogue-composants/README.md` (index généré)
- `docs/architecture/frontend/catalogue-composants/<Composant>.md` : un fichier par export de `src/shared/ui/index.ts`
- `scripts/docs/check_catalogue.sh` (créé) : compare exports et fichiers

## Stratégie
1. Générer le squelette (nom, chemin du source, exports) à partir de `src/shared/ui/index.ts`.
2. Remplir à la main, par composant : rôle, props principales, variantes, états, exemple court, règles d'accessibilité (une section par sujet).
3. Index généré par script, pas à la main.
4. Les composants qui seront déplacés ou créés par T-033a, T-033b, T-033c sont mis à jour par ces tâches (une ligne dans leur critère).

## Tests attendus
- `scripts/docs/check_catalogue.sh` : nombre de fichiers composant égal au nombre d'exports ; échec si un export manque.
- Liens internes du catalogue valides.

## Critères d'acceptation
- Chaque export de `shared/ui` a son fichier ; le contrôle est vert.
- Aucune story ni Storybook référencée dans le catalogue.
- `docs/frontend-foundations.md` renvoie vers le catalogue, sans le recopier.

## Risque et retour arrière
Faible. Le catalogue peut dériver : d'où le contrôle de T-043 et sa mise à jour dans T-033a à T-033c.

## Livrable documentaire
- `docs/architecture/frontend/catalogue-composants/README.md` et un fichier par composant.

## Parallélisable avec
T-042, T-011.
