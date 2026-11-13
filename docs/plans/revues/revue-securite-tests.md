# Revue critique indépendante : sécurité, rôles, données, tests

- **Date** : 2026-10-08
- **Objet** : `docs/plans/PLAN_REMISE_SUR_PIED.md`, `REGISTRE_TACHES.md`, fiches `taches/T-001` à `T-040`, audits `docs/audit/` (backend et frontend)
- **Méthode** : lecture seule. Relecture du plan, des fiches et des audits, puis vérification dans le code (`git ls-files`, `git check-ignore`, `git worktree list`, lecture de `app/core/config.py`, `app/main.py`, `app/rbac/service.py`, `app/core/security.py`, `app/shared/storage_router.py`, `Dockerfile`, `tests/conftest.py`, `.github/workflows/ci.yml.disabled`, `next.config.ts`).
- **Non vérifié** : aucune commande pytest ou Playwright lancée, aucune base touchée, aucun accès réseau (visibilité réelle du dépôt GitHub `dashtech25/zylo-office-backend` non contrôlée), aucun contenu de secret lu ni recopié.

## Synthèse

| Sévérité | Nombre | Identifiants |
|---|---|---|
| Critique | 2 | REV-S-01, REV-S-02 |
| Haute | 10 | REV-S-03 à REV-S-09, REV-S-14, REV-S-15, REV-S-16 |
| Moyenne | 10 | REV-S-10, REV-S-11, REV-S-12, REV-S-13, REV-S-17 à REV-S-22 |
| Basse | 3 | REV-S-23 à REV-S-25 |

Le plan est bien construit sur le fond (IDOR, dump, secrets, RBAC par module), mais plusieurs garde-fous qu'il annonce ne sont pas dans les critères d'acceptation, ou sont contredits par le code ou par d'autres fiches. Les trois points à traiter avant toute exécution sont REV-S-01 (dump et rotation), REV-S-02 (fail-closed réellement absent) et REV-S-05 (élévation de privilèges automatique au démarrage).

---

## Constats

### REV-S-01 : purge du dump et rotation des identifiants non exigées (Critique)

- **Tâches** : T-001, T-027, T-015 (BCK-010), décision `securite/purge-historique-dump.md`, `rotation-credentials.md`
- **Preuve** : `git ls-files backups` renvoie `backups/zylo_office_20260831_180729.sql.gz`, suivi depuis le commit `8aea496`. `git log --all -- backups` le confirme. `origin` pointe sur GitHub. Le plan §7 dit que la question de purge « doit exister avant T-001 fusionnée », alors que T-001 est censée la créer.
- **Constat** : les critères d'acceptation de T-001 demandent seulement que le dump soit retiré de l'index et que deux fichiers de question existent. Ils n'exigent ni la rotation effective, ni le résultat du contrôle de visibilité, ni la décision sur la réécriture. La rotation est attribuée à « l'opérateur, hors dépôt » (T-027) sans propriétaire ni échéance. Retirer le fichier de l'index ne supprime pas la fuite si le dépôt est public ou partagé.
- **Correction** : ajouter aux critères de T-001 (1) la visibilité du dépôt consignée (public ou privé, date, méthode), (2) la liste des identifiants à faire tourner (mot de passe de base `zylo_office`, compte Holykell, mot de passe de démo de `scripts/bootstrap_demo_org.py`) avec propriétaire et date de rotation attestée avant la fusion de T-001, (3) la décision sur `git filter-repo` tranchée par écrit, en dehors de l'agent. Corriger §7 : la question est créée par T-001 elle-même.

### REV-S-02 : fail-closed annoncé mais non implémenté par le défaut (Critique)

- **Tâches** : T-002, T-027, T-015
- **Preuve** : `app/core/config.py:8` : `ENVIRONMENT: str = "development"`. Le `Dockerfile` ne définit pas `ENVIRONMENT` (seulement `PORT=3002` et `PYTHONDONTWRITEBYTECODE`).
- **Constat** : T-002 écrit « toute autre valeur (y compris absente) applique les règles strictes ». Or si la variable est absente, Pydantic applique le défaut `development`, qui autorise les secrets de repli. Une image lancée sans `ENVIRONMENT` démarre donc avec `changeme` comme secret JWT. La garde proposée ne protège pas le cas qu'elle vise.
- **Correction** : dans T-002, supprimer le défaut de `ENVIRONMENT` (champ obligatoire, ou défaut `production`), ajouter `ENV ENVIRONMENT=production` au `Dockerfile`, et ajouter un test « variable absente + secret de repli = démarrage refusé ». Ajouter à T-002 la clé de chiffrement de T-027 (voir REV-S-09).

