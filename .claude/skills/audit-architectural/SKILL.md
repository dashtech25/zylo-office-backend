---
name: audit-architectural
description: Audite les frontières entre packages du backend (modules, capacités partagées, core, shared) et signale les violations.
when_to_use: Quand l'utilisateur demande un audit d'architecture, une vérification des frontières, ou après un ajout de module ou d'import entre packages.
allowed-tools: Read Grep Glob Bash
---

# Audit architectural

1. Lire `docs/architecture/regles-dures.md` et `docs/architecture/packages.md`.
2. Lire `.importlinter` : contrats déclarés.
3. Lancer `.venv/bin/lint-imports` si disponible ; sinon, chercher les imports interdits :
   - `grep -rn "from app.modules" app/core app/shared` (interdit) ;
   - `grep -rn "from app.<module>.models" app/modules` (table d'un autre module) ;
   - imports entre capacités (`app/files`, `app/alerts`, `app/location`).
4. Pour chaque violation : fichier:ligne, règle, contrat ou ADR concerné, correction proposée.
5. Vérifier que tout nouveau package a un contrat `.importlinter` et une entrée dans `docs/architecture/packages.md`.

Ne modifie aucun fichier. Rends le rapport avec les violations classées par gravité.
