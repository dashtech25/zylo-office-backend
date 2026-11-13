# Issues à créer (une par tâche, générées depuis les fiches)

Labels : `priority:Px`, `wave:N`, `area:<domaine>`, `type:<type>`, `repo:<backend|frontend>`. Généré par `scripts/docs/check_plan.py --generer` : ne pas éditer à la main.

| ID | Titre d'issue | Labels |
|---|---|---|
| T-001 | [T-001] Retirer le dump de l'index git et verrouiller les dumps | priority:P0, wave:0, area:security, type:security, repo:backend |
| T-002 | [T-002] Refuser le démarrage hors développement avec des secrets par défaut | priority:P0, wave:0, area:security, type:security, repo:backend |
| T-003 | [T-003] Table de ports unique, allocation par worktree, CORS configurable | priority:P1, wave:0, area:docs, type:chore, repo:backend, repo:frontend |
| T-004 | [T-004] Base de référence et espace de travail isolé | priority:P0, wave:0, area:process, type:chore, repo:backend, repo:frontend |
| T-004b | [T-004b] Tri du travail en cours restant (lots non bloquants) | priority:P1, wave:0, area:process, type:chore, repo:backend, repo:frontend |
| T-005 | [T-005] Environnement de test isolé par tâche et garde de base | priority:P1, wave:0, area:ci, type:chore, repo:backend, repo:frontend |
| T-006 | [T-006] Corriger les 21 tests pytest en échec (payloads et cascades) | priority:P1, wave:1, area:zylo-liquid, type:test, repo:backend |
| T-007 | [T-007] Droit du rôle manager (décision client, aucun élargissement automatique) | priority:P2, wave:1, area:iam, type:test, repo:backend |
| T-008 | [T-008] Playwright sur build de production, e2e versionnés, jetons exclus | priority:P1, wave:1, area:frontend, type:test, repo:backend, repo:frontend |
| T-009 | [T-009] Corriger les 10 scénarios Playwright en échec | priority:P1, wave:1, area:zylo-liquid, type:test, repo:backend, repo:frontend |
| T-010 | [T-010] Isolation inter-organisations (IDOR) sur les 13 routes et sur toutes les routes d'organisation | priority:P0, wave:1, area:iam, type:security, repo:backend |
| T-011 | [T-011] Hygiène frontend (ui-preview, fichiers parasites, route en doublon) | priority:P3, wave:1, area:frontend, type:chore, repo:frontend |
| T-012 | [T-012] Limitation de débit et verrouillage progressif de l'authentification | priority:P1, wave:1, area:security, type:security, repo:backend |
| T-013 | [T-013] Politique de mot de passe et réponses neutres, sans annoncer d'envoi inexistant | priority:P1, wave:1, area:security, type:security, repo:backend, repo:frontend |
| T-014 | [T-014] Uploads sécurisés (liste blanche, lecture bornée, téléchargement forcé) | priority:P1, wave:1, area:security, type:security, repo:backend |
| T-015 | [T-015] Dépendances CVE, OpenAPI désactivé hors développement, CORS restreint | priority:P1, wave:1, area:security, type:security, repo:backend |
| T-016 | [T-016] Process git, labels et exigences versionnées, script de contrôle du plan | priority:P2, wave:1, area:docs, type:docs, repo:backend, repo:frontend |
| T-017 | [T-017] Refonte de la documentation backend en arborescence de petits fichiers | priority:P2, wave:2, area:docs, type:docs, repo:backend |
| T-018 | [T-018] Rôles et permissions par module, un seul mécanisme (Role.moduleCode nullable) | priority:P1, wave:2, area:iam, type:feature, repo:backend |
| T-019 | [T-019] Garde-fous IAM (dernier propriétaire, appartenance, deny, plans, soft-delete) | priority:P1, wave:2, area:iam, type:security, repo:backend |
| T-020 | [T-020] Sessions, révocation et réutilisation des refresh tokens | priority:P2, wave:2, area:security, type:security, repo:backend |
| T-021 | [T-021] Création d'utilisateurs par le propriétaire (API), compte en attente sans mot de passe connu du créateur | priority:P1, wave:2, area:iam, type:feature, repo:backend |
| T-022 | [T-022] Affecter un utilisateur à un module avec ses droits propres (API) | priority:P1, wave:3, area:iam, type:feature, repo:backend |
| T-023 | [T-023] Matrice d'autorisation et inventaire des routes protégées | priority:P2, wave:2, area:iam, type:test, repo:backend |
| T-024 | [T-024] Frontend : création d'utilisateurs par l'administrateur d'organisation | priority:P1, wave:3, area:iam, type:feature, repo:frontend |
| T-025 | [T-025] Frontend : affecter un utilisateur à un module et aligner la permission affichée | priority:P1, wave:3, area:iam, type:feature, repo:frontend |
| T-026 | [T-026] Parcours E2E Playwright : organisation, utilisateur, affectation à un module | priority:P1, wave:3, area:iam, type:test, repo:backend, repo:frontend |
| T-027 | [T-027] Chiffrer le mot de passe du compte Holykell, avec clé de secours et procédure de restauration | priority:P1, wave:1, area:zylo-liquid, type:security, repo:backend |
| T-028 | [T-028] Sortir migrations et seeds du démarrage, avec runbook de sauvegarde et de retour arrière | priority:P1, wave:1, area:ci, type:refactor, repo:backend |
| T-029 | [T-029] Fiabilité des tâches de fond (verrou) et des exceptions avalées | priority:P2, wave:1, area:backend, type:refactor, repo:backend |
| T-030 | [T-030] Frontend : une seule coquille de navigation (ModuleShell et CoreProviders) | priority:P1, wave:2, area:frontend, type:refactor, repo:frontend |
| T-031 | [T-031] Frontend : un seul fil d'Ariane et des pages de délégation | priority:P1, wave:2, area:frontend, type:refactor, repo:frontend |
| T-032 | [T-032] Frontend : tokens visuels uniques, sans référence circulaire, suppression de prototype.css | priority:P1, wave:2, area:frontend, type:refactor, repo:frontend |
| T-033a | [T-033a] Frontend : composants partagés (Table, Tabs, Modal, QueryState, graphiques) | priority:P2, wave:3, area:frontend, type:refactor, repo:frontend |
| T-033b | [T-033b] Frontend : appels réseau par le client unique et états d'erreur des widgets | priority:P2, wave:3, area:frontend, type:refactor, repo:frontend |
| T-033c | [T-033c] Frontend : accessibilité des éléments interactifs et des overlays | priority:P2, wave:3, area:frontend, type:refactor, repo:frontend |
| T-034 | [T-034] Découpe de zylo_liquid/service.py, lot 1 (filet de caractérisation, stations et cuves) | priority:P1, wave:1, area:zylo-liquid, type:refactor, repo:backend |
| T-035a | [T-035a] Découpe de zylo_liquid/service.py, lot a (caisse et shifts) | priority:P2, wave:2, area:zylo-liquid, type:refactor, repo:backend |
| T-035b | [T-035b] Découpe de zylo_liquid/service.py, lot b (livraisons et rapprochements) | priority:P2, wave:2, area:zylo-liquid, type:refactor, repo:backend |
| T-035c | [T-035c] Découpe de zylo_liquid/service.py, lot c (réglementation et déclarations) | priority:P2, wave:2, area:zylo-liquid, type:refactor, repo:backend |
| T-035d | [T-035d] Découpe de zylo_liquid/service.py, lot d (ventes et produits) | priority:P2, wave:2, area:zylo-liquid, type:refactor, repo:backend |
| T-035e | [T-035e] Découpe de zylo_liquid/service.py, lot e (reste) et seuil de taille | priority:P2, wave:2, area:zylo-liquid, type:refactor, repo:backend |
| T-036 | [T-036] Contrats import-linter complets et découplage du socle | priority:P1, wave:2, area:socle, type:refactor, repo:backend |
| T-037a | [T-037a] Jetons dans des cookies HttpOnly, partie backend | priority:P1, wave:2, area:security, type:security, repo:backend |
| T-037b | [T-037b] Jetons dans des cookies HttpOnly, partie frontend | priority:P1, wave:3, area:security, type:security, repo:frontend |
| T-038a | [T-038a] CI bloquante minimale dès la vague 1 | priority:P1, wave:1, area:ci, type:ci, repo:backend, repo:frontend |
| T-038b | [T-038b] CI complète (lint, contrats d'architecture, Playwright sur build prod) | priority:P1, wave:2, area:ci, type:ci, repo:backend, repo:frontend |
| T-039 | [T-039] Documentation frontend en arborescence, design system de référence unique, arbre généré | priority:P2, wave:3, area:docs, type:docs, repo:frontend |
| T-040 | [T-040] Agents et règles Claude Code : CLAUDE.md court, règles par zone, gabarit d'agent d'exécution | priority:P2, wave:3, area:docs, type:docs, repo:backend, repo:frontend |
| T-041 | [T-041] Retrait de Storybook (branche chore/retirer-storybook) et smoke Playwright sur build prod | priority:P1, wave:0, area:frontend, type:chore, repo:frontend |
| T-042 | [T-042] Mise en place minimale de Vitest, sans Storybook, pour la logique pure | priority:P1, wave:0, area:frontend, type:test, repo:frontend |
| T-043 | [T-043] Catalogue de composants dans docs/ (un fichier par composant partagé) | priority:P1, wave:0, area:docs, type:docs, repo:frontend |
| T-046 | [T-046] Fixtures e2e isolées par spec (une organisation et une station par test) | priority:P1, wave:1, area:frontend, type:test, repo:frontend |
| T-047 | [T-047] Tests d'accès interdit et inter-organisations (API et e2e) | priority:P1, wave:3, area:iam, type:test, repo:backend, repo:frontend |
| T-048 | [T-048] Cycle de vie utilisateur : désactivation, retrait de l'organisation, retrait d'un module | priority:P1, wave:3, area:iam, type:feature, repo:backend |
| T-049 | [T-049] Activation de compte par lien à usage unique (mot de passe choisi par le titulaire) | priority:P1, wave:3, area:iam, type:security, repo:backend, repo:frontend |
| T-050 | [T-050] Permission plateforme explicite, et catalogue de plans administré hors API | priority:P2, wave:2, area:iam, type:security, repo:backend |
| T-051 | [T-051] Conteneur non root, routeur monté une fois, routes de démonstration supprimées | priority:P1, wave:1, area:security, type:chore, repo:backend |
