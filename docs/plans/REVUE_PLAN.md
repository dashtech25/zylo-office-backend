# Décisions sur la revue du plan de remise sur pied

- **Date** : 2026-10-08
- **Objet** : une décision par constat des trois revues (`revues/revue-architecture.md`, `revue-securite-tests.md`, `revue-design-playwright.md`) : 21 constats REV-A, 25 constats REV-S, 30 constats REV-D, soit 76.
- **Légende** : **Accepté** = la correction proposée est retenue telle quelle. **Accepté modifié** = le constat est retenu, la correction diffère (raison donnée). **Rejeté (justifié)** = le constat est faux ; aucun rejet n'a été nécessaire.
- **Bilan** : 63 acceptés, 13 acceptés modifiés, 0 rejeté (76 constats). Aucune revue n'a été contredite par les faits vérifiés ; les points où la revue était imprécise (unités de comptage, portée d'un contrôle) sont traités comme « accepté modifié ».

## Vérifications effectuées pour trancher

Contrôles en lecture seule, sur les dépôts, avant décision :

- Dump : présent dans l'historique (commit `8aea496`), suivi par git (REV-S-01).
- `config.py` : `ENVIRONMENT` par défaut `development` (ligne 8) ; `JWT_SECRET` et `STORAGE_SIGNED_URL_SECRET` par défaut contiennent `changeme` ; `Dockerfile` sans `ENV ENVIRONMENT` (REV-S-02, S-03).
- `get_current_organization_id` renvoie l'en-tête sans contrôle d'appartenance (`app/rbac/service.py`, lignes 15 à 23) (REV-S-04).
- `main.py` appelle trois backfills à chaque démarrage, dont `backfill_default_role_permissions` qui ajoute des permissions aux rôles existants (lignes 91 à 109) (REV-S-05, S-06).
- `zylo_liquid/service.py` : 15 681 lignes et 504 fonctions (REV-A-15).
- Migrations : 57 fichiers contiennent `drop_column`, `drop_table` ou `TRUNCATE` ; une seule tête (`f1a3b5c7d849`) (REV-S-12, A-14).
- Branche `chore/retirer-storybook` (commit `64c97e1`) supprime `vitest.config.ts` ; elle est dans un worktree sous `office/worktrees/` (REV-A-04, D-01, A-20).
- Frontend : `globals.css` contient une référence circulaire à la ligne 101 ; `#3498db` à la ligne 15 ; `next.config.ts` sans `headers()` ; pas de `.github/` ; `dev` et `start` sur 3001 ; `playwright.config.ts` sur 3055 (REV-D-08, D-09, D-26, S-19, D-27).
- E2E : 2 fichiers suivis, 25 non suivis ; `e2e/.auth/` présent ; tag `@external` absent ; `video: "on"` (REV-D-17, D-07, D-22, S-17).
- Comptages : hex dans `.tsx` hors stories : 58 occurrences dans 9 fichiers (l'audit annonce 47) ; 44 imports nommés de `Table` depuis `@/shared/ui` (l'audit annonce 54) ; 53 `page.tsx` ; 30 fichiers hors `shared/ui` contenant `<table` (REV-D-13, D-14, D-15).

