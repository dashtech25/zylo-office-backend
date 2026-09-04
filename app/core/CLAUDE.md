# app/core/ — fondation transverse, jamais un module métier

Voir la directive complète : `/CLAUDE.md` (racine du dépôt).

`config.py`, `database.py`, `security.py`, `errors.py`, `logging.py`,
`middleware.py` : mécanismes qui concernent **l'application elle-même**,
utilisés par tous les domaines (socle et modules métier) sans exception.

**Interdiction stricte** : ne jamais importer `app.modules.*` depuis ce
dossier. Si tu es tenté d'ajouter ici une règle spécifique à un module
(zylo_liquid ou futur CRM/Stock), elle appartient à
`app/modules/<domaine>/service.py` ou `permissions.py`, pas ici.

Avant d'ajouter quelque chose ici, vérifie que ce sera vraiment utilisé par
**tous** les futurs modules, pas seulement celui sur lequel tu travailles.
