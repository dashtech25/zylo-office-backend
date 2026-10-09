# Revue critique indépendante : système de design et tests Playwright

- **Date** : 2026-10-08
- **Objet** : plan de remise sur pied (`docs/plans/PLAN_REMISE_SUR_PIED.md`, `REGISTRE_TACHES.md`, fiches `taches/T-001..T-040`), croisé avec le code frontend réel.
- **Périmètre focus** : système de design (coquilles de navigation, fil d'Ariane, tokens CSS, tables, composants, documentation des composants après retrait de Storybook) et tests Playwright (parcours métier, droits, isolation, sélecteurs, fixtures, build de production, échecs actuels).
- **Méthode** : lecture seule du plan, de l'audit frontend et de la baseline ; vérification dans le code (`zylo-office-frontend`, branche `remy` @ `14c1f07`), dans la branche `chore/retirer-storybook` (commit `64c97e1`) et dans le CSS compilé présent dans `.next/`. Aucun test, build ni lint n'a été relancé. Le seul fichier écrit est celui-ci.
- **Sévérité** : **Critique** (bloque la suite du plan ou expose un secret) · **Majeure** (critère non vérifiable, contradiction, ou risque de régression) · **Mineure** (précision, dette de documentation).

## Synthèse

Le plan n'est pas exécutable en l'état sur son volet design et tests. Trois problèmes structurants :

1. **Storybook a été retiré sur une branche non fusionnée et non enregistrée** (`chore/retirer-storybook`), mais le plan, l'audit et neuf fiches supposent encore Storybook et Vitest. Plusieurs critères d'acceptation deviennent impossibles, et le catalogue des composants n'a plus de documentation de remplacement.
2. **La suite Playwright n'est pas versionnée** (25 fichiers non suivis par git), contient un fichier de session avec des jetons en clair non ignoré par git, partage une seule organisation et une seule station entre toutes les specs, et ne teste ni l'accès interdit ni l'isolation inter-organisations.
3. **Le registre et les fiches se contredisent** (dépendances de T-025 et T-026, ports, parallélisme des tâches de coquille), ce qui empêche un orchestrateur de fixer l'ordre de fusion sur les fichiers chauds.

Décompte : 2 Critiques (REV-D-01 et REV-D-07 sont à traiter avant T-004), le reste en Majeure ou Mineure.

---

## Constats

### A. Retrait de Storybook et documentation des composants

#### REV-D-01 : Storybook retiré, mais le plan et les fiches le supposent encore
- **Sévérité** : Critique
- **Tâches** : T-011, T-024, T-025, T-030, T-031, T-032, T-033, T-038, T-039 ; ISSUES_A_CREER (T-011) ; REGISTRE (T-011) ; audit `frontend-design.md` (FRT-009, FRT-014, FRT-023, « points conformes »).
- **Preuve** : `git show chore/retirer-storybook --stat` supprime `.storybook/`, `src/stories/` (26 fichiers), 13 `*.stories.*`, `vitest.config.ts`, et retire `storybook`, `vitest`, `@vitest/*`, `vite` de `package.json`. Les fiches contiennent encore : T-011 « `vitest` projet storybook toujours vert (223 tests) » ; T-033 « Storybook : vitest projet storybook vert » et « Stories Storybook des modales et cartes » ; T-030 « story du `ModuleShell` pour chaque configuration » ; T-024 « Vitest storybook : stories » ; T-025 « Storybook : écran et filtre » ; T-031 « Storybook sur les écrans extraits » ; T-032 « captures de référence avant/après (Storybook) » ; T-038 « job frontend : vitest » ; T-039 (chiffres et arborescence sans mention du retrait).
- **Correction proposée** : réécrire ces critères sans Storybook. Remplacer « story » par « entrée de catalogue » (voir REV-D-02) et « vitest storybook » par « Playwright prod + tsc + build ». Mettre à jour l'audit : FRT-009 et FRT-023 deviennent « réglés sur `chore/retirer-storybook` » ; FRT-014 devient obsolète et doit être remplacé par REV-D-02 ; retirer « Tous les composants de `shared/ui` ont une story » des points conformes (faux après le retrait).

#### REV-D-02 : aucune documentation des composants après le retrait
- **Sévérité** : Majeure
- **Tâches** : T-033 (livrable `composants-partages.md`), T-039 (documentation), T-040.
- **Preuve** : `docs/` du frontend ne contient que `architecture/bonnes-pratiques/frontend-backend-tests.md`, `audit/frontend-design.md`, `design-system-zylo-liquid-reference-analysis.md` et `frontend-foundations.md`. La note ajoutée sur `chore/retirer-storybook` dans `docs/frontend-foundations.md` (« Catalogue de composants : voir `docs/` ») renvoie vers un catalogue qui n'existe pas. Le document d'analyse référencé est une analyse de layouts (« Étape 2 : catalogue des layouts »), pas un catalogue de composants. `docs/audit/retrait-storybook.md` reconnaît l'absence de remplacement. Le plan n'a aucune tâche pour ce catalogue.
- **Correction proposée** : ajouter un livrable mesurable, par exemple `docs/architecture/frontend/catalogue-composants.md`, généré par un script à partir de `src/shared/ui/index.ts` : une section par composant (rôle, props, variantes, états, exemple, règles a11y). Critère : chaque export de `shared/ui` apparaît dans le catalogue, et un contrôle échoue si un export manque. Ce livrable doit être ajouté à T-033 ou à T-039, avec mise à jour de la fiche T-039 pour qu'elle ne parle plus de « design system unique » sans catalogue.

#### REV-D-03 : suppression de Vitest sans remplacement décidé
- **Sévérité** : Majeure
- **Tâches** : T-038 (job vitest), T-033, T-011, baseline (section 2).
- **Preuve** : le commit `64c97e1` supprime Vitest et déclare « aucun test unitaire dans le dépôt, donc aucune config minimale n'a été écrite ». `docs/audit/retrait-storybook.md` indique que les 223 tests disparaissent. Aucune fiche ni question ne tranche si les composants partagés (`QueryState`, `Table`, `Tabs`, `Modal`, `formatDateTime`) doivent avoir des tests.
- **Correction proposée** : créer `docs/questions/tests/couche-tests-composants.md` avec une recommandation (par exemple Vitest + Testing Library sur `shared/ui` et `shared/lib`, hors Storybook, ou « Playwright seul » assumé). Tant que la question n'est pas tranchée, T-038 ne peut pas lister un job vitest.

#### REV-D-04 : le retrait Storybook n'est dans aucune tâche et viole les règles d'exécution
- **Sévérité** : Majeure
- **Tâches** : PLAN §2 (règles), §5 (fichiers chauds), REGISTRE.
- **Preuve** : la branche `chore/retirer-storybook` part de `remy @ 14c1f07`, alors que §2 impose une branche `<type>/T-XXX-<slug>` depuis le tag `base-T004`. Elle n'a pas d'identifiant T-XXX. Elle touche des fichiers absents de la table §5 : `src/core/auth/AuthContext.tsx`, `src/core/organization/OrganizationContext.tsx`, `src/core/rbac/PermissionContext.tsx` (touchés par T-024 et T-025), `eslint.config.mjs` (T-033, T-038), `package.json` et `package-lock.json` (16 064 lignes modifiées), `e2e/mockApi.ts` et `e2e/mockBackend.ts` (T-008). Un worktree existe déjà sous `office/worktrees/frontend-retirer-storybook`, alors que §2 prescrit `wt/T-XXX-<back|front>`.
- **Correction proposée** : créer une fiche (par exemple T-041, « retrait Storybook », vague 0 ou 1) qui devient la référence du retrait. Ajouter les fichiers listés à la table §5. Décider si la branche est rebasée sur `base-T004` ou fusionnée en premier, et l'écrire dans la fiche.

#### REV-D-05 : `.gitignore` retiré par le commit de retrait, `storybook-static/` exposé
- **Sévérité** : Majeure
- **Tâches** : T-004 (tri du travail en cours), T-038 (lint), T-011.
- **Preuve** : le `.gitignore` de `remy` contient `*storybook.log` et `storybook-static` ; celui de `chore/retirer-storybook` ne les contient plus. Le dossier `storybook-static/` (18 Mo) et `debug-storybook.log` existent dans le répertoire de travail. T-004 compte sur une exclusion manuelle (liste en T-004 ligne 18), et T-038 n'ajoute l'ignore ESLint que pour `storybook-static`. Le lint échoue à cause de ce dossier (baseline : 580 erreurs).
- **Correction proposée** : dans T-004, supprimer les artefacts locaux hors git (`storybook-static/`, `debug-storybook.log`) avant tri, et ajouter une vérification `git status --ignored` au critère de T-004. Dans T-038, ajouter « dossier supprimé » en plus de « ignore ESLint ».

#### REV-D-06 : doc des composants et tokens référencée par la règle, mais inexistante
- **Sévérité** : Mineure
- **Preuve** : `docs/questions/` (backend) ne contient que `README.md`. Le plan §7 liste 22 questions, dont `frontend/palette-de-reference.md` (T-032, « recommandation appliquée »), `frontend/bibliotheque-graphiques.md` (T-033), `rbac/code-http-acces-interdit.md` (T-010), `tests/holykell-simulateur.md` (T-009). Aucune n'existe. Le plan §7 dit que la question sur la purge « doit exister avant que T-001 soit fusionnée », ce qui est aujourd'hui faux.
- **Correction proposée** : créer au minimum les questions bloquantes avant leur tâche (T-001, T-010, T-032, T-033, T-009), avec le gabarit de `docs/questions/README.md`. Sinon, retirer les mentions « recommandation appliquée ».

### B. Système de design

#### REV-D-07 : jetons de session de test en clair, non ignorés par git
- **Sévérité** : Critique
- **Tâches** : T-004, T-008, T-026 (global-setup), T-016.
- **Preuve** : `e2e/.auth/gerant-setup.json` contient, pour l'origine `http://localhost:3055`, `zylo_office_access_token` et `zylo_office_refresh_token` en clair (contenu vérifié par les noms de clés, valeurs non reproduites). Le `.gitignore` du frontend ne contient ni `e2e/.auth/` ni `e2e/fixtures/`, et `git status` affiche `?? e2e/.auth/`. Le global-setup écrit ce fichier à chaque exécution. Les `best-practices` (`frontend-backend-tests.md` §3.2) demandent de l'ignorer, mais aucune fiche ne le prescrit. T-004 cite `e2e/.aut…` dans sa liste d'exclusion, mais rien ne le garantit dans le dépôt.
- **Correction proposée** : ajouter `e2e/.auth/` et `e2e/fixtures/` à `.gitignore` dans T-008 (critère : `git check-ignore e2e/.auth/gerant-setup.json` renvoie un résultat). Supprimer le fichier existant. Si un commit a déjà eu lieu, considérer les jetons comme compromis (rotation). Le global-setup doit écrire dans un répertoire temporaire hors dépôt.

#### REV-D-08 : tokens en double, et une troisième couche non recensée
- **Sévérité** : Majeure
- **Tâches** : T-032, FRT-004.
- **Preuve** : `src/app/globals.css` contient un bloc `:root` (valeurs, par ex. `--color-primary: #3498db`) puis un bloc `@theme inline` qui redéclare chaque token comme `--color-primary: var(--color-primary)`. Ce n'est pas un doublon anodin : c'est une référence circulaire. Dans le CSS compilé (`.next/static/chunks/cc18660df191e658.css`), la déclaration circulaire apparaît à l'offset 8491 et `:root{--color-primary:#3498db}` à l'offset 61237. Le rendu actuel n'est correct que parce que la seconde déclaration gagne par ordre de cascade. L'audit ne cite que `globals.css` et `prototype.css` (FRT-004) : il omet cette troisième couche.
- **Correction proposée** : dans T-032, supprimer les redéclarations circulaires du bloc `@theme inline` (ou ne garder que les références vers des valeurs non circulaires) et ajouter un critère vérifiable : `grep -c -- "--color-[a-z-]*:var(--color-" .next/static/**/*.css` renvoie 0 pour les tokens de `globals.css`, après `next build`.

#### REV-D-09 : critère « variante sombre » contraire au code, et décision palette non consignée
- **Sévérité** : Majeure
- **Tâches** : T-032 (objectif et stratégie).
- **Preuve** : T-032 demande des tokens « sur `:root` (avec variante sombre) ». `globals.css` (commentaire en tête) indique « Light-only pour l'instant (aucune source ne demande de dark mode) ». T-032 cite aussi « Recommandation appliquée » pour `docs/questions/frontend/palette-de-reference.md`, qui n'existe pas (REV-D-06).
- **Correction proposée** : retirer « avec variante sombre » du critère, ou ajouter une tâche explicite. Créer la question palette avant le démarrage de T-032.

#### REV-D-10 : double fil d'Ariane, avec une régression d'accessibilité et un sélecteur non stable
- **Sévérité** : Majeure
- **Tâches** : T-031, T-030, FRT-003, FRT-012.
- **Preuve** : le libellé de topbar est calculé dans `src/modules/zylo-liquid/components/ZyloLiquidShell.tsx` (lignes 182-186, rendu ligne 253). `PageHeader` rend `<nav aria-label={breadcrumbLabel}>` dès deux niveaux (`src/shared/ui/PageHeader.tsx` lignes 24-25). `StationDetailScreen.tsx` (lignes 306-309) n'envoie pas `breadcrumbLabel`, donc sa `<nav>` n'a pas de nom accessible. `TankDetailScreen.tsx` l'envoie (ligne 180). Le libellé étant traduit, un sélecteur `nav[aria-label=…]` ne peut pas être écrit de manière stable en Playwright.
- **Correction proposée** : dans T-031, rendre `breadcrumbLabel` obligatoire (ou valeur i18n par défaut) et ajouter un `data-testid="breadcrumb"` documenté. Critère Playwright : sur la page station et la page cuve, `getByTestId('breadcrumb')` existe exactement une fois, et la topbar n'a pas de libellé de page.

#### REV-D-11 : la critère « une seule nav par page » se contredit avec le fil d'Ariane
- **Sévérité** : Majeure
- **Tâches** : T-030 (tests attendus), T-031.
- **Preuve** : T-030 demande « une seule `nav` par page (test de comptage) ». `PageHeader` rend lui-même une `<nav>` dès deux niveaux. Le comptage de `nav` échoue donc dès qu'une page a un fil d'Ariane, ce qui est le cas de toutes les pages de détail.
- **Correction proposée** : compter la navigation de module par un sélecteur précis (`data-testid="module-nav"` posé par `ModuleShell`), et compter le fil d'Ariane séparément.

#### REV-D-12 : parallélisme contradictoire et conflits de fichiers non ordonnés
- **Sévérité** : Majeure
- **Tâches** : T-030, T-031, T-032, T-033, PLAN §5.
- **Preuve** : T-030 dit « Ne pas lancer en parallèle avec T-031 et T-032 ». T-031 dit « Parallélisable avec T-032 et T-033 ». T-032 dit « Parallélisable avec T-031, T-033 ». T-033 dit « ne pas lancer en parallèle avec T-030 ou T-032 sur les mêmes fichiers ». Or T-031 et T-032 modifient tous deux `ZyloLiquidShell.tsx`, et T-032 et T-033 modifient `TrucksMap.tsx` (T-032 aux lignes 72 et 94, T-033 le déplace dans `shared`). La table §5 indique seulement « T-030 bloque les deux autres ».
- **Correction proposée** : ordonner T-031 → T-032 → T-033 dans §5 et dans le registre, avec la liste des fichiers par tâche. Corriger les sections « Parallélisable avec » des fiches pour qu'elles reprennent cet ordre.

#### REV-D-13 : tables brutes, critère non vérifiable et comptages non reproductibles
- **Sévérité** : Majeure
- **Tâches** : T-033 (critère « aucun `<table>` brut hors `shared/ui` sauf tableaux métier listés »), FRT-005.
- **Preuve** : 30 fichiers hors `shared/ui` contiennent `<table` (reproduit). Le critère renvoie à une liste de « tableaux métier listés » qui n'existe dans aucune fiche. L'audit annonce `Table` importé dans 54 fichiers ; le recompte donne 44 (import nommé depuis `@/shared/ui`).
- **Correction proposée** : dans T-033, lister en annexe les tableaux exemptés (nom de fichier), et ajouter un script de contrôle (`grep -rl "<table" src | grep -v shared/ui`) qui échoue hors liste. Corriger le comptage de l'audit.

#### REV-D-14 : pages `src/app` et règle « une ligne » non atteignables avec le périmètre de T-031
- **Sévérité** : Majeure
- **Tâches** : T-031, T-011.
- **Preuve** : 53 `page.tsx` sous `src/app`. La liste de T-031 ne couvre pas `(public)/tarification/page.tsx` (212 lignes), `(public)/produits/page.tsx` (175), `(auth)/register/page.tsx` (77), `(auth)/login/page.tsx` (85), `(public)/essai-gratuit` (61), `(public)/communaute` (50), `(public)/aide` (47). Les pages `src/app/zylo-liquid/*` font 8 à 10 lignes (pages « coming soon », pas de délégation d'une ligne). `(app)/ui-preview/page.tsx` (234 lignes) est supprimé par T-011. La règle de `src/app/CLAUDE.md` est `export { default } from "…"`, ce qui est une seule ligne ; T-031 dit « une ligne » sans préciser la forme.
- **Correction proposée** : dans T-031, lister les 53 pages avec leur cible d'écran, préciser la forme de la ligne (`export { default } from`), et définir les exceptions (`layout`, `loading`, `error`, route handlers, pages publiques si elles restent hors module). Ajouter le script de contrôle prévu dans la fiche.

#### REV-D-15 : tokens et composants dupliqués, comptages à refaire
- **Sévérité** : Mineure
- **Preuve** : FRT-019 annonce 47 occurrences d'hex dans `*.tsx` ; le recompte donne 9 fichiers `.tsx` hors stories contenant un hex à six chiffres. FRT-011 annonce « au moins 13 » usages `useQuery` sans gestion d'erreur ; le recompte donne 12 fichiers avec `isError` pour 71 fichiers `useQuery`, sans lecture fine. Les deux comptages ne sont pas reproductibles.
- **Correction proposée** : remplacer ces chiffres par des commandes de contrôle à relancer dans T-032 et T-033 (critère : le résultat de la commande est 0 ou une liste explicite).

#### REV-D-16 : la coquille tanker n'a pas de contrôle, et T-025 suppose une API absente
- **Sévérité** : Majeure
- **Tâches** : T-025, T-030, FRT-015.
- **Preuve** : `src/app/zylo-tanker/layout.tsx` ne contient que `ProtectedRoute` et `ZyloTankerShell` (lignes 4-10). `src/core/rbac/PermissionContext.tsx` expose `can(permissionCode: string)` (lignes 14 et 53), sans paramètre de module. T-025 écrit « `can(code, module?)` », et son critère « aucun bouton visible sans permission réelle pour le module » n'a pas de liste de permissions par module pour être vérifié.
- **Correction proposée** : dans T-025, écrire la signature cible et la table « module × permission » attendue pour les rôles par défaut. Le critère devient une assertion Playwright sur cette table.

### C. Tests Playwright

#### REV-D-17 : la suite entière n'est pas versionnée
- **Sévérité** : Majeure
- **Tâches** : T-004, T-008, T-009, T-026, T-038.
- **Preuve** : `git ls-files e2e` donne 2 fichiers (`alert-center.spec.ts`, `mockBackend.ts`). `git status --short e2e` donne 25 entrées `??` (22 specs `gerant-*`, `proprietaire-*`, `global-setup.ts`, `fixtures/`, `.auth/`). Le plan ne prévoit le commit de `e2e/` nulle part, alors que T-038 veut une CI qui exécute cette suite et que T-009 corrige des specs non suivies.
- **Correction proposée** : ajouter à T-004 un lot « e2e » (commit des specs et du global-setup, sans `.auth/`). Critère de T-008 : `git ls-files e2e | wc -l` égal au nombre de fichiers `.spec.ts`.

#### REV-D-18 : isolation absente entre specs, et la base est partagée avec pytest
- **Sévérité** : Majeure
- **Tâches** : T-005, T-008, T-009, T-026, PLAN §2.
- **Preuve** : `e2e/global-setup.ts` crée une seule organisation, une seule station et une seule cuve, dont les identifiants sont écrits dans `fixture-data.json` et partagés par toutes les specs. `playwright.config.ts` ne fixe ni `workers` ni de projet d'isolation. Les données de test utilisent `pumpBase = 3000 + (stamp % 6000)` (par exemple `gerant-jaugeage-cuves.spec.ts:70`, `gerant-ouverture-tour.spec.ts:30`), ce qui peut entrer en collision. La baseline (échec B4 : « attendu 2, reçu 3 ») est compatible avec une donnée résiduelle d'une autre spec. La baseline a aussi tourné sur `zylo_office_test`, base que `tests/conftest.py` vide (`TRUNCATE ... CASCADE`) à chaque run pytest. Le plan (§2) interdit de partager une base entre tâches, mais la baseline l'a fait.
- **Correction proposée** : fixture de données par test ou par worker (org et station uniques, suffixées par le nom du test), `workers` explicite, et interdiction des compteurs globaux. Dans T-008 et T-026, le critère doit être : suite exécutée sur `zylo_t008_test` (ou `zylo_t026_test`), sans seed manuel, et deux exécutions consécutives identiques.

#### REV-D-19 : aucun test d'accès interdit ni inter-organisations dans le parcours
- **Sévérité** : Majeure
- **Tâches** : T-026, T-025, T-010, T-022, objectif du focus.
- **Preuve** : `grep` dans `e2e/` pour `403`, `interdit`, `forbidden`, `refus`, `autre organisation` ne renvoie aucun test de refus (seuls des en-têtes `X-Organization-Id` apparaissent, dans des appels de préparation). T-026 ne prévoit qu'un « refus visible » pour un module non affecté. Il ne prévoit ni appel API direct refusé (403), ni accès à l'organisation B avec un jeton de l'organisation A (404 selon `docs/questions/rbac/code-http-acces-interdit.md`, qui n'existe pas), ni URL directe d'un écran interdit. T-025 se contente du masquage UI, qui ne garantit pas l'enforcement.
- **Correction proposée** : dans T-026, ajouter quatre assertions : (a) refus visible en UI sur un module non affecté ; (b) requête API directe sur ce module renvoie 403 ; (c) utilisateur de l'organisation A avec l'en-tête de l'organisation B reçoit le code décidé par T-010 ; (d) URL directe d'un écran interdit ne charge pas les données. Ajouter à T-026 une matrice « rôle × module × action » figée dans la fiche, qui définit « droits effectifs ».

#### REV-D-20 : dépendances de T-025 et T-026 contradictoires entre registre et fiches
- **Sévérité** : Majeure
- **Tâches** : T-026, T-025, T-024, REGISTRE, PLAN §4.
- **Preuve** : fiche T-026 : « T-008, T-024, T-025, T-021, T-022 » ; registre T-026 : « T-008, T-024, T-025 ». Le graphe du plan §4 relie T-022 à T-026. Fiche T-025 : « T-022, T-024, T-018 » ; registre T-025 : « T-022, T-024 ». T-024 exige un test Playwright prod, mais son registre n'a pas T-008.
- **Correction proposée** : aligner le registre sur les fiches, et ajouter T-008 aux dépendances de T-024.

#### REV-D-21 : critères Playwright incomplets, « 17/27 » non reproductible
- **Sévérité** : Majeure
- **Tâches** : T-008, T-009, baseline section 3.
- **Preuve** : la baseline indique que les résultats ont été obtenus avec une configuration Playwright qui n'est pas dans le dépôt (`scratchpad/playwright.prod.config.cjs`) et un seed manuel après pytest. Le critère de T-008 (« cible 17/27 au minimum ») fixe donc un seuil sur un résultat non reproductible. La baseline dit aussi « 9 specs gérant et P7 » ; le comptage des `test(` donne 27 tests, cohérent.
- **Correction proposée** : T-008 doit committer la configuration de build prod, et le critère devient : « la suite passe avec `npm run e2e:prod` sur base vierge, sans seed manuel ». La cible 17/27 ne doit plus figurer dans la fiche.

#### REV-D-22 : P7 dépend d'une fonctionnalité inexistante et de deux environnements différents
- **Sévérité** : Majeure
- **Tâches** : T-009, T-027, PLAN §9.
- **Preuve** : `e2e/proprietaire-07-connexion-holykell.spec.ts` précise que « aucun endpoint ni formulaire n'existait » au moment de l'écriture et vise `localhost:8500` (simulateur). Le plan §9 parle d'un « compte Holykell externe », et la baseline de `h-smartlink.com` ou du simulateur. Le tag `external` annoncé par T-009 n'existe pas (aucune annotation de tag dans `playwright.config.ts` ni dans les specs). T-009 accepte « 26/27 au moins (P7 requalifié) », ce qui compte P7 comme « hors périmètre » sans le dire.
- **Correction proposée** : dans T-009, définir le tag (`@external`), la commande CI qui l'exclut (`--grep-invert @external`), et écrire dans la fiche que la cible est « 26 passent et 1 exclu », pas « 26/27 ». Choisir l'environnement cible dans `docs/questions/tests/holykell-simulateur.md` (à créer).

#### REV-D-23 : attentes arbitraires déplacées dans des timeouts
- **Sévérité** : Mineure
- **Tâches** : T-009 (critère « pas d'attentes arbitraires »), T-026.
- **Preuve** : `waitForTimeout` n'apparaît nulle part dans `e2e/` (conforme). En revanche, 18 `test.setTimeout` existent, dont 8 de 180 s ou plus (6 à 300 s : `gerant-affectation-pompistes.spec.ts:72`, `gerant-jaugeage-cuves.spec.ts:68`, `gerant-fermeture-index.spec.ts:67`, `gerant-ouverture-tour.spec.ts:28`, `gerant-remplacement-pauses.spec.ts:65`, `gerant-pointage-passation.spec.ts:33` ; 240 s : `gerant-planning-grille.spec.ts:36` ; 180 s : `proprietaire-08-ajout-personnel.spec.ts:36`). Ces durées masquent des lenteurs ou des blocages.
- **Correction proposée** : critère élargi : pas de `setTimeout` de test au-delà de 60 s sans justification écrite dans la spec ; durée mesurée par test dans le rapport de T-009.

#### REV-D-24 : sélecteurs couplés à l'implémentation
- **Sévérité** : Mineure
- **Tâches** : T-009, T-026, T-033.
- **Preuve** : `e2e/` contient `locator("..")` (13 usages, navigation par parent), `xpath=` (3), `locator("td")` (8), `option:checked` (18 usages dans 6 specs : `gerant-planning-grille`, `gerant-fermeture-index`, `gerant-pointage-passation`, `gerant-ouverture-tour`, `gerant-affectation-pompistes`, `gerant-remplacement-pauses`). En revanche `getByRole` (558) et `getByLabel` (225) dominent. `SearchableSelect` est utilisé dans 43 fichiers de `src`, alors que 10 fichiers contiennent encore un `<select>` natif : les `option:checked` ne couvrent pas les deux. Il n'y a pas de règle écrite sur la hiérarchie des sélecteurs.
- **Correction proposée** : ajouter à T-009 une règle (rôle et nom accessible d'abord, `data-testid` ensuite, jamais de parent ni de xpath), et remplacer les sélecteurs de select natif par un helper unique qui gère `SearchableSelect`. Vérifier chaque `option:checked` contre le composant réellement rendu.

#### REV-D-25 : mocks et backend réel mélangés sans étiquette
- **Sévérité** : Mineure
- **Tâches** : T-008, T-026, T-033.
- **Preuve** : `e2e/alert-center.spec.ts` utilise `installMockBackend` (`e2e/mockBackend.ts`, qui réutilise `mockApi.ts`). Le plan (T-026, §2) exige un parcours sur backend réel. Aucune convention ne distingue les specs « mock » des specs « réel ». T-008 indique « `mockBackend.ts` (inchangé) », mais le retrait Storybook (REV-D-04) le modifie.
- **Correction proposée** : nommer les dossiers ou suffixes (`*.mock.spec.ts`, `*.real.spec.ts`) et écrire dans `docs/process/tests.md` que les parcours métier sont `real`. T-026 exige un test `real`.

#### REV-D-26 : ports contradictoires entre plan, fiches et configuration
- **Sévérité** : Majeure
- **Tâches** : T-003, T-008, T-024 à T-033, PLAN §2 et §7.
- **Preuve** : PLAN §2 et T-003 donnent frontend prod `3300+n` (T-008 : `next start -p 3308`, `e2e backend 3108`). Le PLAN §7 propose, dans `architecture/ports-canoniques.md`, frontend 3001, backend 3002, Playwright prod 3055 : c'est ce que fait `playwright.config.ts` (`PORT = 3055`) et `package.json` (`start` et `dev` sur 3001). La baseline utilise le backend sur 3007. Trois schémas coexistent, et la question qui doit trancher n'existe pas.
- **Correction proposée** : trancher `ports-canoniques.md` avant T-003, puis réécrire les ports de chaque fiche à partir de cette table. Tant que ce n'est pas fait, aucune fiche Playwright ne peut être exécutée sans conflit de port.

#### REV-D-27 : le CI bloquante est décrite côté backend seulement
- **Sévérité** : Majeure
- **Tâches** : T-038, T-008.
- **Preuve** : `zylo-office-frontend` n'a pas de dossier `.github/` (le commit de retrait l'indique). Le seul workflow est `zylo-office-backend/.github/workflows/ci.yml.disabled`. T-038 indique « Dépôt(s) : backend et frontend » et place les jobs frontend (`tsc`, `lint`, `build`, Playwright prod) dans `.github/workflows` du backend, sans dire comment le backend obtient le frontend.
- **Correction proposée** : décider dans T-038 si le workflow vit dans le frontend (job frontend) et si le backend est lancé par un service Docker ou par un checkout. Préciser les versions de Node et de Python et le port utilisé par chaque job.

### D. Risques transverses et points non vérifiables

#### REV-D-28 : la stratégie d'isolation repose sur des pratiques marquées « non vérifié »
- **Sévérité** : Mineure
- **Tâches** : PLAN §2, T-005, T-008.
- **Preuve** : `docs/architecture/bonnes-pratiques/frontend-backend-tests.md` indique elle-même que la section 4 (worktrees, base dédiée, ports dérivés) « n'est pas couverte par les sources consultées », et marque **[non vérifié]** la protection CSRF, la règle ESLint sur `fetch` (§1.4), la structure du double fil d'Ariane (§1.2) et l'approche des tables (§1.5). Les fiches T-030 à T-033 s'appuient sur ces points sans le signaler.
- **Correction proposée** : dans chaque fiche de design, reprendre la mention « hypothèse, non sourcée » et transformer la règle en critère mesurable (script ou test), pour qu'elle ne dépende plus de la source.

#### REV-D-29 : l'audit frontend n'est pas à jour de la branche de travail
- **Sévérité** : Mineure
- **Tâches** : audit `frontend-design.md`, T-039.
- **Preuve** : l'audit annonce « Storybook : 35 composants, 35 `.stories` » et « Tous les composants de `shared/ui` ont une story » ; ces points sont faux sur `chore/retirer-storybook`. L'audit exclut explicitement les 229 fichiers modifiés non commités (« hors périmètre »), alors que `git status` en compte 39 modifiés et 25 non suivis dans `e2e/`.
- **Correction proposée** : ajouter une section « état à la date de la branche de référence » dans l'audit, et mettre à jour FRT-009, FRT-014, FRT-023 et les points conformes.

#### REV-D-30 : test de non-régression visuel absent
- **Sévérité** : Mineure
- **Tâches** : T-032, T-030, T-031.
- **Preuve** : T-032 écrit « captures de référence avant/après (comparaison visuelle, pas de snapshot automatique au départ) », mais sans Storybook, aucun outil de capture n'est prévu. T-030 et la migration de la coquille (« risque élevé ») n'ont pas de capture de référence.
- **Correction proposée** : ajouter à T-030 une capture Playwright (`toHaveScreenshot`, ou au minimum une capture manuelle versionnée) de chaque zone (dashboard, station, cuve, tanker) avant migration, comme critère de sortie.

---

## Récapitulatif par tâche

| Tâche | Constats |
|---|---|
| T-004 | REV-D-04, REV-D-05, REV-D-07, REV-D-17 |
| T-008 | REV-D-07, REV-D-17, REV-D-18, REV-D-21, REV-D-26 |
| T-009 | REV-D-22, REV-D-23, REV-D-24 |
| T-011 | REV-D-01, REV-D-03, REV-D-14 |
| T-024 / T-025 | REV-D-01, REV-D-16, REV-D-20 |
| T-026 | REV-D-18, REV-D-19, REV-D-20, REV-D-25 |
| T-030 | REV-D-01, REV-D-11, REV-D-12, REV-D-30 |
| T-031 | REV-D-10, REV-D-12, REV-D-14 |
| T-032 | REV-D-08, REV-D-09, REV-D-12, REV-D-15 |
| T-033 | REV-D-02, REV-D-12, REV-D-13 |
| T-038 | REV-D-03, REV-D-05, REV-D-27 |
| T-039 | REV-D-02, REV-D-29 |

## Ce qui est conforme (vérifié)

- Aucune attente fixe `waitForTimeout` dans `e2e/`.
- `getByRole` et `getByLabel` sont majoritaires dans les specs.
- Aucun `dangerouslySetInnerHTML` dans `src/` (affirmation de l'audit, non revérifiée ici).
- Le build de production (`npm run build`) est déclaré OK dans la baseline, et `tsc` OK (non relancés ici).
- Le commit `64c97e1` déclare avoir relancé `tsc`, `lint` et `build` sur son worktree ; ces résultats n'ont pas été reproduits ici, et les constats REV-D-01 à REV-D-05 portent sur son périmètre et non sur sa qualité technique.

## Limites

- Aucun test Playwright, build, `tsc` ni lint n'a été relancé. Les constats de comportement (rendu, cascade CSS) reposent sur le code et sur le CSS compilé présent dans `.next/`, pas sur une exécution.
- Le CSS compilé dans `.next/` peut dater d'un build antérieur aux sources de `remy`.
- Les contenus de `e2e/.auth/` n'ont pas été reproduits : seuls les noms de clés ont été lus.
- Les comptages sont faits par `grep`, ils peuvent différer de 5 à 10 % de l'analyse manuelle.
