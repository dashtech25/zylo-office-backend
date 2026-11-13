# Plan de remise sur pied : Zylo Office

- **Date** : 2026-10-08 · **Statut** : planifié, aucune tâche démarrée · **Version** : 2 (révisé après revue ; décisions par constat dans `REVUE_PLAN.md`)
- **Périmètre** : backend (plan transverse) et frontend (tâches référencées) · **Sources** : `docs/audit/`, `docs/architecture/bonnes-pratiques/`, `docs/plans/revues/`
- **Index** : `REGISTRE_TACHES.md` (58 tâches, généré), `taches/T-XXX-*.md` (fiches, source de vérité), `ISSUES_A_CREER.md` (généré), `docs/questions/` (28 décisions)

## 1. Vision

1. **Sécurité d'abord** : aucune donnée réelle ne doit fuir (dump, secrets, jetons de test), et aucune organisation ne doit pouvoir agir sur une autre (IDOR, toutes les routes d'organisation).
2. **Priorité n°1 : socle IAM par module.** Créer une organisation, créer ses utilisateurs (compte en attente, activation par le titulaire), puis, dans chaque module, affecter un utilisateur avec des droits propres à ce module. Modèle : `Role.moduleCode` nullable, sans élargissement automatique de droits existants.
3. **Stabiliser avant de refactorer** : une CI bloquante existe dès la vague 1 ; les 22 échecs pytest et les 10 échecs Playwright sont corrigés ou marqués avec une décision datée.
4. **Dette structurelle par lots prudents** : coquille de navigation, tokens, découpe de `zylo_liquid/service.py` (15 681 lignes), contrats d'architecture.
5. **Documentation vivante** : petits fichiers reflétant le code, décisions métier dans `docs/questions/`, registre et issues générés à partir des fiches.

## 2. Règles d'exécution (contrat pour tous les agents)

- **Base de référence** : la tâche T-004 pose le tag `base-T004` sur `remy` dans les deux dépôts. Aucune autre tâche ne démarre avant. Les tâches partent de ce tag ou d'un commit ultérieur déjà fusionné.
- **Branches** : `<type>/T-XXX-<slug>` (types : `fix`, `feat`, `refactor`, `test`, `docs`, `ci`, `chore`). Une tâche à lettre (T-033b, T-035c…) part de la branche de la lettre précédente, quand elle est dans la même chaîne.
- **Worktrees** : un par tâche et par dépôt, dans `office/worktrees/T-XXX-<back|front>` (dossier frère des dépôts, hors dépôt). Le dossier `worktrees/` existe déjà (`frontend-retirer-storybook`).
- **Bases de test** : `zylo_t<NNN>[a-z]?_test` (NNN = numéro de tâche). Interdit : `zylo`, `zylo_office`, `zylo_dev`, `zylo_liquid`, `zylo_recette`, et toute base sans suffixe `_test`. La garde est commune à pytest et à Playwright (T-005).
- **Ports** (table unique dans `docs/process/ports.md`, T-003) : checkout principal backend 3002, frontend dev 3001, Playwright prod 3055 ; worktrees : backend 3100+n, frontend dev 3200+n, frontend prod 3300+n. Interdits : 3006, 3007. Les lettres d'une même tâche partagent n et s'exécutent en chaîne.
- **Playwright** : seul le build de production fait foi (`next build`, puis `next start`). Jamais `npm run dev`. **Aucun résultat Playwright n'est déclaré sans une configuration versionnée dans le dépôt, exécutée sur le build de production.** La première est créée par T-041 (smoke), puis étendue par T-008.
- **Vague et niveau** : la **vague** (0 à 3) est un jalon de revue humaine ; le **niveau** est la profondeur de dépendance, calculée. Invariant : pour toute dépendance, le niveau de la tâche est strictement supérieur à celui de la dépendance, et sa vague est supérieure ou égale. Une tâche démarre quand toutes ses dépendances sont fusionnées.
- **Fusions** : l'orchestrateur seul fusionne, vague par vague, dans l'ordre des fichiers chauds (§5). L'agent d'exécution ne fusionne jamais.
- **Migrations** : une seule tâche avec migration Alembic par vague à la fois, ou rebase avant fusion avec `alembic heads` = 1. Toute migration est additive et a un test de `downgrade` sur base jetable, sauf si la fiche déclare explicitement le contraire (retour arrière non restaurant).
- **Validation client avant fusion** : les tâches qui changent des droits existants ne sont pas fusionnées sans réponse écrite du client : T-007, T-018, T-021, T-049, T-048, T-050 (voir §7). Une décision non tranchée n'est jamais « appliquée » par défaut si elle touche des droits existants.
- **CI indépendante** : T-038a (vague 1) et T-038b (vague 2) sont des tâches parallèles, sans dépendance de confort. Aucune tâche n'est bloquée par la CI, et la CI n'est pas un prérequis de fusion. Décision du coordinateur : chaque tâche se valide par des tests exécutés en local. Les dépendances ne gardent que les prérequis techniques réels (table, colonne, module, contrat consommé), justifiés dans chaque fiche.
- **Interdits** : migration destructive (`DROP`, `TRUNCATE`, suppression de colonne) sans accord écrit ; opération sur la production ; réécriture d'historique git sans accord écrit ; `git stash`, `git checkout --` ou `git reset` sur du travail non commité.
- **Décisions non évidentes** : chacune crée ou complète `docs/questions/<catégorie>/<sujet>.md` (gabarit de `questions/README.md`). Pour un choix technique réversible, on avance sur la recommandation. Pour un choix qui change des droits ou des données, on attend la réponse.
- **Hypothèses** : toute hypothèse non sourcée est marquée dans la fiche et transformée en contrôle mesurable (script, test ou grep), jamais affirmée comme acquise.
- **Documentation** : petits fichiers, un sujet par fichier. Le registre, les issues et les listes de dépendances sont générés depuis les fiches.

