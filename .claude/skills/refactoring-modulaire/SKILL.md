---
name: refactoring-modulaire
description: Découpe un module ou un fichier volumineux en packages et fichiers à responsabilité unique, sans changer le comportement.
when_to_use: Quand un fichier dépasse la taille raisonnable, mélange plusieurs responsabilités, ou doit être extrait vers une capacité partagée.
allowed-tools: Read Grep Glob Edit Write Bash
---

# Refactoring modulaire

Principe : le comportement ne change pas. Chaque étape se vérifie par les tests avant la suivante.

1. Lire la cible et ses appelants (`grep -rn "from app.<cible>"`).
2. Lister les responsabilités ; une responsabilité = un fichier.
3. Déplacer par petites étapes : d'abord les constantes et types purs, puis les services, puis les routers. Garder un alias de compatibilité le temps de la transition si des appelants externes existent.
4. Après chaque étape : `.venv/bin/pytest` ciblé, puis `.venv/bin/lint-imports` si disponible.
5. Mettre à jour `docs/architecture/packages.md` et le contrat `.importlinter` si un package change de niveau.
6. Ne jamais déplacer un module métier dans une capacité partagée sans décision écrite dans `docs/questions/`.

Commit par étape, en français, trailers présents.
