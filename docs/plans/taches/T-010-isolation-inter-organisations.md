# T-010 : Isolation inter-organisations (IDOR) sur les 13 routes et sur toutes les routes d'organisation

- **Statut** : Planifiée · **Priorité** : P0 · **Vague** : 1 · **Taille** : L · **Dépôt(s)** : backend · **Domaine** : iam · **Type** : security
- **Branche suggérée** : `fix/T-010-isolation-organisations` · **Base de test** : `zylo_t010_test` · **Ports** : back 3110, front prod 3310
- **Dépendances** : T-005, T-038a, T-008
- **Décisions requises** : `rbac/code-http-acces-interdit.md` (recommandation appliquée : 404 uniforme)

## Objectif
L'autorisation se fait sur l'en-tête `X-Organization-Id`, l'action sur l'`organization_id` du chemin, et rien ne compare les deux. Un administrateur de A peut agir sur B. Le client n'est jamais autorité sur le tenant : l'en-tête est un sélecteur, validé contre une appartenance active, pour **toutes** les routes d'organisation (avec ou sans chemin), et chaque objet est chargé avec le filtre `organizationId`.

## Problèmes résolus
- BCK-001 (P0), IAM-001 (P0), IAM-018, ARC-009 (partie), IAM-013 (partie), REV-S-04 (périmètre limité aux 13 routes), REV-D-19 (partie)

## Dépendances : justification
T-005 (base dédiée), T-038a (CI bloquante avant une modification sensible), T-008 (parcours prod pour `proprietaire-02` et `-04`). Bloque T-018, T-019, T-021, T-022, T-023, T-036, T-047.

## Fichiers / modules concernés
- `app/rbac/dependencies.py` : `get_organization_context` (écrit directement ici, pour que T-036 n'ait pas à le déplacer)
- `app/rbac/service.py` : `get_current_organization_id` (validation d'appartenance), `require_permission`
- `app/identity/router.py`, `service.py` (`PATCH /organizations/{id}`, `protected-demo` : protégées ici, supprimées par T-051)
- `app/modules_registry/router.py`, `service.py`
- `app/billing/router.py` (`POST /organizations/{id}/subscriptions`)
- `app/rbac/router.py`
- `tests/test_isolation_organisations.py` (créé), `tests/test_rbac*.py`

## Stratégie
1. Dépendance unique : l'acteur doit avoir une appartenance active (`OrganizationUser`) à l'organisation du chemin. Si l'en-tête est présent, il doit être égal au chemin. Réponse uniforme 404 pour « inexistant » et « interdit » (R2).
2. Validation d'appartenance dans `get_current_organization_id` : applique la règle aux routes sans chemin (zylo_liquid, zylo_tanker, files, shared), pas seulement aux 13 routes.
3. Objets chargés par `WHERE id = :id AND organizationId = :org`.
4. Interdire tout `require_permission` qui ne compare pas l'organisation à l'appartenance.

## Tests attendus
- Paramétré sur les 13 routes : utilisateur de A (tous droits sur A) appelant B reçoit 404, aucune écriture en base.
- Échantillon de routes sans chemin (zylo_liquid, zylo_tanker, files) : en-tête de B refusé pour un membre de A seul.
- Membre de A et B reste autorisé selon ses droits sur chacune.
- Non-régression : `tests/test_rbac*.py`, `tests/test_modules.py`.
- Playwright sur build prod : `proprietaire-02` et `-04` passent (configuration de T-008).

## Critères d'acceptation
- Les 13 routes de `identite-permissions.md` refusent le cross-tenant, avec au moins 13 cas de test.
- Une route sans chemin d'organisation qui accepte un en-tête étranger fait échouer le test.
- Aucune route d'organisation sans dépendance d'appartenance (contrôle par T-023).

## Risque et retour arrière
Élevé : 13 routes et tout le frontend envoient l'en-tête. Une validation trop stricte casse les parcours. Retour arrière : revert de la dépendance ; le test cross-tenant reste pour mesurer.

## Livrable documentaire
- `docs/architecture/securite/isolation-organisations.md` (créé)
- `docs/questions/rbac/code-http-acces-interdit.md`

## Parallélisable avec
T-006, T-007, T-011 à T-016 (fichiers distincts ; `rbac/` n'est touché par aucune de ces tâches).
