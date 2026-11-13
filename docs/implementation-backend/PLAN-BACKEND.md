# Plan backend ZYLO-OFFICE (BE-CONS-B)

## a) Statut

- Date : 2026-11-13. Statut : **figé pour déploiement** (gel ebc7ad0, voir ETAT-GEL-2026-11-13.md et SUIVI.md, section « Audit du 2026-11-13 »).
- Phases PH-00 à PH-17 : VALIDÉES (décision du propriétaire, 2026-11-03). Les statuts DRAFT et BLOCKED des phases sont ignorés.
- Périmètre : back-end uniquement. Casser l'existant est permis lorsque la nouvelle architecture l'exige.
- Documentation explicite exigée : docstrings dans le code, README de chaque module.

## b) Vue d'ensemble

- 245 tâches définies (BE-261 fusionnée dans BE-024), réparties en 9 domaines.
- Avancement au 2026-11-13 : 230 fusionnées, 15 restantes. Parmi les restantes : 5 prêtes (BE-112, BE-197, BE-199, BE-205, BE-206), 1 bloquée par décision (BE-137, QE-ADM-22), 9 bloquées par prérequis (BE-111, 113, 114, 115, 119, 207, 208, 209, 263). Détail par domaine : SUIVI.md, section « Audit du 2026-11-13 ».
- Un fichier `tasks-*.md` par domaine, dans ce dossier.
- Dépendances : 0 cycle, 0 prérequis absent (vérification du 2026-11-03).

| Domaine | Fichier | Tâches |
|---|---|---|
| Socle tenant et identité | tasks-socle-tenant-identite.md | 39 |
| Modules, catalogue, droits | tasks-modules-droits.md | 22 |
| Portail client et organisation | tasks-portail-organisation.md | 20 |
| Abonnements, facturation, paiements | tasks-abonnements-facturation.md | 30 |
| Paramètres, notifications, audit | tasks-parametres-notifications-audit.md | 27 |
| Administration et interventions | tasks-administration-interventions.md | 28 |
| Données, API, contrats | tasks-donnees-api-contrats.md | 36 |
| Exploitation et architecture | tasks-exploitation-architecture.md | 40 |
| Fondation (recensement) | tasks-fondation-recensement.md | 3 (plus BE-261, fusionnée dans BE-024) |
| Total | | 245 |

## c) Décisions de l'étape A