Non vérifié (hors de portée de l'agent) : visibilité réelle du dépôt GitHub, exécution de pytest et de Playwright, contenu des fichiers de jetons et de données de test (volontairement non lus).

## Décisions par constat

### Revue architecture (REV-A)

| ID | Sévérité | Décision | Justification | Où c'est corrigé |
|---|---|---|---|---|
| REV-A-01 | Critique | Accepté | Profondeur recalculée : 28 tâches sur 40 ont une vague inférieure à leur profondeur (conforme au constat). Vague et niveau sont séparés ; le contrôle refuse une dépendance de même niveau ou de vague supérieure. | PLAN §2–§4 ; `REGISTRE_TACHES.md` (niveau calculé) ; contrôle `check_plan` (T-016) |
| REV-A-02 | Critique | Accepté modifié | Le coordinateur place T-004 en premier : T-001, T-002, T-003, T-005 en dépendent. La tâche est divisée en T-004 (base minimale, tag `base-T004`) et T-004b (tri restant, non bloquant). | T-004, T-004b ; PLAN §2 et §6 ; T-001 à T-005 (dépendance T-004) |
| REV-A-03 | Critique | Accepté | Décision du coordinateur : `Role.moduleCode` nullable, quatre conditions, un seul mécanisme, backfill explicite. Pas de portée module sur `userRole`. | T-018 (réécrite), T-022 ; question `rbac/roles-multi-modules.md` |
| REV-A-04 | Critique | Accepté | Storybook retiré et fusionné (T-041) ; Vitest minimal (T-042) ; catalogue (T-043) ; critères réécrits partout. Branche vérifiée (`64c97e1`). | T-041, T-042, T-043 ; T-011, T-024, T-025, T-030, T-031, T-032, T-033a à c, T-038a/b, T-039 |
| REV-A-05 | Élevée | Accepté | T-004 découpée : base minimale (critère : tag posé, arbre propre) et T-004b (lots restants, durée indicative à confirmer). | T-004, T-004b |
| REV-A-06 | Élevée | Accepté | Cycle de vie absent : création de T-048 (désactivation, retrait d'appartenance, retrait d'affectation) ; dépend de T-020. | T-048 ; question `rbac/cycle-de-vie-utilisateur.md` |
| REV-A-07 | Élevée | Accepté | Le créateur ne connaît plus le secret : compte `pending` sans mot de passe (T-021), activation par lien à usage unique (T-049). | T-021, T-049 ; question `rbac/activation-compte.md` |
| REV-A-08 | Élevée | Accepté modifié | Option (a) retenue : plus de création de plan par API (T-019). La permission plateforme est rendue explicite par une tâche dédiée, créée seulement si la décision l'exige (coordinateur). | T-019, T-050 ; question `rbac/permission-plateforme.md` |
| REV-A-09 | Élevée | Accepté modifié | Scission retenue, mais le premier volet (T-038a) démarre en vague 1 avec un mode « régression » : échec sur tout test hors liste datée (`known_failures.txt`), pas une suite complète verte. Le second volet (T-038b) ajoute lint, contrats et Playwright. | T-038a, T-038b ; T-010 dépend de T-038a |
| REV-A-10 | Élevée | Accepté | Colonne « validation client » ajoutée. Les tâches qui changent des droits existants attendent la validation avant fusion : T-007, T-018, T-021, T-049. | PLAN §7 ; fiches (statut « en attente de validation client ») ; questions correspondantes |
| REV-A-11 | Élevée | Accepté | Ordre écrit des fichiers chauds ; T-036 avant T-018 ; T-010 écrit `dependencies.py` ; T-051 (démo) après T-010. | PLAN §5 ; T-010, T-018, T-036, T-051 |
| REV-A-12 | Moyenne | Accepté | `NULLS NOT DISTINCT` retenu (la CI déclare PostgreSQL 16 : `ci.yml.disabled`) ; détection des doublons avant migration. | T-018 |
| REV-A-13 | Moyenne | Accepté | Registre et issues générés depuis les fiches ; cycle T-007/T-018 supprimé (T-007 ne dépend plus de T-018) ; dépendances des fiches alignées. | `REGISTRE_TACHES.md`, `ISSUES_A_CREER.md` ; T-007, T-018, T-020, T-024, T-025, T-026 ; T-016 |
| REV-A-14 | Moyenne | Accepté | Table des fichiers chauds complétée ; règle : une tâche avec migration par vague ou `alembic heads` = 1 avant fusion. | PLAN §5 |
| REV-A-15 | Moyenne | Accepté | T-035 découpée en a à e, en chaîne ; T-034 ne dépend plus de T-036 ; emplacement des helpers partagés (`common.py`) décidé dans T-034. | T-034, T-035a à T-035e |
| REV-A-16 | Moyenne | Accepté | `forbidden` par paire pour l'acyclicité (pas `acyclic_siblings`) ; ARC-005 et ARC-006 ajoutés ; `shared/permissions.py` marqué « étendu » ; priorité P1. | T-036 ; question `architecture/contrats-importlinter.md` |
| REV-A-17 | Moyenne | Accepté | Scissions : T-015 (T-051 pour le conteneur), T-033 (a, b, c), T-037 (a, b), T-038 (a, b). | Fiches correspondantes |
| REV-A-18 | Moyenne | Accepté | Quota : question à valeur fixée par le client. Clé Holykell : procédure de sauvegarde et test de restauration. Rotation : propriétaire et date attestés. Sauvegarde : runbook. | T-019, T-027, T-028 ; questions `rbac/creation-organisation.md`, `architecture/sauvegarde-avant-migration.md`, `securite/rotation-credentials.md` |
| REV-A-19 | Faible | Accepté modifié | Tailles S, M, L ajoutées à chaque fiche. Pas de jours estimés : aucune donnée de capacité ; chemin critique donné en nombre de tâches (11). Durée indicative seulement pour T-004b. | Fiches (ligne Taille) ; PLAN §4 |
| REV-A-20 | Faible | Accepté | Dossier retenu : `office/worktrees/` (existant). Table de ports unique : checkout principal 3002/3001/3055, worktrees 3100+n, 3200+n, 3300+n. | T-003, T-004 ; PLAN §2 |
| REV-A-21 | Faible | Accepté | ARC-005 garde la priorité P1 (T-036). DOC-017 couvert par T-041. Issues générées depuis le registre. | T-036, T-041 ; `ISSUES_A_CREER.md` |

### Revue sécurité, tests et données (REV-S)

| ID | Sévérité | Décision | Justification | Où c'est corrigé |
|---|---|---|---|---|
| REV-S-01 | Critique | Accepté | Critères de T-001 : visibilité consignée, liste des identifiants avec propriétaire et date, décision de réécriture écrite par le commanditaire. Clôture seulement après rotation attestée. | T-001 ; `securite/purge-historique-dump.md`, `securite/rotation-credentials.md` ; PLAN §7 (question créée par T-001) |
| REV-S-02 | Critique | Accepté | `ENVIRONMENT` par défaut `production` ; `ENV` dans le `Dockerfile` ; test « variable absente + secret de repli = refus » ; clé de chiffrement déclarée dans T-002. Constat vérifié (ligne 8 de `config.py`). | T-002 ; `architecture/environnement-par-defaut.md` |
| REV-S-03 | Haute | Accepté | Recensement des littéraux (`git grep`) et remplacement par variables d'environnement dans T-015 ; secrets GitHub dans T-038a. Présence vérifiée dans `conftest.py`. | T-015, T-038a |
| REV-S-04 | Haute | Accepté | Validation d'appartenance dans `get_current_organization_id` (toutes les routes, y compris sans chemin) ; T-008 ajouté aux dépendances. Absence de contrôle vérifiée. | T-010 |
| REV-S-05 | Haute | Accepté | T-007 bloquée sur la décision client ; pas d'élargissement sans accord écrit ; backfills de démarrage retirés (T-028) ; test « aucun rôle ne gagne de permission au démarrage ». Backfill vérifié dans `main.py`. | T-007, T-028 ; `rbac/manager-role-superset.md` |
| REV-S-06 | Haute | Accepté | Compte `pending` sans secret connu du créateur ; test « le créateur ne peut pas ouvrir de session » ; activation par jeton à usage unique et expiration. | T-021, T-049 ; `rbac/activation-compte.md` |
| REV-S-07 | Haute | Accepté | Règle par couple (IP, compte) et limite globale par IP ; verrou par compte limité, non bloquant pour une IP connue ; deux tests dédiés. | T-012 ; `securite/limitation-authentification.md` |
| REV-S-08 | Haute | Accepté modifié | Pas d'envoi annoncé : message neutre sans promesse d'e-mail. Le 409 du personnel (flux authentifié) reste explicite, choix consigné. L'envoi d'e-mail est traité par T-049, qui dépend d'une décision client ; l'activation immédiate reste un risque accepté tant qu'il n'existe pas. | T-013, T-049 |
| REV-S-09 | Haute | Accepté modifié | Suppression de la colonne en clair : non planifiée, subordonnée à un accord écrit, une période d'observation et une sauvegarde vérifiée (plan §6 : pas de suppression sans accord). Clé et test de restauration dans T-027 et T-002. | T-027, T-002 ; `securite/chiffrement-cle-holykell.md` |
| REV-S-10 | Moyenne | Accepté | Liste unique (PDF, PNG, JPEG, WebP) ; lecture bornée à `MAX+1` ; fichiers existants servis en `attachment` ; photo de profil (IAM-019) couverte. | T-014 ; `securite/types-fichiers-autorises.md` |
| REV-S-11 | Moyenne | Accepté | Critère : sortie `pip-audit` jointe à `surface-api.md` ; tests de connexion, refresh et rejet de jeton avant et après ; référence corrigée vers T-014 (ligne 18 de `requirements.txt` vérifiée). | T-015 |
| REV-S-12 | Moyenne | Accepté modifié | Runbook de sauvegarde, de déploiement et de retour arrière ; test de `downgrade` sur base jetable. Migrations déjà appliquées non réécrites (plan §2 et T-028) : le `TRUNCATE` reste, documenté « à ne jamais rejouer sur une base contenant des données ». | T-028 ; `architecture/sauvegarde-avant-migration.md` |
| REV-S-13 | Moyenne | Accepté | Backfill réel rattachant les rôles par défaut (liste explicite testée) ; rapport des rôles personnalisés ; downgrade déclaré non restaurant. | T-018 |
| REV-S-14 | Haute | Accepté | Retrait de `/taches/` (ancrage) et hook pré-commit refusant dumps et `.env` dès T-004 ; `docs/plans` et `docs/audit` suivis (aucun fichier suivi dans `docs/audit`, vérifié). | T-004 (lot 0) |
| REV-S-15 | Haute | Accepté | Pas de valeur par défaut pour `TEST_DATABASE_URL` ; nom `zylo_t<NNN>[a-z]?_test`, hôte et port autorisés ; garde commune pytest et Playwright ; test « `zylo_office` refusé même sur un autre port ». | T-005 |
| REV-S-16 | Haute | Accepté | Table unique (T-003) ; `CORS_ORIGINS` configurable ; critère de préflight depuis le port de la tâche (T-005, T-008). `CORS_ORIGINS` ne liste que 3001 et 3055 (vérifié). | T-003, T-005, T-008 |
| REV-S-17 | Moyenne | Accepté | Critère « 26 passent, 1 exclu par `@external` » ; contrôle scripté d'absence de suppression d'assertion ; rétention des vidéos (question). | T-009 ; `tests/retention-traces-video.md` |
| REV-S-18 | Moyenne | Accepté | « Prod » remplacé par « build de production local » ; environnement de recette en question ; T-038a/b précisent services PostgreSQL, base par job, seed, démarrage du backend. | T-010, T-038a, T-038b ; `tests/environnement-recette.md` |
| REV-S-19 | Moyenne | Accepté modifié | Les en-têtes (CSP, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`) sont rattachés à T-037b, car ils accompagnent le passage aux cookies, plutôt qu'à une tâche séparée. Test sur la réponse de production. | T-037b |
| REV-S-20 | Moyenne | Accepté modifié | Date de fin de l'en-tête (`AUTH_HEADER_ACCEPTED_UNTIL`), CSRF testé sur `/auth/refresh` et `/auth/logout`. Le comportement de `Secure` en local varie selon les navigateurs (constat exact : « certains », pas « ne fonctionne pas »), traité en question. | T-037a, T-037b ; `securite/stockage-jetons.md` |
| REV-S-21 | Moyenne | Accepté | Test de fuite de journaux sur les parcours de connexion, de création et d'appel Holykell. | T-029 |
| REV-S-22 | Moyenne | Accepté | Graphe généré depuis les fiches ; cycle T-007/T-018 résolu (décision avant T-018) ; ordre des fichiers chauds complété ; T-027 après T-034 sur `zylo_liquid/service.py` (fichier chaud, PLAN §5). | T-007, T-018 ; `REGISTRE_TACHES.md` ; PLAN §5 |
| REV-S-23 | Basse | Accepté | Critères mesurables : T-006 avec cas « API modifiée » ; T-023 sans « aucun changement » (changement listé) ; T-029 liste des exceptions dans la PR ; T-035e critère numérique et reliquat justifié. | T-006, T-023, T-029, T-035e |
| REV-S-24 | Basse | Accepté | Section « Retour arrière » et validation client avant fusion pour T-018, T-021, T-027, T-037a et T-037b. | T-018, T-021, T-027, T-037a, T-037b |
| REV-S-25 | Basse | Accepté modifié | Non prouvé par la revue : transformé en contrôle (`git grep` et variables d'environnement) plutôt qu'en constat. | T-009 |

### Revue design et Playwright (REV-D)

| ID | Sévérité | Décision | Justification | Où c'est corrigé |
|---|---|---|---|---|
| REV-D-01 | Critique | Accepté | Retrait Storybook vérifié (`64c97e1`) ; critères Storybook remplacés dans toutes les fiches listées. | T-041 et fiches citées par REV-D-01 |
| REV-D-02 | Majeure | Accepté modifié | Catalogue créé, mais en un fichier par composant exporté (et un index), contrôlé par script, plutôt qu'un seul document. | T-043 ; T-033a à c ; T-039 |
| REV-D-03 | Majeure | Accepté | Vitest minimal sur la logique pure, décision consignée (appliquée). | T-042 ; `tests/couche-tests-unitaires.md` |
| REV-D-04 | Majeure | Accepté | Retrait traité par T-041 ; merge de `base-T004` (sans réécriture) ; fichiers chauds ajoutés au plan §5. | T-041 ; PLAN §5 |
| REV-D-05 | Majeure | Accepté | Artefacts locaux déplacés hors dépôt avant tri (sauvegarde, pas suppression) ; règles d'ignore de Storybook conservées (constat vérifié : absentes de la branche). | T-004, T-041 |
| REV-D-06 | Mineure | Accepté | 28 questions créées avec le gabarit de `questions/README.md`. | `docs/questions/**` |
| REV-D-07 | Critique | Accepté | `e2e/.auth/` et `e2e/fixtures/` ignorés dès T-004 ; fichier retiré du disque ; jetons à révoquer ; test `git check-ignore`. | T-004, T-008 ; `securite/rotation-credentials.md` |
| REV-D-08 | Majeure | Accepté | Suppression des redéclarations circulaires (ligne 101 de `globals.css`, vérifiée) ; contrôle `grep` après build. | T-032 |
| REV-D-09 | Majeure | Accepté | Thème clair seul, critère « variante sombre » retiré ; palette soumise à décision (question créée). | T-032 ; `frontend/palette-de-reference.md` |
| REV-D-10 | Majeure | Accepté | `breadcrumbLabel` obligatoire, `data-testid="breadcrumb"`, critère Playwright. | T-031 |
| REV-D-11 | Majeure | Accepté | Navigation de module identifiée par `data-testid="module-nav"` ; fil d'Ariane compté séparément. | T-030 |
| REV-D-12 | Majeure | Accepté | Ordre T-030 → T-031 → T-032 → T-033a → T-033b → T-033c dans le plan, le registre et les fiches. | PLAN §3 et §5 ; fiches |
| REV-D-13 | Majeure | Accepté | Liste d'exemptions datée et contrôle `grep` ; comptage reproductible (44 imports nommés, méthode indiquée). | T-033a |
| REV-D-14 | Majeure | Accepté | Liste des 53 pages et forme de la ligne (`export { default } from`) ; exceptions listées. | T-031 |
| REV-D-15 | Mineure | Accepté modifié | Constat exact sur la reproductibilité, mais la correction donnée est l'unité : 58 occurrences dans 9 fichiers `.tsx` (hors stories), et non « 47 » ou « 9 fichiers » comparés entre eux. Chiffres remplacés par des commandes. | T-033b ; T-039 (état de l'audit) |
| REV-D-16 | Majeure | Accepté | Signature `can(code, module?)`, table module × permission, tanker avec providers (`ProtectedRoute` seul vérifié dans le layout). | T-025, T-030 |
| REV-D-17 | Majeure | Accepté | Versionnement des 25 fichiers `e2e/` dès T-004 ; critère `git ls-files e2e` dans T-008. | T-004, T-008 |
| REV-D-18 | Majeure | Accepté | Données par test et par spec (fabrique, suffixes `runId`), plus de compteur global (`pumpBase`, constaté). Exécution sur base `zylo_t<NNN>_test`. | T-046, T-008, T-026 |
| REV-D-19 | Majeure | Accepté | Tests d'accès interdit et inter-organisations en API et navigateur ; matrice figée (T-023). | T-047 ; T-026 (refus visible) ; `rbac/code-http-acces-interdit.md` |
| REV-D-20 | Majeure | Accepté | Registre et fiches alignés (généré) ; T-008 ajouté aux dépendances de T-024. | T-024, T-025, T-026 |
| REV-D-21 | Majeure | Accepté | Configuration de production versionnée ; critère « passe sur base vierge, sans seed manuel » ; cible 17/27 retirée. | T-008 |
| REV-D-22 | Majeure | Accepté | Tag `@external` défini et exclu en CI ; « 26 passent, 1 exclu » ; question sur l'environnement de P7 (tag absent, vérifié). | T-009 ; `tests/holykell-simulateur.md` |
| REV-D-23 | Mineure | Accepté | Critère ajouté : aucun `setTimeout` de test au-delà de 60 s sans justification écrite (18 occurrences comptées). | T-046 |
| REV-D-24 | Mineure | Accepté | Règle de hiérarchie des sélecteurs ; helper pour `SearchableSelect` et `<select>` ; `option:checked` vérifiée contre le composant. Comptages vérifiés (13 et 3). | T-009 |
| REV-D-25 | Mineure | Accepté | Convention `*.mock.spec.ts` / `*.real.spec.ts` ; parcours métier en `real` ; écrite dans `docs/process/tests.md`. | T-046 ; T-026 |
| REV-D-26 | Majeure | Accepté | Table de ports unique et question `ports-canoniques.md` avant T-003 ; ports des fiches recalculés par formule et contrôlés. | T-003 ; `architecture/ports-canoniques.md` |
| REV-D-27 | Majeure | Accepté | Workflow frontend dans `.github/workflows/frontend.yml` (le dépôt n'a pas de `.github/`, vérifié) ; backend dans son propre workflow ; versions fixées. | T-038a, T-038b |
| REV-D-28 | Mineure | Accepté modifié | Hypothèses non sourcées marquées dans les fiches (T-033c pour CSRF et règle `fetch`). Règle générale ajoutée au plan §2 : toute hypothèse est transformée en contrôle, pas en affirmation. | PLAN §2 ; T-033c |
| REV-D-29 | Mineure | Accepté | Section « état à la date de la branche de référence » dans l'audit frontend ; chiffres mis à jour. | T-039 ; T-041 |
| REV-D-30 | Mineure | Accepté | Captures de référence Playwright (`toHaveScreenshot`) avant la migration de la coquille. | T-030, T-032 |