## 3. Vagues

Les listes sont celles produites par le contrôle du plan (`check_plan`, §10). Le niveau est indiqué entre parenthèses.

> Les niveaux entre parenthèses de cette section datent de la version précédente du graphe. Source de vérité : `REGISTRE_TACHES.md` (régénéré depuis les fiches).

### Vague 0 : fondations (9 tâches)
- **Base et espace de travail** : T-004 (niv. 0) puis T-004b (niv. 1, tri restant, non bloquant).
- **Fondations** : T-001 retrait du dump (P0), T-002 refus de démarrage avec secrets par défaut (P0), T-003 table de ports et CORS configurable, T-005 environnement de test isolé et garde de base.
- **Storybook et tests unitaires** : T-041 retrait de Storybook et smoke Playwright sur build de production, T-042 Vitest minimal sans Storybook, T-043 catalogue de composants dans `docs/`.

### Vague 1 : stabilisation, sécurité périphérique, IAM de base (18 tâches)
- **CI** : T-038a CI minimale, tâche indépendante et parallèle (aucune dépendance).
- **Tests** : T-006 pytest (niv. 2), T-007 rôle manager, décision client (niv. 2), T-008 Playwright sur build de production et e2e versionnés (niv. 2), T-046 fixtures isolées (niv. 3), T-009 scénarios en échec (niv. 4).
- **IAM** : T-010 isolation inter-organisations, IDOR (P0, niv. 4).
- **Sécurité** : T-012 limitation de débit (niv. 2), T-013 mot de passe et réponses neutres (niv. 3), T-014 uploads (niv. 2), T-015 dépendances et surface API (niv. 2), T-027 chiffrement Holykell (niv. 2), T-051 conteneur, routeurs et routes de démonstration (niv. 5).
- **Processus et migrations** : T-016 process git et contrôle du plan (niv. 1), T-028 migrations hors démarrage (niv. 2), T-029 tâches de fond (niv. 4).
- **Dette** : T-034 découpe lot 1 (niv. 3). **Frontend** : T-011 hygiène (niv. 3).

### Vague 2 : modèle IAM par module, coquille frontend, architecture, CI complète (18 tâches)
- **IAM** : T-018 rôles par module (niv. 6), T-019 garde-fous IAM (niv. 5), T-020 sessions (niv. 4), T-021 création d'utilisateurs, compte en attente (niv. 7), T-023 matrice d'autorisation (niv. 6), T-050 permission plateforme explicite (niv. 6).
- **Frontend** : T-030 coquille unique (niv. 4), T-031 fil d'Ariane (niv. 5), T-032 tokens (niv. 6).
- **Architecture** : T-036 contrats import-linter (niv. 5), T-035a à T-035e découpe `zylo_liquid` (niv. 5 à 9), T-017 documentation backend (niv. 2).
- **Sécurité** : T-037a cookies, backend (niv. 5).
- **CI** : T-038b CI complète, tâche indépendante de la chaîne IAM (dépend de T-038a et T-036 : fichiers de workflow et contrats).