### REV-S-03 : identifiants de développement littéraux suivis par git (Haute)

- **Tâches** : T-015, T-038, T-001 (non listé dans les audits)
- **Preuve** : `tests/conftest.py` (suivi) contient un mot de passe de base de développement littéral dans la chaîne par défaut de `TEST_DATABASE_URL`. Le même littéral est dans `.github/workflows/ci.yml.disabled` (suivi), qui le passe à `DATABASE_URL` et `TEST_DATABASE_URL`. `app/modules/zylo_liquid/dev_seed.py` et `scripts/` (copiés dans l'image par le `Dockerfile`) contiennent aussi des valeurs de démo. Ces emplacements ne figurent pas dans BCK-010, ni dans T-015.
- **Constat** : T-038 réactive la CI en l'état, donc avec ce littéral. Le défaut de `DATABASE_URL` dans `config.py` contient aussi `changeme`.
- **Correction** : ajouter à T-015 le recensement complet des littéraux (`git grep`), leur remplacement par des variables d'environnement, et la rotation si le même mot de passe sert ailleurs. Dans T-038, les secrets de CI passent par les secrets GitHub, pas par le fichier de workflow.

### REV-S-04 : périmètre de l'IDOR réduit aux 13 routes, alors que le contrôle de l'en-tête est faible partout (Haute)

- **Tâches** : T-010, T-023, T-036
- **Preuve** : `app/rbac/service.py:17-23` : `get_current_organization_id` renvoie l'en-tête `X-Organization-Id` sans vérifier l'appartenance. `require_permission` (l.183-201) ne compare qu'à l'en-tête. `user_has_permission` ne lit que `UserRole` et les grants, pas `OrganizationUser`.
- **Constat** : l'objectif de T-010 dit que l'en-tête « est validé contre une appartenance active », mais la stratégie et les fichiers ne traitent que les routes à `{organization_id}`. Les centaines de routes sans chemin (zylo_liquid, zylo_tanker, files, shared) reposent toujours sur un en-tête non contrôlé. Le critère « Aucune route `{organization_id}` sans dépendance » est vérifié par T-023, postérieure à T-010.
- **Correction** : déplacer la validation d'appartenance dans `get_current_organization_id` (donc toutes les routes), avec tests sur des routes sans chemin. Ajouter à T-010 les tests de non-régression sur les routes zylo_liquid. Ajouter T-008 aux dépendances de T-010, car son critère « Playwright sur `e2e/proprietaire-02` et `-04` sur build prod » n'est pas satisfaisable sans lui (le registre ne le liste pas).

### REV-S-05 : élévation de privilèges automatique dans toutes les organisations (Haute)

- **Tâches** : T-007, T-018, T-026
- **Preuve** : `app/main.py` `on_startup` appelle `backfill_default_role_permissions`, `backfill_active_module_permissions_for_owners` et `backfill_owner_default_permissions` à chaque démarrage. T-007 écrit « Vérifier qu'une organisation existante reçoit la permission par le backfill ».
- **Constat** : T-007 tranche elle-même, en « avançant sur la recommandation », que le manager devient un sur-ensemble du shift manager. Le backfill ajoute ces permissions à chaque rôle manager existant de toutes les organisations, à chaque démarrage, sans validation du propriétaire métier. C'est une élévation de privilèges en production, décidée par un agent. Le règlement du plan (§2) autorise l'agent à avancer sur une recommandation, mais pas à élargir des droits sans validation. T-007 dépend aussi de T-018, et T-018 dépend de T-007 (dépendance circulaire, voir REV-S-22).
- **Correction** : bloquer T-007 sur une validation écrite du propriétaire du domaine RBAC. Si le sur-ensemble est accepté, l'appliquer par migration de données explicite et journalisée, avec un rapport listant les organisations et permissions ajoutées. Ne pas laisser le backfill de démarrage ajouter des droits. Ajouter un test « aucun rôle existant ne gagne de permission au démarrage ».

### REV-S-06 : mot de passe temporaire connu de l'administrateur qui crée le compte (Haute)

- **Tâches** : T-021, T-026
- **Preuve** : T-021 : « mot de passe temporaire généré, changement obligatoire, sans envoi d'email » et « réponse unique » contenant le mot de passe. Audit IAM-007.
- **Constat** : celui qui crée le compte connaît le mot de passe temporaire et peut se connecter avant le titulaire. Il peut ensuite changer le mot de passe et verrouiller le titulaire, ou lire ses données. Le critère « doit changer son mot de passe » ne protège pas contre cela. Le mot de passe temporaire n'a pas d'expiration. Aucun test ne vérifie qu'un créateur ne peut pas se connecter comme le membre créé.
- **Correction** : mot de passe temporaire à durée limitée (par exemple 72 h, champ `temporaryPasswordExpiresAt`), refus de toute connexion après expiration, journalisation de la création, et test « le créateur ne peut pas ouvrir de session pour le compte créé ». Documenter le risque résiduel tant qu'il n'y a pas d'invitation par email.

### REV-S-07 : verrouillage par compte utilisable comme déni de service ciblé (Haute)

- **Tâches** : T-012, T-013
- **Preuve** : T-012 : « backoff exponentiel par compte », « 10 échecs dans 15 min ». Critère : « un compte légitime reste utilisable depuis une autre IP ».
- **Constat** : un verrouillage par compte bloque le titulaire légitime dès que quelqu'un tente 10 mots de passe sur son adresse. Le critère de test ne couvre que l'IP, pas l'effet du verrou sur le compte. Le critère « brute force bloqué par compte et par IP » n'a pas de test IP.
- **Correction** : définir la règle précisément : verrou par couple (IP, compte) avec limite globale par IP, et verrou par compte limité en durée et sans blocage du titulaire depuis une IP déjà connue. Ajouter deux tests : limite par IP sans verrouiller le compte pour les autres IP, et réponse 429 neutre. Décision à consigner dans la question `limitation-authentification.md`.

### REV-S-08 : réponse d'inscription « neutre » qui annonce un envoi qui n'existe pas (Haute)

- **Tâches** : T-013, T-021 ; audit BCK-005
- **Preuve** : T-013 : réponse « si l'adresse est valide, un message a été envoyé » et « vérification par email reportée à une question future ». Critère : « Aucun endpoint ne révèle l'existence d'un email ». Fichiers : `app/modules/zylo_liquid/service.py` est listé « lecture seule ». Or `create_station_staff_member` (service.py:8157) renvoie 409 sur un email déjà pris (IAM-015).
- **Constat** : le message annonce un envoi qui ne se produit pas, et le compte est activé directement, sans vérification (BCK-005 demandait la vérification avant activation). Le critère sur les endpoints est incompatible avec une fiche qui ne modifie pas le service où se trouve le 409.
- **Correction** : soit implémenter l'envoi de vérification dans T-013, soit ne pas annoncer d'envoi et documenter l'activation immédiate comme risque accepté. Étendre le périmètre de T-013 au 409 de `create_station_staff_member`, ou retirer le critère et le noter comme dette. Le contrôle de doublons avant l'index `lower(email)` doit être un critère, pas un risque.

### REV-S-09 : chiffrement Holykell qui laisse la colonne en clair en base (Haute)

- **Tâches** : T-027, T-002, plan §6 (« aucune suppression de colonne dans ce plan »)
- **Preuve** : T-027 : « puis suppression de l'ancienne colonne dans une migration ultérieure (pas dans cette tâche) ». Aucune tâche ne porte cette suppression. `app/modules/zylo_liquid/models.py:74` : colonne en clair.
- **Constat** : après T-027, le mot de passe reste en clair dans la base, indéfiniment. Le critère « plus aucune lecture en clair dans le code » ne suffit pas. La clé de chiffrement n'est pas dans T-002, donc son absence n'interdit pas le démarrage hors développement. Aucune procédure de sauvegarde ou de perte de clé n'est prévue, alors que T-027 dit que la perte de clé rend les comptes inutilisables.
- **Correction** : créer une tâche explicite pour la suppression de l'ancienne colonne (après vérification et une période d'observation), la mentionner au plan §6. Ajouter la clé à T-002. Ajouter au critère de T-027 la procédure de sauvegarde de la clé (hors dépôt) et un test de restauration.

