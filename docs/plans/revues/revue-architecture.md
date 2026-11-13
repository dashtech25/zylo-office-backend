# Revue critique indépendante : architecture et plan de remise sur pied

- **Date** : 2026-10-08
- **Objet** : `docs/plans/PLAN_REMISE_SUR_PIED.md`, `REGISTRE_TACHES.md`, `taches/T-001` à `T-040`, confrontés aux audits `docs/audit/` (backend et frontend) et au code (lecture seule).
- **Méthode** : lecture de l'intégralité du plan, du registre et des fiches ; recalcul des profondeurs de dépendances à partir du registre (script hors dépôt, aucun fichier du projet modifié) ; couverture des identifiants d'audit (71 identifiants, tous couverts sauf DOC-017 et ARC-021, tous deux P3) ; vérifications dans le code et l'historique git (`chore/retirer-storybook`, `.importlinter`, migrations Alembic, `roles_seed.py`, `modules_registry/service.py`, `identity/service.py`).
- **Limites** : aucun test lancé, aucune base interrogée. Les hypothèses sur les données de production (doublons `userRole`, rôles personnalisés) restent à vérifier par requête en lecture seule.

## Synthèse

Le plan est bien construit sur le fond (IDOR en tête, puis socle IAM, puis découpe). Il n'est pas exécutable en l'état pour trois raisons :

1. Les vagues ne sont pas celles que le plan définit : 28 tâches sur 40 ont une dépendance de même vague ou d'une vague ultérieure (REV-A-01).
2. La règle « aucune tâche avant la base T-004 » est violée dès la vague 0 (REV-A-02).
3. Le retrait de Storybook supprime le seul outil de test unitaire du frontend. Une dizaine de critères d'acceptation ne peuvent plus être satisfaits (REV-A-04).

Sur le modèle IAM, `Role.moduleCode` nullable est suffisant pour le besoin « droits propres à chaque module », à quatre conditions. Le plan en omet trois, et sa migration de backfill ne change rien aux données existantes (REV-A-03).

**Verdict** : plan à corriger avant lancement. Corrections prioritaires : REV-A-01 à REV-A-04, puis REV-A-06 à REV-A-08.

---

## Constats

### REV-A-01 : vagues incohérentes avec la règle de profondeur (Critique)

- **Tâches** : registre (colonne Vague), `PLAN_REMISE_SUR_PIED.md` §3 et §4.
- **Preuve** : le plan définit les vagues comme « profondeur de dépendances ». En recalculant la profondeur depuis le registre, 28 tâches sur 40 ne correspondent pas à leur vague. Exemples :
  - T-010 (P0) est en vague 1 mais dépend de T-004 (vague 1). Profondeur 2.
  - T-021 est en vague 2 mais dépend de T-018 et T-019 (vague 2). Profondeur 4.
  - T-025 et T-026 sont en vague 3 mais dépendent de T-022, T-024 (vague 3). Profondeurs 6 et 7.
  - T-038 (CI) est en vague 2 mais dépend de T-036 (vague 2). Profondeur 4.
  - T-037 (cookies, P1) est en vague 3 mais dépend de T-033 (vague 3). Profondeur 6.
  - T-040 dépend de T-039 (vague 3) et est en vague 3. Profondeur 6.
  - Le plan annonce « environ 7 niveaux » de chemin critique. Le chemin réel est T-001 → T-004 → T-010 → T-019 → T-021 → T-022 → T-025 → T-026 (huit tâches). Le plan omet T-019 et T-025.
- **Correction** : deux options. (a) Garder quatre vagues comme jalons de revue humaine, et affecter chaque tâche à la vague ayant une profondeur ≤ sa vague, avec la règle « une tâche démarre dès ses dépendances fusionnées » comme seul critère de démarrage. (b) Abandonner le mot « vague » et utiliser « niveau » (0 à 7), généré par script à partir des fiches. Dans les deux cas, la colonne du registre doit être générée, pas saisie, et un contrôle (script déjà écrit pendant la revue) doit échouer si une dépendance est de même niveau ou de niveau supérieur.

### REV-A-02 : règle « base T-004 avant tout » violée (Critique)

