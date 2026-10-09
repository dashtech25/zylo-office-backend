# T-013 : Politique de mot de passe et réponses neutres, sans annoncer d'envoi inexistant

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend et frontend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `feat/T-013-mot-de-passe` · **Base de test** : `zylo_t013_test` · **Ports** : back 3113, front dev 3213, front prod 3313
- **Dépendances** : T-012
- **Décisions requises** : `securite/politique-mot-de-passe.md` (recommandation : 12 caractères)

## Objectif
Une seule règle de mot de passe (12 caractères minimum, mots de passe courants refusés) à l'inscription, au changement et à la réinitialisation. L'inscription ne révèle pas l'existence d'un compte. Le message n'annonce aucun envoi qui n'existe pas. L'e-mail est normalisé en minuscules.

## Problèmes résolus
- BCK-005 (P1), IAM-015 (P2, énumération), IAM-016 (P2), IAM-024 (P3), FRT-013 (P2), REV-S-08 (message d'envoi inexistant, 409 de `create_station_staff_member`)

## Dépendances : justification
- T-012 : limitation de l'inscription (endpoint) que T-013 modifie et teste.
- Retirées (confort ou CI, pas de prérequis technique) : T-002 (même zone de configuration : ordre de fusion seulement).

## Fichiers / modules concernés
- Backend : `app/auth/schemas.py`, `app/auth/service.py`, `app/identity/service.py` (`check_email_available`), `app/modules/zylo_liquid/service.py` (fonctions de personnel uniquement : `create_station_staff_member`, `reset_station_staff_password`)
- Migration : index unique sur `lower(email)` (après contrôle de doublons)
- Frontend : `src/shared/lib/validation.ts` (créé), `src/core/auth/ForceChangePasswordScreen.tsx`, `src/app/(auth)/register/page.tsx`, `AddStaffMemberModal.tsx`

## Stratégie
1. Une constante de longueur, côté backend et frontend, et un seul schéma réutilisé.
2. Réponse d'inscription neutre : « si cette adresse peut être utilisée, la suite vous sera indiquée ». Aucun texte n'annonce un e-mail envoyé. L'activation immédiate est un risque accepté et écrit (la vérification par e-mail relève de T-049).
3. Le 409 de `create_station_staff_member` (personnel, hors T-034) est remplacé par la même réponse neutre pour les flux publics ; pour le flux administrateur (authentifié et autorisé), le message de doublon reste explicite, et ce choix est consigné.
4. Contrôle de doublons de `lower(email)` **avant** l'index ; sur la production, à faire par l'opérateur, hors périmètre.

## Tests attendus
- Unitaires : mot de passe de 11 caractères refusé partout ; e-mail en majuscules normalisé.
- Intégration : deux inscriptions avec la même adresse (casse différente) : une seule acceptée, réponse identique.
- Playwright sur build prod : inscription et changement de mot de passe, message d'erreur attendu.

## Critères d'acceptation
- Une seule constante de longueur, côté backend et frontend.
- Aucun endpoint public ne révèle l'existence d'un e-mail.
- Aucun message n'annonce un envoi qui n'existe pas.
- Index unique `lower(email)` après migration.

## Risque et retour arrière
Moyen : l'index unique échoue en présence de doublons (contrôle préalable obligatoire). Les comptes existants ne sont pas invalidés. Retour arrière : supprimer l'index (migration inverse, additive).

## Livrable documentaire
- `docs/questions/securite/politique-mot-de-passe.md`

## Parallélisable avec
T-011, T-014, T-015 (après T-012 sur `app/auth/`).