Recommandations appliquées, réponses différées (voir POINTS-OUVERTS.md, section « Décisions de l'étape A »).

- D1 : enveloppe d'erreur `{"error": {...}}` portée par BE-001 (clés `request_id` et `field_errors` du code).
- D2 : table unique `audit_event`, propriétaire BE-007.
- D3 : table `subscription_entitlement`, propriétaire BE-024, BE-261 fusionnée.
- D4 : dépendances auth, tenant et RBAC explicites (BE-150, BE-180, BE-260).
- D5 : BE-120 hors vague 1.
- D6 : routes `/api/v1` et `/api/v1/admin`, mot `organizations`, doublons /auth/login (BE-005) et portal-summary (BE-109).
- D7 : chemins `app/<capacité>/`.
- D8 : ligne « Code existant (develop) » pour les tâches des vagues 1 et 2.

Compléments :

- Convention camelCase pour les colonnes, reprise du code develop. Elle s'applique aux 9 fichiers de tâches, pas au code.
- Noms de tables `audit_event` et `subscription_entitlement` gardés ; la question de casse reste ouverte.

## d) Tableau des vagues

Source : DEPENDANCES.md, section « Vagues ». Vague 1 = aucune dépendance ; vague n = 1 + max des vagues des prérequis.

Règle : toutes les tâches d'une vague sont lançables quand les vagues précédentes sont terminées. Aucune tâche d'une vague n'attend une autre tâche de la même vague.

| Vague | Nombre | Identifiants |
|---|---|---|
| 1 | 2 | BE-001, BE-221 |
| 2 | 6 | BE-002, BE-003, BE-032, BE-070, BE-220, BE-223 |
| 3 | 13 | BE-004, BE-005, BE-007, BE-021, BE-023, BE-040, BE-072, BE-222, BE-224, BE-232, BE-233, BE-242, BE-256 |
| 4 | 14 | BE-006, BE-008, BE-018, BE-019, BE-020, BE-024, BE-030, BE-034, BE-041, BE-071, BE-225, BE-230, BE-240, BE-249 |
| 5 | 11 | BE-009, BE-042, BE-045, BE-056, BE-073, BE-075, BE-079, BE-226, BE-231, BE-241, BE-250 |
| 6 | 28 | BE-010, BE-012, BE-014, BE-016, BE-022, BE-026, BE-027, BE-033, BE-035, BE-036, BE-043, BE-044, BE-046, BE-055, BE-076, BE-078, BE-090, BE-120, BE-150, BE-180, BE-227, BE-244, BE-248, BE-251, BE-253, BE-254, BE-255, BE-260 |
| 7 | 25 | BE-011, BE-013, BE-015, BE-025, BE-028, BE-031, BE-037, BE-047, BE-077, BE-080, BE-086, BE-088, BE-122, BE-127, BE-151, BE-152, BE-181, BE-191, BE-228, BE-234, BE-237, BE-243, BE-245, BE-247, BE-262 |
| 8 | 18 | BE-017, BE-029, BE-048, BE-051, BE-052, BE-074, BE-081, BE-087, BE-098, BE-121, BE-147, BE-153, BE-182, BE-229, BE-235, BE-236, BE-246, BE-257 |
| 9 | 19 | BE-038, BE-049, BE-050, BE-053, BE-082, BE-123, BE-146, BE-154, BE-160, BE-166, BE-172, BE-183, BE-184, BE-185, BE-187, BE-238, BE-239, BE-252, BE-258 |
| 10 | 21 | BE-039, BE-054, BE-057, BE-058, BE-059, BE-093, BE-099, BE-124, BE-132, BE-142, BE-155, BE-161, BE-164, BE-167, BE-173, BE-174, BE-175, BE-186, BE-188, BE-192, BE-259 |
| 11 | 13 | BE-060, BE-100, BE-125, BE-128, BE-133, BE-144, BE-145, BE-156, BE-162, BE-165, BE-168, BE-189, BE-193 |
| 12 | 10 | BE-061, BE-101, BE-126, BE-129, BE-136, BE-138, BE-157, BE-163, BE-169, BE-190 |
| 13 | 19 | BE-083, BE-102, BE-105, BE-107, BE-108, BE-116, BE-118, BE-130, BE-131, BE-134, BE-135, BE-139, BE-141, BE-143, BE-158, BE-170, BE-194, BE-210, BE-213 |
| 14 | 12 | BE-084, BE-094, BE-095, BE-103, BE-104, BE-106, BE-159, BE-171, BE-176, BE-195, BE-200, BE-211 |
| 15 | 9 | BE-085, BE-089, BE-109, BE-117, BE-140, BE-196, BE-202, BE-212, BE-215 |
| 16 | 7 | BE-091, BE-097, BE-110, BE-197, BE-198, BE-199, BE-201 |
| 17 | 3 | BE-092, BE-096, BE-203 |
| 18 | 2 | BE-112, BE-204 |
| 19 | 3 | BE-205, BE-206, BE-214 |
| 20 | 7 | BE-111, BE-113, BE-137, BE-207, BE-208, BE-209, BE-263 |
| 21 | 2 | BE-114, BE-119 |
| 22 | 1 | BE-115 |
| Total | 245 | |

## e) Renvois

- CARTE-ROUTES.md : 297 routes déclarées, par domaine, avec droits requis.
- DEPENDANCES.md : tableau identifiant, prérequis, dépendants directs ; vagues ; points ouverts QE-CONS.
- POINTS-OUVERTS.md : décisions de l'étape A, questions QE par domaine, anomalies à trancher.
- tasks-*.md : 9 fichiers, un par domaine, avec tâches, dépendances, vagues et points ouverts.

## f) Anomalies connues à trancher

Détail et recommandations dans POINTS-OUVERTS.md, section « Anomalies connues à trancher ».

- Dépendances « EXT » déclarées mais absentes de BE-061, BE-176, BE-215 et BE-259 (correcteurs : « Dépendances externes : aucune »).
- Routes operator/internal hors `/api/v1/admin` (16 routes selon CARTE-ROUTES.md).
- Doublons de routes : GET /api/v1/auth/me et POST /api/v1/auth/refresh (BE-005 et BE-188), GET /api/v1/notifications (BE-171 et BE-238), GET /api/v1/notifications/preferences (BE-168 et BE-238), PATCH /api/v1/organizations/{organization_id} (BE-104 et BE-186). BE-238 déclare aussi PATCH /api/v1/notifications/{id} et PUT /api/v1/notifications/preferences, à trancher.
- BE-176 dépend de tâches de vagues supérieures.
- Casse des tables `audit_event` et `subscription_entitlement` : question ouverte (convention camelCase du backend).
- BE-209 : commits `feat` et `test` présents sur develop (654d379, b221cd2) sans fusion tracée, alors que son prérequis BE-206 n'est pas fusionné (QE-SUI-05).
- BE-197 : code sur la branche `be-197-lot` uniquement, non fusionné ; routes HTTP à trancher (QE-BE-197-ROUTES).
- BE-261 : section résiduelle dans `tasks-fondation-recensement.md`, à retirer ; BE-279 cité à tort (QE-SUI-07).
- Fusions tracées dans git mais absentes des lignes de SUIVI.md : BE-196, BE-198, BE-201, BE-203, BE-204, BE-214 (QE-SUI-04).
