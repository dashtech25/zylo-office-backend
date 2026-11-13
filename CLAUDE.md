# Zylo Office : backend (point d'entrée pour Claude)

Ce fichier est court par choix. La documentation détaillée est dans `docs/`, et `docs/README.md` en donne l'index. En cas de conflit, la doc citée fait foi.

Zylo Office est un monolithe modulaire : socle (identité, organisations, rôles, permissions, registre de modules, abonnements) et modules métier (`zylo_liquid`, `zylo_tanker`).

## Commandes

```bash
.venv/bin/pytest                                  # tests
.venv/bin/alembic upgrade head                    # migrations
.venv/bin/uvicorn app.main:app --reload --port 3002   # checkout principal
```

Ports (checkout, worktrees, interdits) : [`docs/process/ports.md`](docs/process/ports.md). Démarrage complet : [`docs/process/local-setup.md`](docs/process/local-setup.md).

## Architecture : règles dures

Sens de dépendance (strict) :

```text
modules/<x>  ->  shared/, core/, identity/, rbac/, <capacité>/     autorisé
shared/, core/, <capacité>/  ->  modules/<x>                       INTERDIT
<capacité> A -> <capacité> B                                       INTERDIT
```

1. Un module n'interroge jamais les tables d'un autre module : il passe par les fonctions publiques de `service.py`.
2. Un module métier ne possède jamais une capacité partagée (fichiers, alertes, localisation, auth) : il la consomme.
3. Toute intégration externe passe par un adaptateur (ex. `app/integrations/holykell/`).
4. `core/` et `shared/` n'importent jamais depuis `app/modules/`. Une règle spécifique à un module va dans ce module.
5. `import-linter` (`.importlinter`) fait respecter ces contrats. Un nouvel import entre packages exige un contrat, pas une exception implicite.

Détail : [`docs/architecture/regles-dures.md`](docs/architecture/regles-dures.md), [`docs/architecture/packages.md`](docs/architecture/packages.md), [`docs/architecture/appel-direct-ou-evenement.md`](docs/architecture/appel-direct-ou-evenement.md).

## Avant de créer quelque chose

Réutiliser avant de créer : `shared/` (pagination, schémas, devises, géo), puis `core/` (sécurité, erreurs), puis étendre un service ou un router existant. Créer seulement ensuite. Conventions de nommage et d'API : [`docs/architecture/conventions-api.md`](docs/architecture/conventions-api.md). Structure d'un module et checklist d'ajout : [`docs/architecture/convention-module.md`](docs/architecture/convention-module.md).

## Sécurité, IAM et permissions

- Refus par défaut. Une seule fonction décide : `rbac/service.py::user_has_permission`. Le contrôle par module passe par `rbac/module_rights.py`.
- Permissions au format `domaine.entite.action`, déclarées dans `permissions.py` **et** `seed.py` du module. Sans cela, `require_permission()` refuse, y compris au propriétaire.
- Un rôle de module ne contient que ses permissions ou celles du socle partagé ; un utilisateur a au plus un rôle par module et organisation.
- Modèle complet : [`docs/architecture/securite/modele-organisations-roles.md`](docs/architecture/securite/modele-organisations-roles.md) ; matrice routes et permissions : [`matrice-autorisation.md`](docs/architecture/securite/matrice-autorisation.md) (générée, ne pas éditer à la main).
- Échec fermé sur les secrets hors développement ([ADR 0003](docs/architecture/decisions/0003-echec-ferme-secrets.md)). JWT avec PyJWT ([ADR 0004](docs/architecture/decisions/0004-pyjwt-remplace-python-jose.md)).
- Champs sensibles chiffrés (mot de passe Holykell, `APP_FIELD_ENCRYPTION_KEY`) : [ADR 0005](docs/architecture/decisions/0005-chiffrement-champs-holykell.md). Aucune valeur de clé, de secret ou de mot de passe dans le dépôt, les journaux ou les réponses.
- Un contrôle de sécurité qui échoue bloque la livraison ; il ne se contourne pas par un `try` silencieux.

