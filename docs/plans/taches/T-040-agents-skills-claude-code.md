# T-040 : Agents et règles Claude Code : CLAUDE.md court, règles par zone, gabarit d'agent d'exécution

- **Statut** : Planifiée · **Priorité** : P2 · **Vague** : 3 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : docs · **Type** : docs
- **Branche suggérée** : `docs/T-040-agents-claude` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-016, T-017, T-039
- **Décisions requises** : aucune

## Objectif
Faire de `CLAUDE.md` un point d'entrée court (moins de 200 lignes) qui renvoie à la doc. Les règles propres à une zone vont dans `.claude/rules/` avec `paths:`. Définir le gabarit d'agent d'exécution (lire la fiche, créer le worktree, créer la base, exécuter, produire le résultat, ne jamais fusionner).

## Problèmes résolus
- Consigne `documentation-architecture-agents.md` (CLAUDE.md long, instructions dupliquées, règles non scopées), DOC-006 (partie), DOC-008 (partie)

## Dépendances : justification
- T-016 : workflow documenté.
- T-017 : arborescence backend documentée.
- T-039 : arborescence frontend documentée.

## Fichiers / modules concernés
- `CLAUDE.md` (backend et frontend) : réduction
- `.claude/rules/*.md` (créés, par zone : `securite.md`, `rbac.md`, `frontend-pages.md`, `migrations.md`)
- `docs/process/agents.md` (créé) : gabarit d'agent et rôles (orchestrateur, agent d'exécution)

## Stratégie
1. Inventaire des règles de chaque `CLAUDE.md` ; chaque règle reçoit une destination (fichier de règles, doc, ou suppression justifiée).
2. Gabarit : tâche, dépôt, branche, worktree, base, ports, fiche à lire en entier, fichiers autorisés, tests, « ne fusionne pas », « ne migre pas la production », « décision non évidente : question ».
3. Essai du gabarit sur une tâche de test sans modification de code.

## Tests attendus
- Vérification manuelle : chaque règle retirée a une destination (tableau dans la PR).
- Vérification de contradictions entre règles (relecture).
- `scripts/docs/check_plan.py` (T-016) vert.

## Critères d'acceptation
- `CLAUDE.md` backend et frontend inférieurs à 200 lignes.
- Règles par zone présentes dans `.claude/rules/`.
- Gabarit d'agent utilisable pour une tâche de test.

## Risque et retour arrière
Faible pour le code. Risque : règle perdue ; contrôlé par le tableau de destinations.

## Livrable documentaire
- `docs/process/agents.md`.

## Parallélisable avec
Rien de bloquant ; coordonner avec T-038b sur les fichiers `.github`.
