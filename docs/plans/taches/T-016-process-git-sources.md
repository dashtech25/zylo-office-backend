# T-016 : Process git, labels et exigences versionnées, script de contrôle du plan

- **Statut** : À vérifier · **Priorité** : P2 · **Vague** : 1 · **Taille** : S · **Dépôt(s)** : backend et frontend · **Domaine** : docs · **Type** : docs
- **Branche suggérée** : `docs/T-016-process` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-004
- **Décisions requises** : `process/visibilite-depot-requirements.md`

## Objectif
Documenter le workflow git réellement suivi, préparer les labels, rendre versionnées les exigences terrain (`docs/requirements/`), copier les extraits sourcés des sources hors dépôt, et versionner le script qui contrôle la cohérence du plan (fiches, registre, questions, ports, bases).

## Problèmes résolus
- DOC-018, DOC-020, DOC-004 (cahiers métier hors versionnement), DOC-012 (copies « (1) » et « (2) »), DOC-014 (références absentes), DOC-021 (exigences socle), REV-A-13 (contrôle des dépendances)

## Dépendances : justification
T-004 (base et plan versionnés). Bloque T-017 et T-040.

## Fichiers / modules concernés
- `docs/process/git-workflow.md` (complété par T-004), `docs/process/labels.md` (créé)
- `docs/requirements/socle-organisations-utilisateurs-modules.md` (créé, sourcé : date et chemin de la source)
- `scripts/docs/check_plan.py` (créé) : vérifie que les dépendances des fiches sont cohérentes, que la vague ne décroît jamais le long d'une dépendance, qu'il n'y a pas de cycle, que les ports suivent la formule, que les noms de base suivent la règle, et que les questions citées existent. Régénère `REGISTRE_TACHES.md` et `ISSUES_A_CREER.md`.
- `.gitignore` : déjà corrigé par T-004 (ancrage de `/taches/`).

## Stratégie
1. Question `process/visibilite-depot-requirements.md` : recommandation appliquée : `docs/requirements/` dans le dépôt backend, après contrôle de visibilité (T-001). Si le dépôt est public, les exigences restent hors dépôt.
2. Renommer les copies « (1) » et « (2) », factoriser l'en-tête commun.
3. `check_plan.py` s'exécute en CI (T-038a) : il échoue si le registre ou les issues ne sont pas régénérés.
4. Labels : `priority:P0..P3`, `wave:0..3`, `area:backend|frontend|docs|ci|iam|security`, `type:...`, `module:zylo-liquid|zylo-tanker|socle` (créés sur GitHub par l'orchestrateur).

## Tests attendus
- Script de liens : les chemins cités dans les docs existent.
- `check_plan.py` : sortie verte sur le plan final.

## Critères d'acceptation
- `git-workflow.md` et `labels.md` existent et sont référencés par les README.
- `docs/requirements/` versionné, extrait sourcé présent.
- `check_plan.py` vert, régénération du registre et des issues reproductible.

## Risque et retour arrière
Faible pour le code. Risque de publication : les cahiers contiennent des données terrain. Vérifier l'absence de secrets avant de versionner.

## Livrable documentaire
- `docs/process/git-workflow.md`, `docs/process/labels.md`, `docs/requirements/socle-organisations-utilisateurs-modules.md`

## Parallélisable avec
T-006 à T-015, T-051.