## Données et migrations

- Tables en camelCase, en anglais, commentées. Migrations Alembic avec downgrade écrit ; pas de migration au démarrage ([`docs/workflows/migration.md`](docs/workflows/migration.md)).
- Dumps, `.env*` (sauf `.env.example`) et clés ne sont jamais versionnés (`scripts/dev/controle_fichiers_sensibles.sh`).
- Les tests utilisent une base `zylo_t<NNN>_test` ou `zylo_office_test`, jamais une base de dev, de recette ou de production.

## Git et livraison

- Branche de travail `remy`. Une tâche = une branche et un worktree (`scripts/dev/env_tache.sh creer <NNN> back`). Procédure : [`docs/process/git-workflow.md`](docs/process/git-workflow.md).
- Commits en français, trailers `Co-Authored-By` et `Claude-Session` en fin de message. Un sujet par commit.
- Interdit sans accord écrit : fusion, push, réécriture d'historique, `git reset --hard`, `git stash` ou `git clean` sur du travail non commité, `--no-verify`.
- Avant un gros changement : `git status`. Si des fichiers sont modifiés par un autre travail, rester chirurgical sur ces fichiers.
- Workflow de bout en bout : [`docs/workflows/bout-en-bout.md`](docs/workflows/bout-en-bout.md). Contrôles avant livraison : [`docs/workflows/validation-avant-livraison.md`](docs/workflows/validation-avant-livraison.md).
- La CI est désactivée (`ci.yml.disabled`, DOC-001) : les contrôles sont manuels.

## Documentation et questions

- Un fichier de documentation traite un seul sujet. Seuil : 300 lignes hors `docs/archive/` (à confirmer, [`seuil-taille-docs.md`](docs/questions/process/seuil-taille-docs.md)).
- Index régénérable : `scripts/docs/generer_index.sh`. Liens : `scripts/docs/verifier_liens.sh`. Plan : `python3 scripts/docs/check_plan.py`.
- Une décision non évidente va dans `docs/questions/<catégorie>/<sujet>.md`, avec une recommandation vérifiée. Une décision durable devient une ADR ([`docs/architecture/decisions/`](docs/architecture/decisions/README.md)).
- Le code est commenté par intention : le pourquoi d'une contrainte, un invariant, un piège évité. Les docstrings décrivent le contrat. Ne pas paraphraser le code.
- Destinations des règles de l'ancien CLAUDE.md : [`docs/process/regles-claude-md.md`](docs/process/regles-claude-md.md).

## Décisions en vigueur

- Playwright est suspendu ([ADR 0006](docs/architecture/decisions/0006-playwright-suspendu.md)) ; repris le 2026-10-10 : un test par issue, écrit d'abord, en local. Hors issues, les critères restent pytest, tsc, lint et build locaux.
- Storybook est retiré du frontend ([ADR 0007](docs/architecture/decisions/0007-storybook-retire.md)).
- Ports : [ADR 0008](docs/architecture/decisions/0008-table-ports-unique.md).
- Rôles par module : [ADR 0002](docs/architecture/decisions/0002-roles-par-module.md).

## Agents et skills

- Agents (`.claude/agents/`) : `architecture`, `iam-permissions`, `backend`, `frontend`, `qualite-tests`, `documentation-recherche`, `revue`. Tous en `model: haiku`. Gabarit de délégation : [`docs/process/agents.md`](docs/process/agents.md).
- Skills (`.claude/skills/`) : `audit-architectural`, `roles-permissions`, `refactoring-modulaire`, `revue-securite`, `validation-avant-livraison`, `documentation-technique`, `nouvelle-adr`.

## Périmètre de ce fichier

Ce fichier couvre le dépôt backend. Le frontend a son propre `CLAUDE.md` (dans son dépôt), à consolider dans une tâche dédiée ([`agents-frontend.md`](docs/questions/process/agents-frontend.md)).
