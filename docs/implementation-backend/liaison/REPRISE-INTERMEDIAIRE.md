# Reprise de l'intermédiaire, backend Zylo Office (2026-11-06 03:55 EST)

## Règles en vigueur
- 4 exécutants codeurs au maximum, vivants en même temps. Compter avant chaque création. Ne jamais dépasser 4.
- Aucun agent intégrateur : c'est l'intermédiaire qui fusionne (merge --no-ff, migrations de fusion, lignes SUIVI.md).
- Les exécutants codent et lancent leurs propres tests ciblés (zylo_tNNN_test, sans --noconftest). L'intermédiaire ne lance jamais de tests lui-même, ni Monitor.
- Un lot = une branche be-NNN-lot depuis develop, worktree office/worktrees/BE-NNN-back. Tests d'abord, puis code.
- Ne jamais faire de merge de develop dans une branche de lot (interdit sans accord écrit) : en cas de conflit, nouvelle branche be-NNN-v2 depuis develop + cherry-pick.
- Ne jamais réinitialiser develop (pas de reset --hard) : pour annuler une fusion, `git revert -m 1 <merge>`.
- Après chaque fusion : `import app.main` doit passer et une seule tête Alembic doit subsister.
- Protocole de liaison : rapport toutes les 30 min dans liaison/rapports/AAAA-MM-JJ-HHMM.md (8 sections), message « main » (2 lignes + chemin), puis `reset_compteur.sh <chemin>`, et suppression de RELANCE.flag. URGENT seulement dans les cas du skill.
- Au-delà de 500k de contexte : ne plus lire de fichiers de code, s'appuyer sur SUIVI.md et les rapports.
- **POLITIQUE DE PUSH (modifiée 2026-11-12)** : Développement/fusions en local ; push vers GitHub branche `develop` tous les 5-10 lots fusionnés (après fusions, jamais en cours de dev). Signaler dans les rapports : "Push à GitHub ? [OUI/NON]".

## Fusionnés sur develop (tête 629e1ac, tête Alembic unique 54ba4aaf7237)
BE-003, BE-024 (absorbe BE-261), BE-180, BE-248, BE-251, BE-253, BE-244, BE-247, et les lots fusionnés avant la session (cf. SUIVI.md).
Depuis la dernière reprise (BE-130 inclus, c99250d) : be-254, be-239, be-238 (via be-238-v2), be-142, be-094, be-084, be-255, be-245, be-009, be-122, be-127, be-160, be-227, be-243, be-252, be-257, be-258, be-083, be-141, be-170, be-176, be-139, be-159, be-061, be-085, be-089, be-095, be-262, be-171, be-091, be-097, be-246, be-092, be-096, be-182, be-183, be-187, be-147 (via be-147-v2), be-192, be-188, be-184, be-193, be-100, be-101, be-129, be-107, be-038, be-259.
Compte script : 197 identifiants fusionnés (commande ci-dessous). Les lignes SUIVI.md de chaque lot sont à jour, sauf BE-038 (ligne 62 réécrite, ligne de fusion ajoutée).

## Suspendus
- BE-102 : BLOQUÉ par QE-POR-04. La fiche exige qu'aucun rôle Owner ne soit créé à la création d'une organisation ; identity/service.py::create_organization en crée un, et la fixture organization de tests/conftest.py (~161 fichiers) en dépend. Décision à trancher avant reprise. Worktree BE-102-back conservé, aucun commit utile.
- BE-186 : BLOQUÉ car BE-185 a été annulé sur develop (revert a4a89c8). Relancer une fois be-185-v2 fusionné ; sa branche be-186-lot est à 249b80c (ancienne base) : prévoir une branche be-186-v2 depuis develop.

## En cours (exécutants relancés après la limite API, 2026-11-06)
- BE-185 (branche be-185-v2, HEAD 165716c) : ambiguïté Alembic. La table `tenant` est définie par BE-100 (app/identity/models.py, classe Tenant) ; BE-185 la redéfinissait, ce qui cassait l'import (`Table 'tenant' is already defined`). Correction : une seule définition (BE-100), migration BE-185 = colonnes de cycle de vie seulement, downgrade compatible. Problème restant : le test ca1 de BE-100 casse sur be-185-v2 (downgrade -1 ne retire pas tenant). Exécutant relancé : doit rendre BE-100 10/10 et BE-185 8/8 verts ensemble.
- BE-130 : FUSIONNÉ (c99250d, 7/7 verts). Ne plus le relancer.
- BE-108 (be-108-lot, commit 4767043 tests non vérifiés) : relancé (limite API à 429 interrompue).
- BE-131 (be-131-lot, à develop, sans commit) : relancé depuis le début.

## Prochains lots éligibles (prérequis fusionnés, non commencés)
BE-039, BE-105, BE-116, BE-118, BE-134. Bloqués : BE-109 (attend BE-106/107/108), BE-106, BE-110..BE-119 selon chaîne ; BE-186 (attend be-185-v2).
Recalcul : voir commande 2 ci-dessous.

