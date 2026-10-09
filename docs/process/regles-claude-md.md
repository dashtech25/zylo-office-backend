# Destination des règles de l'ancien CLAUDE.md du backend

- **Statut** : inventaire de la consolidation T-040. Chaque règle a une destination ; aucune n'est supprimée sans motif.
- **Vérification** : relecture ligne à ligne de l'ancien `CLAUDE.md` (194 lignes) contre les destinations ci-dessous.

| Règle de l'ancien CLAUDE.md | Destination |
|---|---|
| Directive : le socle n'est pas une simple API ; `grande_phases.md` hors dépôt | `CLAUDE.md` (résumé) ; [`docs/questions/process/`](../questions/process/) pour le lien hors dépôt (DOC-014) |
| Règle qui prime : `core/`, `shared/`, domaines du socle, capacités, modules, `api/v1/` | `CLAUDE.md` (résumé) ; [`packages.md`](../architecture/packages.md) |
| Direction de dépendance stricte et interdits | `CLAUDE.md` ; [`regles-dures.md`](../architecture/regles-dures.md) |
| Convention d'un module métier (structure de fichiers) | [`convention-module.md`](../architecture/convention-module.md) |
| Monolithe modulaire, pourquoi pas microservices | [`monolithe-modulaire.md`](../architecture/monolithe-modulaire.md), [ADR 0001](../architecture/decisions/0001-monolithe-modulaire.md) |
| Capacités en cours d'extraction (files, location, alerts, integrations) | [`etat-migration.md`](../architecture/etat-migration.md) |
| Règles dures 1 à 3 (pas de table d'un autre module, pas de capacité possédée, adaptateur) | `CLAUDE.md` (résumé) ; [`regles-dures.md`](../architecture/regles-dures.md) |
| Appel direct ou événement : tableau de choix | [`appel-direct-ou-evenement.md`](../architecture/appel-direct-ou-evenement.md) |
| `import-linter` : vérification technique | `CLAUDE.md` ; [`verification-import-linter.md`](../architecture/verification-import-linter.md) |
| Séquence obligatoire avant de créer ; nommage et contrat d'API | [`conventions-api.md`](../architecture/conventions-api.md) |
| Checklist d'ajout d'un module | [`convention-module.md`](../architecture/convention-module.md) |
| Méthode de travail : une famille à la fois, vérification après chaque changement ; `git status` avant un gros changement | `CLAUDE.md` (résumé) ; [`bout-en-bout.md`](../workflows/bout-en-bout.md) |
| Commandes pytest, alembic, uvicorn (port) | `CLAUDE.md` ; [`local-setup.md`](local-setup.md) ; [`ports.md`](ports.md) |
| Port 3007 dans `CLAUDE.md` (ligne 187) | Corrigé : renvoi vers [`ports.md`](ports.md) (DOC-002) |
| Arborescence de `app/` dans le README | Remplacée par [`packages.md`](../architecture/packages.md) (DOC-006) |