### REV-S-10 : uploads, types autorisés incohérents et lecture non bornée (Moyenne)

- **Tâches** : T-014, décision `securite/types-fichiers-autorises.md`
- **Preuve** : plan §7 : « PDF et images seulement ». T-014 : « PDF, PNG, JPEG, WebP, et types bureautiques retenus ». `app/shared/storage_router.py:34` : `content = await file.read()`, puis contrôle de taille (l.35) : la lecture est faite avant la limite. `storage_router.py:87` sert le fichier avec le type déduit de l'extension, sans `Content-Disposition`.
- **Constat** : deux décisions différentes pour le même objet. La limite de taille n'empêche pas le chargement complet en mémoire. Les fichiers déjà stockés avec une extension active ne sont couverts par aucun critère (seulement une phrase de risque).
- **Correction** : aligner T-014 et le plan sur une seule liste. Lire au plus `MAX+1` octets. Ajouter un critère : les fichiers existants sont servis avec `attachment` et `nosniff` (test sur un fichier HTML déjà stocké). Ajouter le critère IAM-019 (photo de profil) qui manque actuellement.

### REV-S-11 : critère « aucune CVE » non vérifiable, mauvaise référence (Moyenne)

- **Tâches** : T-015 ; audit BCK-009
- **Preuve** : `requirements.txt:11` `python-jose[cryptography]==3.3.0`, `:18` `Pillow==11.0.0`. `pip-audit` non exécuté (audit).
- **Constat** : le critère « aucune CVE connue » n'a ni commande ni sortie consignée. T-015 dit « T-013 sur les uploads pour Pillow » alors que les uploads sont T-014. Le changement de `python-jose` peut modifier la vérification des jetons : aucun test de non-régression d'authentification n'est exigé.
- **Correction** : critère : sortie de `pip-audit` jointe au document `docs/architecture/securite/surface-api.md`, version corrigée. Ajouter des tests de connexion, refresh et rejet de jeton mal signé avant et après la mise à jour. Corriger la référence T-013 en T-014.

