# T-028 : Sortir migrations et seeds du démarrage, avec runbook de sauvegarde et de retour arrière

- **Statut** : À vérifier · **Priorité** : P1 · **Vague** : 1 · **Taille** : M · **Dépôt(s)** : backend · **Domaine** : ci · **Type** : refactor
- **Branche suggérée** : `fix/T-028-migrations-job` · **Base de test** : `zylo_t028_test` · **Ports** : back 3128
- **Dépendances** : T-002, T-005
- **Décisions requises** : `architecture/migrations-au-demarrage.md` (appliquée), `architecture/sauvegarde-avant-migration.md` (en attente)

## Objectif
Aujourd'hui le `CMD` exécute `alembic upgrade head` puis `uvicorn` à chaque démarrage, et l'application lance seeds et backfills à chaque processus (`app/main.py`, `on_startup`). Séparer : une étape de migration unique, lancée avant le déploiement, des commandes de seed explicites et idempotentes, et une vérification de la révision au démarrage.

## Problèmes résolus
- BCK-006 (P1, migrations au démarrage), ARC-022 (P3), BCK-016 (partie seeds à chaque processus), REV-S-12 (sauvegarde et retour arrière non encadrés), REV-S-05 (backfills au démarrage)

## Dépendances : justification
T-002 (configuration), T-005 (base dédiée). Bloque T-029, T-051.

## Fichiers / modules concernés
- `Dockerfile` (ligne 33 : `CMD`)
- `app/main.py` (`on_startup`, lignes 80 à 110)
- `app/cli.py` ou `scripts/seed.py` (commandes `migrate`, `seed`, `check-revision`)
- `docs/process/deploiement.md` (créé), `docs/process/runbook-migration.md` (créé)

## Stratégie
1. `CMD` : uvicorn seul. Au démarrage, vérification que `alembic current` est au head ; refus avec message clair sinon.
2. Job de migration séparé, exécuté une fois par déploiement, précédé d'une sauvegarde chiffrée hors dépôt (procédure opérateur, décrite dans le runbook).
3. Seeds : commande explicite idempotente, appelée par le job de déploiement. Les backfills de `on_startup` sont retirés : leur logique devient une migration de données explicite (T-007 et T-018 s'y conforment).
4. Les migrations déjà appliquées ne sont pas réécrites. La migration `7ffb9473d45e` contient un `TRUNCATE ... CASCADE` historique : elle reste, est documentée comme « ne jamais rejouer sur une base contenant des données », et la mise à niveau d'une base vide est testée.
5. Test de retour arrière : `downgrade -1` sur base jetable pour chaque migration de la vague 1 et 2 (critère de chaque tâche qui migre).

## Tests attendus
- Démarrage sans migration à jour : refus avec message clair.
- `alembic upgrade head` sur base vierge puis seeds : deux exécutions, même résultat.
- `downgrade -1` puis `upgrade head` : succès sur base jetable.

## Critères d'acceptation
- Le conteneur ne migre plus au démarrage.
- Seeds exécutables seuls, idempotents.
- Runbook de sauvegarde, de déploiement et de retour arrière écrit, avec révision de production consignée (à renseigner par l'opérateur).

## Risque et retour arrière
Élevé : un déploiement qui oublie la migration laisse une application incompatible avec le schéma. Retour arrière : revenir au `CMD` précédent (un commit).

## Livrable documentaire
- `docs/process/deploiement.md`, `docs/process/runbook-migration.md`
- `docs/questions/architecture/migrations-au-demarrage.md`
- `docs/questions/architecture/sauvegarde-avant-migration.md`

## Parallélisable avec
T-012 à T-015 (séquencer avec T-015 et T-051 sur `app/main.py`).

## Réalisation (branche `chore/T-028-T-051-migrations-conteneur`, statut À vérifier)
- `CMD` du `Dockerfile` : uvicorn seul. `on_startup` ne seed, ne backfill, ne migre plus ; il vérifie seulement la révision (`app/core/migrations.py`).
- `app/cli.py` : `verifier-revision`, `migrer` (garde destructive : confirmation + fichier de sauvegarde), `seed`, `backfill` (rôle owner seulement).
- Documentation : `docs/operations/migration.md`, `deploiement.md`, `retour-arriere.md`.
- Non fait ici : runbook de production (révision à renseigner par l'opérateur), tests de `downgrade -1` sur base jetable pour chaque migration des vagues 1 et 2, réécriture de `7ffb9473d45e` (seulement commentée).
