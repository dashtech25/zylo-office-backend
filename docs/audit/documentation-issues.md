# Audit documentation, tâches et issues — Zylo Office

Date : 2026-10-08. Périmètre : `zylo-office-backend` et `zylo-office-frontend` (lecture seule).
Méthode : lecture des docs (README, CLAUDE.md, ARCHITECTURE.md, phase_1_database.md, validation_log.md, docs/, taches/, .github/), vérification par `grep`/`git`/`gh` contre le code.
Priorités : **P1** = contradiction forte ou risque de perte ; **P2** = obsolète, doublon ou gros fichier à découper ; **P3** = cosmétique / hygiène.
Tous les items sont à l'état **Ouvert**.

## Index

| ID | Priorité | Sujet |
|---|---|---|
| DOC-001 | P1 | CI désactivée mais documentée comme bloquante |
| DOC-002 | P1 | Ports backend contradictoires (3002 vs 3007) |
| DOC-003 | P2 | Ports frontend contradictoires (3001 / 3006) |
| DOC-004 | P1 | Cahiers métier `taches/` hors git (risque de perte) |
| DOC-005 | P1 | Module `zylo_tanker` absent de toute la doc |
| DOC-006 | P2 | Trois arborescences backend divergentes |
| DOC-007 | P2 | Arborescence frontend de CLAUDE.md obsolète |
| DOC-008 | P2 | Règle « page = 1 ligne » non respectée |
| DOC-009 | P2 | Index docs/README.md incomplet et non à jour |
| DOC-010 | P2 | Doublon phase 1 base de données (racine vs docs/) |
| DOC-011 | P2 | Gros fichiers de doc à découper |
| DOC-012 | P2 | Cahiers métier : copies « (1) / (2) », répétitions, statut périmé |
| DOC-013 | P2 | Journaux de livraison mélangés à la doc de référence |
| DOC-014 | P2 | Références à des documents absents du dépôt |
| DOC-015 | P2 | Fichiers parasites et dump de base suivis par git |
| DOC-016 | P2 | Deux sources de design system en conflit (frontend) |
| DOC-017 | P3 | Gabarit Storybook et CSS contraires à la règle « aucun CSS local » |
| DOC-018 | P2 | Stratégie Git documentée ≠ pratique |
| DOC-019 | P2 | Arbres de travail très sales (tâche) |
| DOC-020 | P2 | Issues GitHub quasi vides, labels par défaut (tâche) |
| DOC-021 | P1 | Exigences organisations / utilisateurs / modules : source hors dépôt, implémentation partielle (tâche) |
| DOC-022 | P2 | validation_log.md figé au 1er septembre |
| DOC-023 | P3 | docs/architecture/performance : 17 fichiers à plat, phases mélangées aux thèmes |
| DOC-024 | P3 | Nommage de fichiers incohérent (`phase12-...`) |
| DOC-025 | P3 | Environnements et stack non documentés (Neon, prod) |

## Détail

**DOC-001 — P1 — Ouvert — CI désactivée mais documentée comme bloquante**
- Preuves : `.github/workflows/` ne contient que `ci.yml.disabled` (pas de `ci.yml`). Commit `6318b21` : « désactive temporairement le CI ». `ARCHITECTURE.md` §5 (Phase 6) : « CI bloquante sur violation » ; §7 : contrats « exécutés en CI » ; `CLAUDE.md` : « vérifiés en CI ». Le job CI utilise `postgres:16` alors que le serveur local est en 17.11.
- Reco : réactiver `ci.yml` (ou ouvrir une issue dédiée) ; d'ici là, indiquer « CI désactivée depuis 6318b21 » dans ARCHITECTURE §5/§7 et CLAUDE.md.

