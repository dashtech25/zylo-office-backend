# ADR 0001 : Monolithe modulaire, pas de microservices

- **Date** : antérieure à 2026-10-08 (décision actée dans l'architecture backend).
- **Statut** : Acceptée.
- **Source** : [`docs/architecture/monolithe-modulaire.md`](../monolithe-modulaire.md) (archive d'origine : `docs/archive/ARCHITECTURE.md`, §1).

## Contexte

Un seul VPS, une petite équipe, aucun besoin de mise à l'échelle indépendante d'un module.

## Décision

Zylo Office est un monolithe modulaire avec événements de domaine en mémoire : un déploiement, une base PostgreSQL, un historique Alembic, mais des frontières entre modules aussi strictes que si elles étaient séparées.

## Conséquences

- Les frontières sont vérifiées par `import-linter` (contrats dans `.importlinter`).
- Une extraction physique d'un module reste possible plus tard, parce que les frontières sont déjà propres. Ce n'est pas le point de départ par défaut.
- Les capacités partagées (fichiers, alertes, localisation, intégrations) vivent au premier niveau de `app/`, jamais dans `app/modules/`.

## Alternatives écartées

Microservices : coût d'infrastructure et d'exploitation disproportionné à la taille actuelle.