### REV-S-12 : migrations au démarrage, sauvegarde et retour arrière non encadrés (Moyenne)

- **Tâches** : T-028, T-018, T-027, T-037
- **Preuve** : `Dockerfile:33` : `alembic upgrade head && uvicorn`. Dans `alembic/versions/`, 57 fichiers contiennent `drop_column`, `drop_table` ou `TRUNCATE` (par exemple `7ffb9473d45e` avec `TRUNCATE ... CASCADE`). BCK-006 demandait de remplacer ce `TRUNCATE`, T-028 l'écarte.
- **Constat** : la sauvegarde avant migration est « procédure opérateur, hors dépôt », sans tâche ni critère. Le démarrage refusé si `alembic current != head` provoque une indisponibilité si le job de migration n'a pas tourné. Aucune révision de la production n'est relevée. Aucune tâche ne prévoit de retour arrière pour T-018, T-027, T-037.
- **Correction** : ajouter à T-028 un runbook (sauvegarde chiffrée hors dépôt, test de restauration, révision de prod consignée, ordre de déploiement) et un critère de test d'exécution d'un `downgrade` sur base jetable. Décider du sort du `TRUNCATE` (remplacer par une migration vide documentée, ou exclure du chemin de mise à niveau). Ajouter pour chaque tâche de la vague 2 un champ « retour arrière ».

### REV-S-13 : rôles existants jamais rattachés à un module (Moyenne)

- **Tâches** : T-018, T-022
- **Preuve** : T-018, étape 2 : « Role.moduleCode nullable + backfill à NULL ». Et : « Les rôles existants ont moduleCode NULL ... comportement actuel (organisation entière) ».
- **Constat** : la priorité n°1 (droits différents par module) n'est pas atteinte pour les données existantes, puisque les rôles par défaut zylo_liquid restent transverses. T-018 demande un `resourceId` UUID pour stocker le code du module, alors que `Module.code` est une chaîne (IAM-005) : convertir ce type n'est pas une migration additive. Le downgrade « réversible » supprime `moduleCode` et ses données.
- **Correction** : ajouter une migration de données qui rattache les rôles par défaut à leur module (liste explicite, vérifiée par un test). Ajouter une colonne `moduleCode` texte pour les attributions de portée module, plutôt que convertir `resourceId`. Préciser que le downgrade ne restaure pas les données perdues, ou retirer le critère de réversibilité.