**DOC-002 — P1 — Ouvert — Ports backend contradictoires**
- Preuves : 3002 dans `zylo-office-backend/README.md` (l. 34-38), `Dockerfile`, `.env.example`, `app/core/config.py` ; 3007 dans `zylo-office-backend/CLAUDE.md` (l. 187), `zylo-office-frontend/README.md` (l. 32, 36), `src/core/api/client.ts`, les e2e, `docs/architecture/performance/phase-4-benchmark-results.md`.
- Reco : une seule table « Ports » (ex. `docs/process/local-setup.md`) ; aligner README et code sur la même valeur.

**DOC-003 — P2 — Ouvert — Ports frontend contradictoires**
- Preuves : `package.json` `dev`/`start` sur 3001 ; `README.md` l. 40 : 3006 ; `.env.local` : `PORT=3006` ; `.env.local.example` : `PORT=3001` ; `playwright.config.ts` commente « 3001/3006/3007 déjà utilisés ».
- Reco : même traitement que DOC-002 ; supprimer la valeur de README au profit de la table unique.

**DOC-004 — P1 — Ouvert — Cahiers métier hors versionnement**
- Preuves : `.gitignore` contient `taches/` (« jamais commité »). `git ls-files taches` = 0 fichier. Ce dossier contient pourtant les seules exigences terrain détaillées : 4 cahiers (1 474 à 1 648 lignes), `zone-declaration/plan.md`, 22 scénarios et `points-critiques.md`.
- Reco : sortir `taches/` du `.gitignore` et le versionner sous `docs/requirements/` (ou dans un dépôt privé dédié) ; sauvegarde hors machine en attendant.

**DOC-005 — P1 — Ouvert — `zylo_tanker` non documenté**
- Preuves : `app/modules/zylo_tanker/` existe ; `src/modules/zylo-tanker/` (screens consumption, dashboard, documents, localisation, pumps, supervision, tanks) ; route `src/app/zylo-tanker/` ; `.importlinter` le cite. `grep` sur ARCHITECTURE.md, CLAUDE.md (back et front), README (back et front), `docs/` : aucune occurrence.
- Reco : créer `docs/modules/zylo-tanker/README.md` (statut, périmètre, écrans) ; le mentionner dans les arborescences.

**DOC-006 — P2 — Ouvert — Trois arborescences backend divergentes**
- Preuves : `CLAUDE.md` (convention module), `ARCHITECTURE.md` §2 (omet `auth/`, `billing/`, `modules_registry/`, `notifications/`), `README.md` « Architecture » (omet `files/`, `location/`, `alerts/`, `integrations/`, `audit/`, `notifications/`). `app/` contient bien l'ensemble.
- Reco : une seule arborescence réelle dans `docs/architecture/packages.md` ; les README la référencent au lieu de la recopier.

**DOC-007 — P2 — Ouvert — Arborescence frontend de CLAUDE.md obsolète**
- Preuves : `zylo-office-frontend/CLAUDE.md` dit « arborescence réelle » mais omet `src/core/modules/`, `src/core/rbac/`, `src/core/notifications/`, et `zylo-tanker`. Il affirme « les 10 écrans non triviaux » déjà migrés, alors que `src/modules/zylo-liquid/screens/` compte 27 dossiers.
- Reco : régénérer l'arbre ; retirer le chiffre (« tous les écrans suivent ce patron »).

**DOC-008 — P2 — Ouvert — Règle « page = 1 ligne » non respectée**
- Preuves : `src/app/CLAUDE.md` impose « un fichier page.tsx ne contient pas de logique ». Sept pages `src/app/zylo-liquid/` font 8 à 10 lignes avec `"use client"` et `useTranslations` (ex. `utilisateurs/page.tsx`, `audit/`, `securite/`, `sante/`, `parametres/`, `hypotheses/`, `journal-audit/`).
- Reco : soit extraire un composant `ComingSoon` de route dans le module et réduire la page à une ligne, soit assouplir la règle par écrit (« 1 ligne ou placeholder partagé »).