- **Tâches** : T-001, T-002, T-003, T-005 (vague 0) ; T-004 ; plan §2 et §6.
- **Preuve** :
  - Plan §6 : « Toute tâche qui démarre avant T-004 partira d'une base instable. Pas d'exception. »
  - Plan §2 : les branches sont créées « depuis le tag `base-T004` ». Ce tag n'existe pas encore et ne peut pas exister avant T-004.
  - Le dépôt backend a 54 fichiers modifiés et le frontend 229 (T-004). T-001 propose un `git rm --cached` puis un commit sur cet arbre sale. T-002, T-003 et T-005 modifient `config.py`, `conftest.py`, `Dockerfile`, `CLAUDE.md`, qui font partie de ce travail en cours.
  - T-003 écrit « à faire avant le tri [T-004] » alors que T-004 n'a pas T-003 comme dépendance.
  - T-004 dit « Parallélisable avec : Rien. Tâche bloquante ». Le plan dit « 4 tâches en parallèle » en vague 0.
- **Correction** : choisir un seul modèle. Soit T-001 à T-005 passent après T-004 (coût : quelques jours de séquence). Soit T-004 est découpée : un commit de base minimal, sans le travail en cours, est posé d'abord sur `remy`, et le reste du tri devient une tâche parallèle. Dans les deux cas, corriger le plan §2, §6, la fiche T-003 et la fiche T-004 (dépendances).

### REV-A-03 : modèle IAM par module : suffisance, alternatives, migration (Critique)

- **Tâches** : T-018, T-021, T-022, T-025 ; `identite-permissions.md` (IAM-005) ; `bonnes-pratiques/securite-rbac-multitenant.md` §4.
- **Réponse à la question** : `Role.moduleCode` nullable suffit pour « un utilisateur a des droits différents selon le module », à condition de :
  1. Un seul mécanisme. La fiche T-018 propose à la fois `Role.moduleCode` (objectif, étape 1) et `userRole.resourceType = 'module'` avec `resourceId` = code du module (étape 4, reprise par T-022 « pas de nouvelle table »). Il faut en garder un seul. Le second est impossible tel quel : `UserRole.resourceId` est typé UUID (`app/rbac/models.py`) et le code de module est une chaîne. « À convertir » signifie un `ALTER COLUMN` sur une table peuplée, donc une migration non additive, contraire à la règle du plan §6 (« toutes additives et réversibles »).
  2. Une exception explicite pour les permissions transverses. Les rôles par défaut de zylo_liquid contiennent `CURRENCY_READ` et `GEO_READ`, qui ont le module `shared` (`app/modules/zylo_liquid/roles_seed.py:231-232`). Une règle stricte « permission.moduleCode = role.moduleCode » casse ces rôles. Il faut une liste fermée de permissions de socle partagées, ou un indicateur sur la permission.
  3. Le rôle propriétaire est une exception déclarée. `grant_module_permissions_to_owner` (`modules_registry/service.py`) donne à `owner` les permissions de chaque module activé. Le propriétaire est donc un rôle « transverse » qui contient des permissions de modules. La règle « transverse = socle seulement » de T-018 est fausse pour lui.
