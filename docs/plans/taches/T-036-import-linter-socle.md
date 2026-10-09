# T-036 : Contrats import-linter complets et découplage du socle

- **Statut** : Terminée · **Priorité** : P1 · **Vague** : 2 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : socle · **Type** : refactor
- **Branche suggérée** : `refactor/T-036-contrats` · **Base de test** : `zylo_t036_test` · **Ports** : back 3136
- **Dépendances** : T-005, T-010
- **Décisions requises** : `architecture/contrats-importlinter.md` (appliquée)

## Objectif
Ajouter les contrats manquants : cycle `alerts` ↔ `zylo_liquid` (ARC-005, P1), `zylo_tanker` (ARC-006), notifications (ARC-007), acyclicité entre paquets de premier niveau. Supprimer les `ignore_imports` du socle par un registre de seeders, sortir `core/` de la dépendance vers `identity`, et retirer FastAPI des services.

## Problèmes résolus
- ARC-005 (P1), ARC-006, ARC-007, ARC-008, ARC-009, ARC-010, ARC-017, ARC-018, REV-A-16, REV-A-11 (ordre avec T-018)

## Dépendances : justification
T-010 (dépendances d'identité stabilisées), T-005 (base). Bloque T-018 : le registre de seeders est introduit ici avant que T-018 n'ajoute du code de seed dans `modules_registry/service.py`.

## Fichiers / modules concernés
- `.importlinter` : contrats `forbidden` par paire (pour l'acyclicité), contrats pour zylo_tanker et notifications. Le type `acyclic_siblings` ne vaut que pour des paquets frères : `app.alerts` et `app.modules.zylo_liquid` ne le sont pas.
- `app/core/security.py` (ligne 13)
- `app/modules_registry/service.py` (lignes 133 et 137) : registre de seeders
- `app/rbac/service.py`, `app/identity/service.py` : imports FastAPI vers `dependencies.py`
- `app/location/service.py` (ligne 340) : `os.environ` vers `Settings`
- `app/shared/permissions.py` (**étendu**, il existe déjà)
- `app/notifications/service.py` (ligne 31)
- `app/modules/zylo_tanker/dev_seed.py` (écrit dans les tables de `location`, ARC-006)

## Stratégie
1. Question `architecture/contrats-importlinter.md` : recommandation appliquée : `forbidden` en erreur, exceptions datées, réduites à chaque PR.
2. Contrats en avertissement d'abord, puis en erreur.
3. Registre de seeders injecté, le socle ne l'importe pas.
4. `lint-imports` branché en CI par T-038b.

## Tests attendus
- `lint-imports` : contrats KEPT, nombre supérieur à 10.
- Tests unitaires du registre de seeders.
- Suite pytest sans nouvel échec.

## Critères d'acceptation
- Aucun cycle entre paquets de premier niveau ; chaque `ignore_imports` est justifié et daté.
- `core/` n'importe plus `identity/`.

## Risque et retour arrière
Moyen : déplacer des dépendances FastAPI peut casser des injections. Retour arrière : contrats repassés en avertissement par configuration.

## Livrable documentaire
- `docs/architecture/modules/` (créé 2026-10-09) : `matrice-dependances.md`, `capacites-proprietaires.md`, `files-usage-zylo-liquid.md`, `exceptions-importlinter.md` (contrats, exceptions datées, violations du snapshot wip).

## Parallélisable avec
T-035a à T-035e (fichiers distincts ; T-035a touche `zylo_liquid`, pas le socle). Attention à `rbac/service.py` avec T-018 et T-019.