**DOC-009 — P2 — Ouvert — Index docs/README.md incomplet**
- Preuves : `docs/README.md` se dit « index … toujours à jour » mais ne référence pas `docs/architecture/performance/` (17 fichiers), ni `ARCHITECTURE.md`, `phase_1_database.md`, `validation_log.md`, `taches/`. Il liste `phase-3-frontend.md` comme « à créer » (non créé) et cite `instruction_2_base_donnees_phase_1.md` (absent du dépôt).
- Reco : régénérer l'index à partir de l'arborescence cible (voir ci-dessous) ; retirer les entrées « à créer ».

**DOC-010 — P2 — Ouvert — Doublon phase 1 base de données**
- Preuves : `phase_1_database.md` (racine, 253 lignes, 18 Ko) et `docs/modules/zylo-liquid/phase-1-database.md` (30 lignes, résumé). `docs/README.md` assume le doublon « pour respecter le nom de livrable ».
- Reco : un seul document de référence sous `docs/modules/zylo-liquid/database/` ; le livrable historique devient un lien dans `docs/archive/`.

**DOC-011 — P2 — Ouvert — Gros fichiers de doc à découper**
- Preuves (lignes) : `docs/modules/zylo-liquid/phase-2-api.md` 907 (16 endpoints, décisions, 16 « Rapport final ») ; `validation_log.md` 598 (33 Ko, racine, niveaux 1 à 3 + suivi) ; `phase_1_database.md` 253 (18 Ko) ; cahiers `taches/*.md` 1 474 à 1 648 ; `docs/architecture/performance/observability-implementation.md` 199.
- Reco : un fichier par domaine d'API (`api/fuel-products.md`, `api/stations.md`, `api/tanks.md`…) ; `validation/niveau-1-algorithmes.md`, `niveau-2-endpoints.md`, `niveau-3-flux.md` ; cahiers découpés par responsabilité (voir DOC-012).

**DOC-012 — P2 — Ouvert — Cahiers métier : copies, répétitions, statut périmé**
- Preuves : noms `Cahier_Chef_d_Equipe_… (1).md` et `Cahier_Responsable_de_Tour_… (2).md` (suffixes de téléchargement). Chaque cahier répète le même bloc d'en-tête (entreprise, station, méthode). Le cahier responsable de tour et le cahier chef d'équipe disent « documents séparés à venir pour le chef d'équipe / le pompiste », alors que ces fichiers existent.
- Reco : renommer sans suffixe ; factoriser l'en-tête commun dans `requirements/station/README.md` ; mettre à jour les statuts.