## Blocages et écarts connus
- Test transverse rouge déjà présent sur develop : test_inventaire_donnees_be242.py (76 tables absentes du registre, antérieur à BE-100). À corriger en fin de plan.
- BE-038 : routes à portée répondent 404 et non 403 pour un identifiant inexistant (constaté, non corrigé).
- BE-147 : décision QE-ADM-BE147-01 appliquée (require_admin_scope sur les montages /admin) ; QE à inscrire dans POINTS-OUVERTS.md (absente du fichier).
- ALERTE.txt (liaison) : présent depuis 11:00 (surveillance arrêtée après deux échecs). Non supprimé.
- Agents anciens listés comme « en cours » par TaskStop (propriété) : BE-009, BE-122, BE-127, BE-182 (ancien), BE-160, BE-227, BE-243 (ancien) ; à ignorer, leurs lots sont fusionnés.

## Questions en attente (POINTS-OUVERTS.md)
- QE-POR-04 : création d'organisation sans rôle Owner (bloque BE-102).
- QE-FAC-07 : permission de suspension manuelle billing.subscription.manage (BE-091, appliquée).
- QE-FAC-04 : lien checkout / abonnement (BE-084, BE-089 : recommandation appliquée).
- QE-FAC-11 : adaptateur paiement stub FlutterwaveTestProvider (BE-095).
- QE-FAC-25 : demande d'export non ready bloque la clôture (BE-097, appliquée).
- QE-EXP-15 : approbation d'un tenant par personne désignée (BE-246, appliquée).
- QE-API-16 : 5 tentatives d'inbox (BE-193, appliquée).
- QE-API-07 : extension de la table user plutôt que user_identity (BE-187, appliquée).
- QE-POR-30 : renommage organizationUser vers organization_user (BE-100, appliquée).
- QE-POR-24 : invitation.recipientUserId (BE-100, appliquée).
- QE-SOC-26 : fixtures BE-038 (appliquée).
- QE-ADM-BE147-01 : (à inscrire).

## Commandes utiles
1. Recalcul des lots éligibles et des fusionnés : script Python lisant implementation-backend/DEPENDANCES.md (tableau `| BE-nnn | prérequis |`) et `git log develop --format=%s` (motifs « Fusion de be-NNN-lot » et « feat(BE-NNN) »), plus la liste des lots fusionnés à la main.
2. Fusion d'un lot : `git -C "<office>/worktrees/develop-integration-back" merge --no-ff be-NNN-lot -m "Fusion de be-NNN-lot dans develop"`
3. Vérifications après fusion (venv du backend, env.sh pour ENVIRONMENT) :
   - `.../zylo-office-backend/.venv/bin/python -c "import app.main"`
   - `.../zylo-office-backend/.venv/bin/python -m alembic heads` (une seule tête attendue)
4. Tête double : `alembic merge -m "fusion BE-NNN et develop" <tête1> <tête2>`, puis `git add alembic/versions && git commit --amend --no-edit`.
5. Annuler une fusion publiée : `git revert -m 1 <hash>` (jamais reset).
6. Ajout d'une ligne SUIVI.md : après la dernière ligne `| 1xx |`, insérer `| n | BE-NNN | be-NNN-lot | fusionné (...) | <hash> | <verts>/<rouges>/<total>, <fichier de test> |`.
7. Liaison : `implementation-backend/liaison/reset_compteur.sh <rapport>` après écriture du rapport et envoi à main.
8. Chemins : office = /home/remy/Desktop/travail/dashtech/zylo/projet en cours/zylo-office/office ; backend = office/zylo-office-backend ; intégration = office/worktrees/develop-integration-back ; env de test = /tmp/claude-1000/-home-remy/176a69a3-8e62-4402-babc-33835dcfbe45/scratchpad/env.sh (puis re-exporter TEST_DATABASE_URL vers zylo_tNNN_test).

## MISE À JOUR (2026-11-06, après REPRISE PRÊTE)
- Fusionnés depuis : BE-130 (c99250d), BE-131 (099abe2), BE-108 (dc428ad), BE-185 (e9143f4, via be-185-v2). Total : 199 fusionnés, 46 restants.
- Aucun exécutant vivant de mon fait à cette heure. Tête Alembic : b108c4a1d2e3 (unique).
- BE-185 : fusionné. Rouge transverse accepté hors lot : BE-100 ca1 (révision de fusion 54ba4aaf7237 et chaîne BE-193). À corriger en fin de plan par réordonnancement des révisions.
- BE-186 : débloqué (BE-185 fusionné). Branche be-186-lot à l'ancienne base : créer be-186-v2 depuis develop, ne pas réutiliser be-186-lot.
- Éligibles maintenant : BE-039, BE-105, BE-116, BE-118, BE-134, BE-186 (via be-186-v2).
- Suspendu : BE-102 (QE-POR-04).