### REV-S-14 : protection contre le dump absente jusqu'à T-038, et fiches du plan non versionnées (Haute)

- **Tâches** : T-001, T-016, T-038, T-004
- **Preuve** : T-001, tests attendus : « Garde automatique (défini dans T-038) ». `git check-ignore -v docs/plans/taches/T-001-retrait-dump-git.md` renvoie `.gitignore:30 taches/`. Le `.gitignore` ignore donc toutes les fiches `taches/` du plan.
- **Constat** : entre T-001 et T-038 (vague 2), rien n'empêche de recommiter un dump. Les 40 fiches du plan ne sont pas versionnées, donc T-004 (commit de tout le travail en cours) ne les inclura pas, et l'historique du plan est perdu. T-016 prévoit de retirer la règle, mais T-016 est après T-004.
- **Correction** : retirer `taches/` du `.gitignore` (ou le limiter à la racine) dans T-001, et ajouter immédiatement un hook de pré-commit qui refuse `*.sql*` et `.env*` (hors exemple). Ne pas attendre T-038. Vérifier avec `git check-ignore` que `docs/plans/` et `docs/audit/` sont suivis (`docs/audit/` et `docs/plans/` sont actuellement non suivis).

### REV-S-15 : base de test partagée par défaut entre worktrees (Haute)

- **Tâches** : T-005, T-006 à T-010, plan §2 et §3 (4 à 6 worktrees en parallèle)
- **Preuve** : `tests/conftest.py` : `TEST_DATABASE_URL` vaut par défaut la base `zylo_office_test`, et `_reset_test_database` fait un `TRUNCATE` de toutes les tables à chaque session. La garde de T-005 ne porte que sur le suffixe `_test` et sur quelques noms exacts. Le `.env` du backend pointe sur une autre instance (port 5433) que le défaut des tests (5432), selon l'audit baseline.
- **Constat** : si une tâche oublie `TEST_DATABASE_URL`, elle vide la base partagée par toutes les autres, ce qui produit de faux échecs et de fausses preuves. La garde par nom ne tient pas compte de l'hôte ni du port. Le global-setup Playwright est hors de cette garde.
- **Correction** : supprimer le défaut de `TEST_DATABASE_URL` (échec si absent). Garde commune pour pytest et Playwright : nom en `zylo_t\d{3}_test` (ou `_test`), hôte et port dans une liste autorisée, et refus si la base cible est identique à une base de développement. Ajouter un test qui vérifie que la garde refuse `zylo_office` même sous un autre port.

### REV-S-16 : ports et CORS contradictoires, aucune couverture CORS (Haute)

- **Tâches** : T-003, T-005, T-008, T-037
- **Preuve** : T-003 : Playwright prod canonique sur 3055. T-008 : `next start -p 3308`. Plan §2 : frontend prod `3300+n`. `app/core/config.py:10-18` : `CORS_ORIGINS` ne liste que 3001 et 3055, et le commentaire indique que sans cela, les tests e2e échouent au préflight. `src/core/api/client.ts:3` : défaut `http://localhost:3007`.
- **Constat** : trois sources donnent trois ports pour le même rôle. Aucune tâche ne met à jour `CORS_ORIGINS` pour les nouveaux ports. Le défaut de l'API côté front pointe vers un port que T-003 supprime.
- **Correction** : trancher dans T-003 une seule table (et corriger T-008). Rendre `CORS_ORIGINS` configurable par environnement (le document de T-003 le dit déjà pour le back, mais la liste est en dur). Ajouter aux critères de T-005 et T-008 « un préflight depuis le port de la tâche réussit ».

### REV-S-17 : tests Playwright, critères flous et cause de 9 échecs non tranchée (Moyenne)

- **Tâches** : T-009, T-026, T-038
- **Preuve** : baseline §3 : 9 échecs « non tranchés », P7 dépend d'un compte Holykell réel. T-009 : « Suite e2e prod : 26/27 au moins (P7 requalifié) ».
- **Constat** : « 26/27 » n'est pas défini si P7 est exclu (27 tests, 26 exécutés, 1 ignoré ?). Rien n'interdit de réécrire une assertion pour la faire passer, sauf une règle orale. La cause de chaque échec doit être dans la PR, pas vérifiable par un test. Les vidéos (`video: on`) conservent les données de test sans règle de rétention.
- **Correction** : critère : 26 passent, P7 est marqué et exclu explicitement, et `git diff` des fichiers `e2e/` ne contient aucune assertion supprimée (contrôle scripté). Ajouter une règle de rétention des vidéos et traces. Le compte Holykell de test ne doit pas être dans le dépôt (vérifier `e2e/` et les fixtures).