- **Migration** : le plan dit « backfill à NULL ». C'est une opération nulle : tous les rôles existants restent transverses et gardent le comportement actuel, donc l'objectif n'est atteint pour aucune organisation existante. Il faut un backfill réel :
  - rôles créés par `DEFAULT_ROLES` (`roles_seed.py`) : `moduleCode` déduit du code du rôle et de ses permissions, après contrôle ;
  - rôles personnalisés (créés par l'administrateur) : requête de rapport en lecture seule listant ceux qui mélangent plusieurs modules, à trancher avec le client ; pas de bascule silencieuse.
- **Contradiction de sources** : `securite-rbac-multitenant.md` §4 présente `Role.moduleCode` nullable comme « global (multi-module, existant) », c'est-à-dire que le transverse est multi-module. T-018 décide le contraire (« un rôle = un module ou aucun, transverse réservé au socle »). La décision doit être prise une fois, dans `docs/questions/rbac/roles-multi-modules.md`, en citant les deux positions.
- **Alternative** : `UserModuleAssignment(organizationId, userId, moduleCode FK module.code, roleId)`, unique sur (organizationId, userId, moduleCode, roleId). Elle évite la duplication des rôles par module et rend l'affectation lisible. Coût : deux sources de vérité dans `user_has_permission`, donc un refactor plus large de `app/rbac/service.py` (fichier chaud). Recommandation : garder `Role.moduleCode` (changement additif, réutilise le moteur) avec les quatre conditions ci-dessus. Documenter l'alternative dans la question.
- **Correction** : mettre à jour T-018 (un seul mécanisme, liste des permissions partagées, owner explicite, backfill réel avec rapport, test de contrainte à l'écriture dans `update_role_permissions` et `assign_role`) et retirer toute mention de `resourceType = 'module'` de T-022.

### REV-A-04 : Storybook retiré, stratégie de test du frontend effondrée (Critique)

- **Tâches** : T-004 (lot « storybook »), T-011, T-024, T-025, T-030, T-031, T-032, T-033, T-038, T-039 ; `baseline-tests.md` (223 tests Vitest) ; `ISSUES_A_CREER.md`.
- **Preuve** : la branche `chore/retirer-storybook` (commit `64c97e1`, base `remy` @ `14c1f07`, worktree `worktrees/frontend-retirer-storybook`) supprime `vitest.config.ts`, `vitest.shims.d.ts`, `@vitest/*`, `vitest`, `vite` et `playwright` (le seul consommé est `@playwright/test`). Sa note `docs/audit/retrait-storybook.md` indique : « plus aucun test unitaire dans le dépôt » et « les 223 tests Vitest disparaissent ».
- **Conséquences** :
  - Critères impossibles : T-011 (« vitest projet storybook vert, 223 tests »), T-033 (« vitest projet storybook vert »), T-024 et T-025 (« Vitest storybook : stories »), T-030 (« story du ModuleShell »), T-031 (« Storybook sur les écrans extraits »), T-032 (« captures Storybook avant/après »), T-033 (stories des modales et cartes).
  - T-038 : « exclure storybook-static de l'ESLint » reste utile tant que ce dossier existe sur les postes (il est ignoré par git), mais il n'y a plus de job `vitest` à mettre en CI.
  - T-004 : le lot « storybook » et l'exclusion de `storybook-static` doivent refléter le travail déjà fait sur la branche de retrait, sinon T-004 recommit ce qui est supprimé.
  - T-011 : une partie est déjà réalisée sur `chore/retirer-storybook` (`src/stories`, `.storybook`). Le registre le traite comme à faire.
  - Conflits entre la branche de retrait et les tâches du plan : `package.json` et `package-lock.json` (16 064 lignes modifiées, touchés aussi par T-008, T-011, T-038), `eslint.config.mjs` (T-011, T-033, T-038), `src/core/rbac/PermissionContext.tsx` (T-024, T-025), `AuthContext.tsx` (T-037), `OrganizationContext.tsx`.
  - DOC-017 (gabarit Storybook) n'est couvert par aucune tâche ; il est résolu par la branche de retrait.
- **Correction** :
  1. Fusionner `chore/retirer-storybook` dans `remy` avant T-004, ou l'inclure comme lot explicite de T-004. Marquer DOC-017 et la partie de T-011 comme faites.
  2. Remplacer partout « Storybook » dans les critères par un équivalent réel, ou le supprimer.
  3. Trancher explicitement : soit un runner unitaire est réintroduit (nouvelle question `docs/questions/frontend/tests-unitaires.md`, dépendance ajoutée à T-038), soit la stratégie frontend est Playwright seul. Le plan actuel ne tranche pas et laisse T-024, T-025 et T-033 sans moyen de test.
  4. Mettre à jour `baseline-tests.md` (le chiffre de 223 tests n'est plus vrai).

### REV-A-05 : T-004 est un goulot et un fourre-tout (Élevée)

- **Tâche** : T-004.
- **Preuve** : 283 fichiers à trier en lots, avec tests par lot, bloquent toutes les tâches et tout le chemin IAM. Aucune estimation de durée n'existe dans le plan (voir REV-A-19). Le tri doit aussi intégrer la branche de retrait de Storybook (REV-A-04).
- **Correction** : découper T-004 en T-004a (base minimale qui débloque le chemin critique : backend `zylo_liquid` + socle, frontend hors Storybook) et T-004b (reste, parallèle). Donner une durée cible et un critère de sortie mesurable.

### REV-A-06 : cycle de vie des utilisateurs absent du chemin critique (Élevée)

- **Tâches** : T-021, T-022, T-024, T-025, T-020.
- **Preuve** : aucune tâche ne crée :
  - la désactivation ou la suspension d'un utilisateur (`User.status` accepte `active | suspended | pending`, `app/identity/models.py:27`). T-020 déclare révoquer les sessions « lors de la désactivation », mais aucune route de désactivation n'est prévue ;
  - le retrait d'un utilisateur de l'organisation (suppression de `OrganizationUser`) ;
  - le retrait d'une affectation à un module. T-022 ne prévoit que création et lecture ; T-025 n'a pas d'action « retirer ».
- **Impact** : le client demande « créer ses utilisateurs, puis choisir un utilisateur dans chaque module ». Sans retrait ni désactivation, un départ d'employé ne peut pas être traité dans l'application.
- **Correction** : ajouter à T-021 `PATCH /organizations/{id}/users/{userId}` (statut), à T-022 `DELETE` d'une affectation module et de l'appartenance, à T-025 l'action correspondante, et les tests cross-org (T-010) sur ces routes. Ajouter T-020 comme dépendance de ces routes pour la révocation.

### REV-A-07 : mot de passe temporaire connu du créateur (Élevée)

- **Tâche** : T-021 ; question `invitation-ou-mot-de-passe-temporaire.md`.
- **Preuve** : T-021 renvoie le mot de passe temporaire une fois au créateur (propriétaire ou administrateur). `mustChangePassword` ne bloque que les routes métier : `/auth/change-password` reste accessible. Le créateur peut donc se connecter comme l'employé avant sa première connexion et changer le mot de passe, ce qui verrouille le compte. C'est le risque IAM-007 de l'audit, que T-021 ne traite pas.
- **Correction** : pas de mot de passe connu du créateur. Compte créé en statut `pending` avec un lien d'activation à usage unique envoyé hors application, ou, à défaut, mot de passe temporaire affiché une fois puis compte bloqué pour tout autre usage tant que l'utilisateur n'a pas choisi son mot de passe via un jeton distinct. Mettre à jour la question et T-021.
- **Point d'attention** : T-021 ajoute `identity.user.manage`. Les propriétaires existants ne l'auront pas. Le schéma existe déjà (`backfill_owner_default_permissions` dans `app/identity/service.py`), T-021 doit l'appliquer et l'inclure dans ses tests.

### REV-A-08 : « permission plateforme » supposée, inexistante (Élevée)

- **Tâche** : T-019 (étape 4 : `billing/plans` « réservées à une permission plateforme »).
- **Preuve** : `app/identity/service.py:26` indique « sans concept de super-admin plateforme ». Aucune tâche ne crée ce concept.
- **Correction** : deux options. (a) Supprimer la création de plans côté API et laisser le catalogue en seed (le plus simple, cohérent avec « catalogues authentifiés » de T-023). (b) Créer une question et une tâche dédiées pour le modèle plateforme. Recommandation : (a), et corriger la fiche.

### REV-A-09 : CI bloquante livrée après les changements IAM (Élevée)

- **Tâches** : T-038 (vague 2, dépendances T-006, T-007, T-009, T-036), T-010, T-018, T-019, T-021 (vagues 1 et 2).
- **Preuve** : le filet automatique arrive après les modifications de sécurité les plus sensibles. Le plan repose sur « l'orchestrateur seul fusionne », sans contrôle automatique. T-038 dépend de T-036 (qui n'est pas indispensable à la CI minimale) et de T-009. T-038 lance Playwright sur build prod sans dépendre de T-008.
- **Correction** : scinder T-038 en T-038a (pytest, `tsc`, `build`, garde sur les dumps et les ports, dès la fin de T-006/T-007) et T-038b (`lint-imports`, `lint`, Playwright prod, après T-036 et T-008). T-038a devient une dépendance de T-010.

### REV-A-10 : décisions métier prises par l'agent, sans validation du client (Élevée)

- **Tâches** : T-007, T-010, T-018, T-019, T-021, T-023 ; plan §2 « on avance sur la recommandation et on reste réversible ».
- **Preuve** : plusieurs décisions touchent les droits de clients réels et ne sont pas réversibles sur les données :
  - T-007 : le rôle manager devient un sur-ensemble du responsable de tour, donc gagne des droits dans les organisations existantes ;
  - T-018 : interdiction des rôles multi-modules (voir REV-A-03) ;
  - T-019 : création d'organisation ouverte à tout utilisateur authentifié, avec quota « configurable » (aucune valeur fournie) ;
  - T-021 : mot de passe temporaire (voir REV-A-07).
  La priorité n° 1 est celle du client. Le plan lui-même prévoit une question « explicitement demandée par le commanditaire » pour la purge (T-001), mais aucune pour ces décisions.
- **Correction** : ajouter une colonne « validé par le client » dans le plan §7, et faire de la validation une condition de fusion de T-007, T-018, T-019 et T-021. Les questions dont la réponse change des droits existants ne doivent pas être « appliquées » par défaut.

### REV-A-11 : conflits de fichiers entre tâches de même vague non séquencés (Élevée)

- **Tâches** : T-010, T-015, T-018, T-036, T-021 ; plan §5.
- **Preuve** :
  - T-010 (P0) protège les routes `protected-demo` (identity, modules_registry) et les teste ; T-015 supprime ces mêmes routes démo. Même vague 1, pas de dépendance.
  - T-010 crée `get_organization_context` dans `app/rbac/service.py` ; T-036 (vague 2) déplace les dépendances FastAPI de `rbac/service.py` vers `dependencies.py`. Il faut écrire T-010 directement dans `app/rbac/dependencies.py`, sinon T-036 réécrit T-010.
  - T-036 retire le couplage `modules_registry` → `roles_seed` (`modules_registry/service.py:133,137`), tandis que T-018 ajoute du code de seed dans le même fichier. T-036 doit précéder T-018, ou T-018 doit utiliser le registre de seeders.
  - T-034 touche `zylo_liquid/service.py` en vague 1, en même temps que T-027 et T-029 (aussi vague 1), dont les fiches déclarent le conflit sans que le graphe le matérialise.
- **Correction** : ajouter les dépendances manquantes (T-036 avant T-018 sur le seeding ; T-015 partie démo après T-010 ou T-010 corrigé pour ne plus tester les routes démo) et une règle « un seul fichier chaud par vague, ordre écrit ».

### REV-A-12 : unicité `userRole` et NULL (Moyenne, à vérifier en base)

- **Tâches** : T-018, T-022.
- **Preuve** : `UserRole` a une contrainte unique sur (userId, organizationId, roleId, resourceType, resourceId) (migration `95e8bd6bf477`). Avec PostgreSQL (NULLS DISTINCT par défaut), deux lignes à `resourceType` et `resourceId` NULL ne sont pas comparées : une attribution d'organisation entière peut être dupliquée.
- **Correction** : `UNIQUE NULLS NOT DISTINCT` (PostgreSQL 15 et plus, à vérifier sur la version déployée), ou deux index uniques partiels. Ajouter à T-018 une requête de détection des doublons existants avant la migration, et un test de contrainte.

### REV-A-13 : dépendances déclarées dans les fiches et dans le registre ne concordent pas (Moyenne)

- **Preuve** (comparaison fiche / registre) :
  - T-007 ↔ T-018 : T-007 dit « dépend de la décision de T-018 » et T-018 dépend de T-007. Dépendance circulaire « molle », absente du graphe.
  - T-020 : fiche « dépend de T-011 et T-012 », registre « T-012, T-013 ». T-011 (hygiène frontend) n'a aucun lien avec `app/auth/`. T-013 est absent de la fiche.
  - T-015 : fiche « T-013 sur les uploads pour Pillow » : c'est T-014.
  - T-002 : fiche « bloque T-011 » (frontend), non reporté dans le registre.
  - T-027 : fiche dépend de T-005, absent du registre.
  - T-029 : fiche dépend de T-005, absent du registre.
  - T-033 : fiche dépend de T-024 et T-025 (vague 3), ce qui place T-033 après elles et pas en vague 3.
  - T-010, T-012, T-038 : dépendent de Playwright prod (T-008) sans le déclarer.
  - T-026 : utilise `npm run e2e:prod`, script absent de `package.json`. Aucune tâche ne le crée explicitement.
- **Correction** : générer le registre et le graphe à partir des fiches (le script de cette revue peut servir de base) et faire échouer la CI documentaire si les deux ne concordent pas.

### REV-A-14 : table des fichiers chauds incomplète (Moyenne)

- **Preuve** : la table du plan §5 omet des fichiers touchés par plusieurs tâches : `app/identity/service.py` et `router.py` (T-010, T-013, T-019, T-021), `app/core/security.py` (T-019, T-021, T-036), `app/billing/*` (T-010, T-019), `app/rbac/router.py` (T-010, T-018, T-022), `app/core/config.py` (T-002, T-003, T-012, T-015, T-027, T-037), `Dockerfile` (T-002, T-003, T-015, T-028), `alembic/versions/` (T-012, T-013, T-018, T-020, T-027), `eslint.config.mjs` (T-011, T-033, T-038), `package.json` (T-008, T-011, T-038), `src/core/auth/*` (T-013, T-037).
- **Migrations** : la révision Alembic actuelle est unique (`f1a3b5c7d849`, vérifié). Cinq tâches de vagues 1 et 2 vont créer des migrations en parallèle. Sans règle, cela produit plusieurs têtes. Le plan n'en parle pas.
- **Correction** : compléter la table, et ajouter une règle : une seule tâche avec migration par vague, ou rebase obligatoire avant fusion avec vérification `alembic heads` = 1.

### REV-A-15 : découpe de `zylo_liquid/service.py` (Moyenne)

- **Tâches** : T-034, T-035.
- **Preuve** : 15 681 lignes, 504 fonctions de premier niveau (vérifié). T-035 regroupe cinq lots séquentiels (caisse, livraisons, réglementation, ventes, reste) dans une seule ligne de registre, alors que le plan dit « un lot par tâche ». Le critère « cinq lots mergés » rend la tâche non planifiable.
- T-034 indique « lint-imports après chaque extraction (contrats T-036) », mais T-036 est en vague 2 et dépend de T-010 : T-034 dépend d'un contrat qui n'existe pas encore. Les 10 contrats actuels suffisent.
- **Point d'architecture** : le plan décrit une façade de réexport mais ne traite pas des fonctions partagées entre sous-domaines (helpers communs, constantes). Sans une règle sur leur emplacement (`common/`, par exemple), les imports circulaires sont probables, comme le signale T-034.
- **Correction** : splitter T-035 en T-035a à T-035e, chacun avec sa dépendance et son fichier chaud. Retirer la dépendance à T-036 de T-034 (la vérification se fait avec les contrats existants). Ajouter une règle sur les helpers partagés et sur l'ordre avec T-027 et T-029.

### REV-A-16 : T-036, contrats import-linter (Moyenne)

- **Tâche** : T-036 (priorité P2 pour un P1 résolu, ARC-005).
- **Preuve** :
  - ARC-005 (cycles alerts ↔ zylo_liquid) n'a aucun fichier dans les « Fichiers concernés » de T-036. Ce cycle est un des deux principaux de l'audit. Il manque aussi ARC-006 (`zylo_tanker/dev_seed.py` qui écrit dans les tables de `location`).
  - T-036 demande un « contrat d'acyclicité ». import-linter 2.15 (`requirements.txt`) n'a pas de type `acyclic` général ; il a `acyclic_siblings`, qui ne vaut que pour les paquets frères. `app.alerts` et `app.modules.zylo_liquid` ne sont pas frères. Il faut nommer le type et le périmètre dans la fiche.
  - T-036 marque `app/shared/permissions.py` « (créé) ». Il existe déjà (permissions de devises et géographie).
- **Correction** : ajouter ARC-005 (alerts) et ARC-006 aux fichiers de T-036, nommer le type de contrat, corriger « créé » en « étendu », et passer T-036 en P1 si ARC-005 reste dans son périmètre.

### REV-A-17 : tâches surdimensionnées ou mal reliées (Moyenne)

- **T-015** : six sujets sans lien (CVE, OpenAPI, routes démo, CORS, double montage du routeur, conteneur non root). Conflit avec T-010 (REV-A-11). À scinder : sécurité périphérique (CVE, OpenAPI, CORS) et déploiement (conteneur, routeurs).
- **T-033** : composants partagés, trois graphiques, `fetch` hors client, accessibilité, états d'erreur, déplacement de `TrucksMap` entre modules, migration d'écrans un par commit. À scinder : composants partagés ; réseau et états d'erreur ; accessibilité.
- **T-037** : cookies HttpOnly (P1, sécurité) est planifié en dernière vague, après huit tâches frontend (T-033 notamment), alors que sa partie backend dépend seulement de T-020. Le « même site » (proxy ou sous-domaine) n'est couvert par aucune tâche d'infrastructure ni question validée : hypothèse non justifiée.
- **Correction** : scinder T-037 en partie backend (vague 2, après T-020) et partie frontend (après T-003 et T-033 seulement si `client.ts` est modifié), et ajouter la décision d'infrastructure à `docs/questions/`.

### REV-A-18 : hypothèses non justifiées et omissions (Moyenne)

- Quota de création d'organisation (T-019) : aucune valeur, aucun emplacement de configuration, aucun test de dépassement.
- Migration Holykell (T-027) : pas de procédure de retour arrière documentée si la clé est perdue ; le plan le signale mais ne l'assigne à personne.
- Rotation des identifiants (T-001) : l'action est réalisée par l'opérateur hors dépôt, sans critère de sortie vérifiable dans les fiches.
- Aucune tâche sur les sauvegardes avant migration (T-028 la mentionne comme « procédure opérateur »).

### REV-A-19 : estimation, chemin critique, capacité (Faible)

- Aucun plan ne donne d'estimation de charge, de durée ou de capacité. Le chemin critique (REV-A-01) est sous-estimé et T-004 n'a pas de durée. La faisabilité ne peut pas être jugée.
- **Correction** : ajouter une taille (S, M, L) par tâche, et une estimation du chemin critique en jours, en tenant compte de T-004 et de la validation client (REV-A-10).

### REV-A-20 : ports et worktrees (Faible)

- `PLAN §2` parle d'un dossier `wt/` ; le répertoire réel est `worktrees/`. Le plan doit dire lequel.
- Le port Playwright prod est 3055 (`playwright.config.ts`, valeur canonique de T-003), alors que la règle d'allocation donne `3300 + n` pour le frontend production. Les deux règles coexistent sans précédence.

### REV-A-21 : cohérence audits / plan (Faible)

- ARC-005 est P1 dans l'audit, traité par une tâche P2 (REV-A-16).
- DOC-017 n'est couvert par aucune tâche (résolu par la branche de retrait, REV-A-04).
- `ISSUES_A_CREER.md` duplique le registre : deux sources à maintenir. À générer.

---

## Réponses directes

- **Un cycle de dépendances ?** Non dans le registre (vérifié par parcours). Un cycle mou existe entre T-007 et T-018 (REV-A-13).
- **Une tâche bloquante oubliée ?** Oui : la branche `chore/retirer-storybook` n'est dans aucune tâche (REV-A-04). Et T-008 (Playwright prod) manque comme dépendance de T-010, T-012, T-038 (REV-A-13).
- **`Role.moduleCode` suffit-il ?** Oui, sous quatre conditions (REV-A-03).
- **Découpe de `zylo_liquid/service.py`** : la stratégie (filet de caractérisation, façade) est bonne. T-035 est trop gros (REV-A-15).
- **Tâches à Storybook** : T-011, T-024, T-025, T-030, T-031, T-032, T-033, T-038, T-039, T-004 (REV-A-04).

## Plan de correction proposé (ordre)

1. Décider le modèle de base (REV-A-02) et fusionner la branche de retrait (REV-A-04).
2. Générer registre et graphe depuis les fiches, et corriger les vagues (REV-A-01, REV-A-13).
3. Réécrire T-018, T-021, T-022, T-019 (REV-A-03, REV-A-07, REV-A-08) et ajouter T-021/T-022 pour le cycle de vie (REV-A-06).
4. Scinder T-038, T-035, T-033, T-015, T-037 ; avancer T-038a et T-036 (REV-A-09, REV-A-15, REV-A-17).
5. Faire valider par le client les décisions de droits (REV-A-10) avant toute fusion de T-007, T-018, T-019, T-021.