### Vague 3 : parcours complet et fermeture (13 tâches)
- **Parcours métier** : T-022 affectation par module, API (niv. 8), T-048 cycle de vie utilisateur (niv. 9), T-049 activation par lien à usage unique (niv. 8), T-024 front création d'utilisateurs (niv. 8), T-025 front affectation (niv. 9), T-047 accès interdit et inter-organisations (niv. 9), T-026 E2E du parcours socle (niv. 10, dernier de la chaîne IAM).
- **Frontend** : T-033a composants partagés (niv. 7), T-033b réseau et états d'erreur (niv. 8), T-033c accessibilité (niv. 9), T-037b cookies, frontend et en-têtes de sécurité (niv. 9).
- **Documentation et agents** : T-039 documentation frontend (niv. 7), T-040 agents et CLAUDE.md court (niv. 8).

## 4. Graphe de dépendances et chemin critique

Le graphe complet est dans chaque fiche (ligne « Dépendances ») et dans `REGISTRE_TACHES.md`. Les chaînes principales :

```
T-004 ──┬─> T-001, T-004b, T-016, T-041 ──┬─> T-042 ──> T-043 (catalogue, sans dépendance)
T-010 ──> T-019 ──> T-018 (+ T-007, T-036) ──> T-021 (+ T-013) ──> T-022 ──┬─> T-025 (+ T-024) ──> T-026
                                                                           └─> T-047 (+ T-046)
T-012 ──> T-013 ──> T-021 ;  T-030 ──> T-031 ──> T-032 ──> T-033a ──> T-033b ──> T-033c
T-002 ──> T-027 ──> T-035a ──> T-035b ──> T-035c ──> T-035d ──> T-035e  (+ T-034, T-028 ──> T-029)
T-038a ──> T-038b (+ T-036) ─ CI : hors de toute chaîne bloquante
```

**Chemin critique** : les chaînes les plus longues font 7 tâches (niveaux 0 à 6) : T-002 → T-027 → T-035a → … → T-035e (découpe `zylo_liquid`), et la chaîne IAM T-010 → T-019 → T-018 → T-021 → T-022 → T-025 → T-026. La chaîne IAM est détaillée dans `IAM_PAR_MODULE.md`. La durée n'est pas estimée en jours : aucune donnée de capacité n'existe. La chaîne frontend T-030 → T-031 → T-032 → T-033a est parallèle à la chaîne IAM.

## 5. Fichiers chauds (ordre de fusion)

Une tâche ne démarre pas sur un fichier chaud tant que la tâche qui précède dans cette liste n'est pas fusionnée.

| Fichier | Tâches qui le touchent, dans l'ordre |
|---|---|
| `.gitignore` | T-004 (lot 0) → T-001 → T-041 |
| `Dockerfile` | T-002 → T-028 → T-015 → T-051 |
| `app/core/config.py` | T-002 → T-003 → T-012 → T-015 → T-027 → T-037a |
| `tests/conftest.py` | T-005 → T-002 (coordonnés) → T-015 |
| `app/main.py` | T-028 → T-029 → T-015 → T-051 |
| `app/rbac/service.py` | T-010 → T-019 → T-018 → T-022 → T-036 (ce dernier retire les dépendances FastAPI) |
| `app/rbac/dependencies.py` | T-010 (crée) → T-036 |
| `app/rbac/router.py` | T-010 → T-018 → T-022 → T-048 |
| `app/identity/service.py`, `router.py` | T-010 → T-013 → T-019 → T-021 → T-048 |
| `app/auth/service.py`, `router.py` | T-012 → T-013 → T-020 → T-037a → T-049 |
| `app/modules/zylo_liquid/service.py` | T-013 (personnel uniquement) → T-034 → T-027 → T-029 → T-035a → T-035b → T-035c → T-035d → T-035e |
| `app/modules/zylo_liquid/roles_seed.py` | T-007 → T-018 |
| `app/modules_registry/service.py` | T-010 → T-036 → T-018 → T-022 |
| `alembic/versions/` | une tâche avec migration par vague à la fois (§2), `alembic heads` = 1 avant chaque fusion |
| `playwright.config.ts` | T-003 → T-041 → T-008 → T-009 → T-047 → T-026 |
| `e2e/global-setup.ts` | T-005 → T-008 → T-046 → T-026 |
| `package.json`, `package-lock.json` | T-004 (lot minimal) → T-041 → T-042 → T-011 → T-038a → T-038b |
| `eslint.config.mjs` | T-041 → T-038b |
| `.github/workflows/` (backend et frontend) | T-038a → T-038b |
| `src/core/api/client.ts` | T-003 → T-033b → T-037b |
| `src/core/auth/*` | T-013 → T-037b |
| `src/core/rbac/PermissionContext.tsx` | T-024 → T-025 |
| `src/app/(app)/users/page.tsx` | T-011 → T-030 → T-024 → T-031 |
| coquilles `src/modules/*/components/*Shell.tsx` | T-030 → T-031 → T-032 → T-033a |
| `src/app/globals.css` | T-032 seul |
| `src/shared/ui/PageHeader.tsx` | T-031 → T-033a |
| `TrucksMap.tsx` | T-032 → T-033a (déplacé dans `shared`) |