### REV-S-18 : CI, environnement de recette et « prod » ambigus (Moyenne)

- **Tâches** : T-038, T-010 (risque), T-026, plan §2 (interdit : « opération sur la production »)
- **Preuve** : T-010 : « Risque : ... Tests cross-tenant obligatoires et parcours prod vérifié ». Plan §2 : « Interdits : opération sur la production ». `ci.yml.disabled` lance `alembic upgrade head` puis `pytest` sur une base de service, sans étape de démarrage du backend pour Playwright.
- **Constat** : le plan ne définit pas d'environnement de recette. « Parcours prod vérifié » ne peut donc être qu'un build local, ce qui n'est pas dit. La CI décrite par T-038 n'indique ni le service PostgreSQL, ni le seed du référentiel, ni le démarrage du backend pour Playwright.
- **Correction** : définir l'environnement de recette (base dédiée, backend lancé sur build) et remplacer « prod » par « build de production local » dans T-010. Compléter T-038 : service Postgres, nom de base `zylo_tNNN_test` par job, seed, démarrage du backend et de `next start`, et interdiction d'écrire dans une base sans suffixe `_test`.

### REV-S-19 : frontend sans en-têtes de sécurité ni CSP (Moyenne, omission)

- **Tâches** : aucune ; T-037 (cookies), T-014 (CSP côté API seulement)
- **Preuve** : `zylo-office-frontend/next.config.ts` ne définit aucun `headers()`. `grep` : aucune occurrence de `Content-Security-Policy` ni de `X-Frame-Options`. `dangerouslySetInnerHTML` : 0 occurrence (positif).
- **Constat** : T-037 passe les jetons en cookies HttpOnly, ce qui rend une CSP stricte plus importante. Aucune tâche ne la prévoit. L'API seule protège ses fichiers, pas l'interface.
- **Correction** : ajouter une tâche (ou un critère à T-033) : CSP, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` dans `next.config.ts`, avec test sur les en-têtes de la réponse de production.

### REV-S-20 : jetons en cookies, migration et CSRF incomplets (Moyenne)

- **Tâches** : T-037, T-020
- **Preuve** : `src/core/auth/tokens.ts` lit et écrit `localStorage`. T-037 prévoit que le backend « accepte cookie ET en-tête pendant la transition », et que le cookie de rafraîchissement est restreint au chemin `/auth`.
- **Constat** : pendant la transition, le jeton reste lisible par JavaScript, et l'en-tête Bearer reste un vecteur. Les cookies `Secure` ne fonctionnent pas en `http://localhost` sur certains navigateurs : aucun critère ne dit comment le développement local est traité. La protection CSRF n'est pas testée sur les routes d'authentification elles-mêmes.
- **Correction** : fixer une date de fin pour l'acceptation de l'en-tête. Préciser le traitement de `Secure` en local. Ajouter un test CSRF sur `/auth/refresh` et `/auth/logout`.

### REV-S-21 : journalisation et secrets dans les logs non couverts (Moyenne, omission)

- **Tâches** : aucune explicite ; T-029 traite seulement les `except`
- **Preuve** : BCK-017 (exceptions avalées), BCK-010 et REV-S-03 (littéraux). Aucune tâche ne vérifie que les mots de passe, jetons ou `holykellPassword` n'apparaissent pas dans les journaux. T-027 vérifie seulement la valeur Holykell.
- **Constat** : un `logger.exception` autour d'un appel Holykell peut recopier les arguments. T-029 demande de journaliser davantage, donc davantage de surface.
- **Correction** : ajouter à T-029 un test qui capture les logs pendant les parcours de connexion, de création de compte et d'appel Holykell, et vérifie l'absence des valeurs sensibles.

### REV-S-22 : dépendances, ordre et conflits incohérents entre registre et fiches (Moyenne)