**DOC-013 — P2 — Ouvert — Journaux de livraison mélangés à la doc de référence**
- Preuves : `phase-2-api.md` contient 16 sections « Rapport final — Endpoint N » ; `phase_1_database.md` contient « Rapport final (§23 de l'instruction) » ; `ARCHITECTURE.md` §5 contient des notes datées (« Note Phase 4 (2026-09-16) »).
- Reco : déplacer les rapports de livraison dans `docs/archive/` ; ne garder dans la doc de référence que l'état courant.

**DOC-014 — P2 — Ouvert — Références à des documents absents du dépôt**
- Preuves : `CLAUDE.md`, `README.md`, `ARCHITECTURE.md` citent `grande_phases.md` (présent seulement à `projet en cours/zylo-office/grande_phases.md`, hors dépôt), `plan-migration/architecture-migration.md` (dans `zylo_liquid_prototype`), `instruction_2_base_donnees_phase_1.md`, `instruction.md`, « Point 3 — Définir la procédure… ». Aucun de ces chemins n'existe dans les dépôts.
- Reco : copier les extraits utiles dans `docs/requirements/` (avec date et source) ; pour le reste, écrire le chemin absolu et la mention « hors dépôt ».

**DOC-015 — P2 — Ouvert — Fichiers parasites et dump suivis par git**
- Preuves : backend : `teste.html` (0 octet), `test.txt` (1 octet), `backups/zylo_office_20260831_180729.sql.gz` suivi alors que `backups/` est dans `.gitignore`. Frontend : `test.txt` (14 octets) suivi.
- Reco : `git rm` des fichiers vides ; sortir le dump de l'historique (il contient des données) et le garder hors dépôt.

**DOC-016 — P2 — Ouvert — Deux sources de design system en conflit (frontend)**
- Preuves : `docs/frontend-foundations.md` (§8 « Conflits détectés ») et `docs/design-system-zylo-liquid-reference-analysis.md` (§A.1 : valeurs « partiellement différentes » de la palette). Le second se déclare « analyse uniquement, aucune implémentation » sans statut de décision.
- Reco : un seul design system de référence ; l'analyse passe en `docs/archive/` ou reçoit un statut « décidé / rejeté » par écart.

**DOC-017 — P3 — Ouvert — Gabarit Storybook contraire à la règle CSS**
- Preuves : `zylo-office-frontend/src/stories/` contient `Configure.mdx` (446 lignes), `header.css`, `button.css`, `page.css` (gabarit Storybook). `CLAUDE.md` frontend : « Aucun nouveau fichier CSS local ».
- Reco : supprimer le gabarit (ou l'exclure explicitement de la règle).

**DOC-018 — P2 — Ouvert — Stratégie Git documentée ≠ pratique**
- Preuves : README backend et frontend, `CLAUDE.md` : « main → develop → remy », « une tâche = une issue + une branche ». Réalité : branche de travail `remy` ; `develop` existe ; de nombreuses branches locales `endpoint-N-…`, `docs-phase-3-…` ; CI déclenchée sur `main` et `remy` seulement. `ARCHITECTURE.md` §5 : « un commit par phase », mais les phases 1 et 2 sont dans un seul commit (`8020c61`).
- Reco : documenter le workflow réel dans `docs/process/git-workflow.md`, puis aligner les README sur ce texte.

**DOC-019 — P2 — Ouvert — Arbres de travail très sales (tâche)**
- Preuves : `git status` : 54 fichiers modifiés (backend) et 229 (frontend) non commités, au 2026-10-08.
- Reco : ouvrir une issue « trier et committer le travail en cours » ; découper par sujet (une issue = une branche).

**DOC-020 — P2 — Ouvert — Issues GitHub quasi vides, labels par défaut (tâche)**
- Preuves (`gh`, lecture seule) : backend : 1 issue ouverte (#55, « App Launcher ») et 0 PR ; frontend : 0 issue et 0 PR. Labels : seulement les labels GitHub par défaut (`documentation`, `bug`, `enhancement`…). Aucun label par module ni par priorité.
- Reco : créer les labels `module:zylo-liquid`, `module:zylo-tanker`, `area:docs`, `priority:P1`, `priority:P2` ; ouvrir une issue par item P1 de ce rapport.

**DOC-021 — P1 — Ouvert — Exigences organisations / utilisateurs / modules (tâche)**
- Preuves : sources hors dépôt : `projet en cours/zylo-office/grande_phases.md` (679 lignes : §8 Organisation → User → Role → Permission, §9 modules activables, PHASE 6) et `projet en cours/zylo/audit/03_besoins_cibles.md` (sections « Utilisateurs », « Organisation », « Permissions »). Côté code (inventaire) : pas de route de création d'utilisateur par le propriétaire ; pas de concept d'affectation utilisateur à un module ; aucun test E2E sur utilisateurs ni rôles (`e2e/` ne contient que `proprietaire-02` et `-04` pour organisation/modules).
- Reco : créer `docs/requirements/socle-organisations-utilisateurs-modules.md` (extraits de grande_phases §6-9 et besoins 03, sourcés) ; issues « création utilisateur », « affectation module », « e2e utilisateurs/rôles ».

**DOC-022 — P2 — Ouvert — validation_log.md figé au 1er septembre**
- Preuves : dernier commit touchant `validation_log.md` : 2026-09-01 (endpoint 16). Des commits de fonctionnalités suivent (ex. `eabf517`, 2026-09-20, alertes `manual_gauging_discrepancy`) sans entrée de validation.
- Reco : ajouter une date et un commit par ligne de validation ; signaler « non validé » pour les nouveautés.

**DOC-023 — P3 — Ouvert — docs/architecture/performance à plat et mélangé**
- Preuves : 17 fichiers dans un dossier ; 4 numérotés par phase (`phase-1-audit`, `phase-2-architecture-decision`, `phase-3-implementation`, `phase-4-benchmark-results`), 13 par thème ; `README.md` du dossier non référencé par l'index racine (DOC-009).
- Reco : regrouper par thème (`cache/`, `api/`, `database/`, `observability/`) ; ranger les phases dans `archive/`.

**DOC-024 — P3 — Ouvert — Nommage incohérent**
- Preuves : `docs/core/phase12-offline-readiness-audit.md` au lieu de `phase-12-…` (convention de `docs/README.md`) ; `docs/core/app-launcher-endpoints.md` sans lien avec une phase.
- Reco : appliquer la convention ou renommer selon le sujet.

**DOC-025 — P3 — Ouvert — Environnements et stack non documentés**
- Preuves : `app/core/database.py` et `docs/architecture/performance/phase-1-audit.md` mentionnent Neon ; README et CLAUDE.md ne décrivent que PostgreSQL local. Le Dockerfile cite `backend.zylooffice.com` (3004).
- Reco : un tableau « environnements » (local, recette, prod) dans `docs/process/local-setup.md`.

## Points vérifiés et conformes

- Les 10 contrats `import-linter` annoncés (ARCHITECTURE §7) correspondent aux 10 blocs de `.importlinter`.
- Les 5 commits cités dans ARCHITECTURE §5 (`8020c61`, `74e772c`, `a78ca84`, `fb648e0`, `f3d5819`) existent.
- `alembic/versions/` contient 68 migrations (le nombre n'est cité nulle part en doc, donc rien à corriger).
- Convention de nommage des tables et permissions bien décrite et appliquée (non audité en détail).

## Proposition d'arborescence cible `docs/`

```text
zylo-office-backend/docs/
├── README.md                    index unique, généré depuis l'arbre
├── architecture/
│   ├── README.md                résumé des règles (renvoie à CLAUDE.md)
│   ├── packages.md              arbre réel de app/ (source unique)
│   ├── import-contracts.md      les 10 contrats importlinter
│   ├── migration-status.md      phases 0-6 + commits
│   └── performance/             par thème : cache/ api/ database/ observability/
├── core/                        identity, rbac, modules-registry, billing, offline
├── modules/
│   ├── zylo-liquid/
│   │   ├── README.md
│   │   ├── database/            un fichier par domaine de tables
│   │   ├── api/                 un fichier par domaine d'API
│   │   ├── validation/          niveau-1, -2, -3 (+ suivi)
│   │   └── compatibility-matrix.md
│   └── zylo-tanker/README.md    à créer (DOC-005)
├── requirements/
│   ├── socle-organisations-utilisateurs-modules.md   (DOC-021)
│   ├── station/                 gerant, responsable-de-tour, chef-d-equipe, pompiste
│   └── zone-declaration/        plan, scenarios/, points-critiques.md
├── process/
│   ├── git-workflow.md          workflow réel (DOC-018)
│   ├── local-setup.md           ports, env, venv (DOC-002/003/025)
│   └── ci.md                    état CI (DOC-001)
└── archive/                     rapports de livraison, phases closes, anciens livrables
```

## Réponse de l'auditeur

Aucune modification de code ni de doc hors de ce fichier. Aucun commit, aucune issue ou label créé.
