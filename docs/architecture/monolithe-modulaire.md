# Pourquoi un monolithe modulaire

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.


Détail complet de l'architecture "monolithe modulaire" et de la migration en
cours pour y arriver. Les règles courtes à respecter au quotidien sont dans
`CLAUDE.md` (lu automatiquement en début de session) — ce document explique
le "pourquoi" et le "comment" en profondeur, sert de référence quand une
règle du `CLAUDE.md` n'est pas assez précise pour un cas concret.

Source du plan de migration approuvé (hors de ce dépôt, document de
cadrage) : `plan-migration/architecture-migration.md` dans le dépôt
`zylo_liquid_prototype`. Ce fichier-ci en est la traduction opérationnelle
pour ce dépôt, tenue à jour au fil des phases livrées.

## 1. Pourquoi un monolithe modulaire, pas des microservices

Zylo Office tourne aujourd'hui sur un seul VPS, avec une petite équipe.
Découper en microservices maintenant ajouterait :
- un bus de messages distribué (Kafka/RabbitMQ) et son exploitation,
- des déploiements et une observabilité par service,
- de la complexité réseau (retries, timeouts, cohérence éventuelle)

...pour un problème que le projet n'a pas : aucun module n'a besoin de
scaler indépendamment, la charge actuelle tient largement sur une seule
instance. Le coût serait payé tout de suite, le bénéfice (scalabilité
indépendante, déploiement isolé par équipe) n'a pas d'usage réel aujourd'hui.

La réponse retenue après la formation d'architecture (couplage/cohésion,
comparatif des architectures, patrons de communication) : **un seul
déploiement, une seule base Postgres, un seul historique Alembic — mais une
discipline de frontières entre modules imposée et vérifiée techniquement**
(voir §4, `import-linter`). Si un jour un module a un besoin de charge
mesuré (pas supposé) qui justifie une extraction physique, les frontières
propres rendent cette extraction possible sans réécriture — mais ce n'est
jamais le point de départ par défaut, et rien dans ce plan n'anticipe une
telle extraction avant qu'elle soit prouvée nécessaire.