## 6. Risques transverses

- **Base de référence (T-004)** : 54 fichiers modifiés côté backend et 229 côté frontend, non commités. Aucune tâche ne démarre avant le tag `base-T004`. Pas d'exception.
- **IDOR (T-010)** : une correction trop stricte casse le frontend (l'en-tête est envoyé partout). Tests cross-tenant sur toutes les routes d'organisation, parcours prod vérifié.
- **Droits existants (T-007, T-018, T-021)** : toute modification de rôle par défaut élargit les organisations existantes. Pas de backfill au démarrage (T-028) ; migrations explicites, idempotentes, avec rapport.
- **Migrations** : additives et réversibles quand c'est possible. La migration `7ffb9473d45e` contient un `TRUNCATE` historique : elle n'est pas réécrite, elle est documentée comme non rejouable sur une base avec données (T-028).
- **Clé Holykell (T-027)** : si la clé est perdue, les comptes Holykell sont inutilisables. Sauvegarde et test de restauration obligatoires ; suppression de l'ancienne colonne non planifiée.
- **Refactor coquille (T-030)** : une coquille cassée bloque tout le produit. Captures de référence avant migration ; migration progressive, une coquille après l'autre.
- **Découpe `service.py` (T-034, T-035a à e)** : filet de caractérisation avant tout déplacement ; façade de réexport pendant la transition ; helpers partagés dans `common.py`.
- **Cookies (T-037a, T-037b)** : bascule seulement après l'acceptation de la date de fin de l'en-tête ; décision d'infrastructure du client requise.

## 7. Décisions à trancher (`docs/questions/`)

Colonne « Validation client » : **oui** si la réponse change des droits ou des données existantes (fusion bloquée tant que la réponse n'est pas écrite) ; **non** si la décision est technique et réversible.

| Fichier | Tâches | Validation client | État |
|---|---|---|---|
| `securite/purge-historique-dump.md` | T-001 | oui (commanditaire) | En attente de réponse |
| `securite/rotation-credentials.md` | T-001, T-015, T-027, T-008 | oui (propriétaires et dates) | En attente de réponse |
| `process/visibilite-depot-requirements.md` | T-016, T-001 | non | En attente de réponse |
| `architecture/environnement-par-defaut.md` | T-002 | non | Appliquée (coordinateur, à confirmer) |
| `architecture/ports-canoniques.md` | T-003, T-008, T-038a | non | Appliquée (coordinateur, à confirmer) |
| `securite/limitation-authentification.md` | T-012 | non | En attente (avance sur la recommandation) |
| `securite/politique-mot-de-passe.md` | T-013 | oui (politique) | En attente de réponse |
| `securite/types-fichiers-autorises.md` | T-014 | oui (types métier) | En attente de réponse |
| `securite/chiffrement-cle-holykell.md` | T-027 | oui (clé, sauvegarde, suppression) | En attente de réponse |
| `securite/catalogues-publics.md` | T-023 | oui (offre) | En attente de réponse |
| `securite/stockage-jetons.md` | T-037a, T-037b | oui (infrastructure) | En attente de réponse |
| `architecture/migrations-au-demarrage.md` | T-028, T-051 | non | Appliquée (coordinateur, à confirmer) |
| `architecture/sauvegarde-avant-migration.md` | T-028, T-018, T-027, T-037a | oui (exploitation) | En attente de réponse |
| `architecture/contrats-importlinter.md` | T-036, T-038b | non | Appliquée (coordinateur, à confirmer) |
| `rbac/roles-multi-modules.md` | T-018 | oui (droits) | En attente, validation avant fusion |
| `rbac/manager-role-superset.md` | T-007 | oui (droits) | En attente, validation avant fusion |
| `rbac/creation-organisation.md` | T-019 | oui (quota) | En attente de réponse |
| `rbac/code-http-acces-interdit.md` | T-010, T-047 | non | Appliquée (sur recommandation, à valider) |
| `rbac/activation-compte.md` | T-021, T-049 | oui (canal d'envoi, droits) | En attente, validation avant fusion |
| `rbac/cycle-de-vie-utilisateur.md` | T-048 | oui (conservation des données) | En attente, validation avant fusion |
| `rbac/permission-plateforme.md` | T-050 | oui (administration) | En attente de réponse |
| `zylo-liquid/ordre-validation-fournisseur.md` | T-006 | oui (ordre métier) | En attente de réponse |
| `tests/couche-tests-unitaires.md` | T-042 | non | Appliquée (coordinateur, à confirmer) |
| `tests/environnement-recette.md` | T-038a, T-010, T-026 | oui (hébergement) | En attente de réponse |
| `tests/holykell-simulateur.md` | T-009 | oui (environnement) | En attente de réponse |
| `tests/retention-traces-video.md` | T-008 | non | En attente de réponse |
| `frontend/palette-de-reference.md` | T-032 | oui (design) | En attente, validation avant fusion |
| `frontend/bibliotheque-graphiques.md` | T-033a, T-033b | oui (design) | En attente de réponse |

**Question posée avant T-001** : `securite/purge-historique-dump.md` est créée par T-001 elle-même et existe dans le dépôt (vérifié par `check_plan`). Elle doit être tranchée par écrit par le commanditaire avant que T-001 soit clôturée, pas avant sa fusion.

## 8. Gabarit d'agent

Chaque agent d'exécution reçoit ce gabarit, rempli pour une tâche :

```
Tâche : T-XXX (fiche : docs/plans/taches/T-XXX-<slug>.md)
Dépôt : <back|front> · Branche : <type>/T-XXX-<slug> · Worktree : worktrees/T-XXX-<back|front>
Base de départ : tag base-T004 (ou commit fusionné indiqué dans la fiche)
Base de test : zylo_tNNN[lettre]_test · Ports : back 31NN, front dev 32NN, front prod 33NN (table docs/process/ports.md)
Lis la fiche en entier. Ne touche que les fichiers listés, sauf nécessité documentée dans la PR.
Tests : ceux de la fiche. Playwright seulement sur build de production, avec la configuration versionnée.
Décision non évidente : docs/questions/<cat>/<sujet>.md. Si la décision change des droits : ne pas avancer, arrêter et signaler.
Ne fusionne pas. Ne migre pas la production. Ne réécris pas l'historique.
Sortie : statut, fichiers modifiés, résultats de tests (commande et compte), questions ouvertes (10 lignes max).
```

## 9. Points d'incertitude

- **Faille IDOR** : déduite du code (`get_current_organization_id` renvoie l'en-tête sans contrôle, vérifié), pas encore reproduite par un test. T-010 commence par ce test.
- **Visibilité du dépôt** : non contrôlée par l'agent (pas d'accès réseau). Elle conditionne T-001 et T-016.
- **CVE** : `pip-audit` n'a pas été exécuté. T-015 le fait et joint la sortie.
- **Ports et Docker** : le conteneur n'a pas été lancé ; le démarrage sans migration et l'utilisateur non root sont à valider sur une image de test (T-028, T-051).
- **Playwright P7** : dépend d'un environnement externe non décrit (question `tests/holykell-simulateur.md`).
- **Chiffres de la baseline** : 22 pytest et 10 Playwright en échec, repris de `baseline-tests.md`, non rejoués pour ce plan. Le chiffre « 223 tests Vitest » n'est plus valable après T-041 ; `baseline-tests.md` est mis à jour par T-041.
- **Durées** : aucune estimation en jours. La taille (S, M, L) est indicative.

## 10. Contrôle du plan

Un script de contrôle lit les fiches (source de vérité) et vérifie :
- chaque dépendance existe ; le niveau d'une tâche est strictement supérieur à celui de ses dépendances ; aucune vague ne décroît le long d'une dépendance ; aucun cycle ;
- les ports suivent la formule de §2 ; aucun port réservé n'est utilisé ; aucune base n'est en dehors de la règle de nommage ;
- chaque question citée existe dans `docs/questions/` ;
- le registre et les issues sont régénérés depuis les fiches.

**Dernière exécution** : 58 tâches, 0 erreur. Le script est actuellement dans le répertoire de travail de l'agent, hors dépôt : T-016 le versionne dans `scripts/docs/check_plan.py` et le branche en CI (T-038a).