- **Tâches** : registre, fiches T-002, T-007, T-011, T-013, T-018, T-020, T-027, T-034, plan §5
- **Preuve** :
  - T-002 : « Bloque T-011 » ; le registre n'a que T-004 pour T-011.
  - T-020 : dépend de « T-011 et T-012 » ; le registre donne T-012 et T-013.
  - T-007 dépend de la décision de T-018 ; T-018 dépend de T-007 (cycle).
  - T-010 : critère Playwright sans T-008 dans les dépendances.
  - §5 (fichiers chauds) : `zylo_liquid/service.py` listé pour T-021, T-027, T-029, T-034, T-035. T-013 et T-020 le modifient aussi (`create_station_staff_member`, `reset_station_staff_password`), et T-027 le modifie sans ordre fixé avec T-034.
- **Constat** : un agent qui suit le registre peut démarrer une tâche avant ses prérequis, et deux agents peuvent modifier le même fichier sans ordre.
- **Correction** : générer le graphe depuis les fiches (script qui compare « Dépendances » de chaque fiche au registre et échoue en cas d'écart). Résoudre le cycle T-007/T-018 en déplaçant la décision avant T-018. Compléter §5 et fixer l'ordre T-027 avant ou après T-034.

### REV-S-23 : critères d'acceptation non vérifiables ou contradictoires (Basse)

- **Tâches** : T-006, T-012, T-015, T-023, T-029, T-035
- **Constat** :
  - T-006 : « 21 tests verts, sans assertion supprimée », alors que la correction de `test_purchase_order_requires_active_supplier` dépend d'une décision non prise (ordre de validation). Le critère peut devenir impossible.
  - T-023 : « Aucun changement de comportement attendu », alors que la décision IAM-020 rend `GET /modules` et `GET /billing/plans` authentifiés.
  - T-029 : « au moins un test par exception traitée » sans liste.
  - T-035 : « `service.py` inférieur à 2 000 lignes, ou justification écrite » : un critère qui accepte n'importe quelle taille.
- **Correction** : rendre chaque critère mesurable (commande, seuil, fichier de preuve). Pour T-006, prévoir le cas « décision = API change » et son critère propre. Pour T-023, retirer « aucun changement de comportement » ou le limiter aux routes non modifiées.

### REV-S-24 : tâches à risque sans plan de retour arrière ni validation humaine (Basse)

- **Tâches** : T-018, T-021, T-027, T-037
- **Constat** : ces quatre tâches modifient l'authentification, les droits, les données chiffrées ou les migrations, et leurs fiches ne prévoient ni feature flag, ni retour arrière, ni validation humaine avant la fusion. Le plan §2 laisse l'orchestrateur fusionner, mais aucune porte de sortie n'est définie si une migration se passe mal en production.
- **Correction** : pour chacune, ajouter une section « Retour arrière » et une validation écrite du propriétaire avant fusion (les décisions métier doivent déjà passer par `docs/questions/`, mais la fusion ne l'exige pas).

### REV-S-25 : identifiants Holykell de test dans les tests e2e (Basse)

- **Tâches** : T-009, T-027
- **Preuve** : baseline §3 : P7 utilise un compte Holykell réel (`h-smartlink.com`) ou un simulateur, et ses identifiants ne sont pas décrits.
- **Constat** : si les identifiants sont dans `e2e/` ou dans les fixtures versionnées, ils fuient avec le dépôt. Non vérifié, faute de lecture des fichiers de données de test.
- **Correction** : vérifier avec `git grep` que `e2e/` ne contient aucun identifiant externe. Les lire depuis l'environnement, et ajouter un critère à T-009.

---

## Points conformes relevés

- L'IDOR (REV-S-04 et BCK-001) est bien décrit et localisé ; les 13 routes énumérées correspondent à `identite-permissions.md`.
- Le plan interdit `TRUNCATE`, `DROP` et la réécriture d'historique sans accord (§2) ; la règle est claire.
- Les tâches T-002, T-005 et T-027 ont des stratégies de test concrètes (cas unitaires, cas d'échec).
- Les 22 échecs pytest et 10 échecs Playwright sont classés par groupe avec leur cause probable (baseline §1.1 et §3), et le compte est exact (12 + 9 + 1 = 22).

## Limites de cette revue

- Aucune commande de test lancée. Les chiffres de baseline sont repris de `baseline-tests.md`, non rejoués.
- Visibilité du dépôt GitHub non contrôlée (pas d'accès réseau). Si le dépôt est public, REV-S-01 passe en exploitable immédiatement.
- Les fichiers de données e2e et `.env.migration` n'ont pas été lus (volontairement).
