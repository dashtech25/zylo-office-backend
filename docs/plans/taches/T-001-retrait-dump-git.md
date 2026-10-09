# T-001 : Retirer le dump de l'index git et verrouiller les dumps

- **Statut** : À vérifier · **Priorité** : P0 · **Vague** : 0 · **Taille** : S · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `fix/T-001-retrait-dump-index` · **Base de test** : aucune · **Ports** : aucun
- **Dépendances** : T-004
- **Décisions requises** : `securite/purge-historique-dump.md`, `securite/rotation-credentials.md`, `process/visibilite-depot-requirements.md`

## Objectif
Retirer `backups/zylo_office_20260831_180729.sql.gz` de l'index git (le fichier reste sur disque), renforcer les règles d'ignore, et consigner les décisions de visibilité, de purge et de rotation. Aucune réécriture d'historique dans cette tâche.

## Problèmes résolus
- BCK-003 (P0), ARC-003, DOC-015 (partie dump), BCK-011 (`.env.migration`), REV-S-01

## Dépendances : justification
T-004 (base propre). Le hook de garde est posé par T-004 (lot 0) ; cette tâche ne le duplique pas.

## Fichiers / modules concernés
- `backups/` (index uniquement)
- `.gitignore` : `*.sql`, `*.sql.gz`, `backups/`, `.env.*` avec `!.env.example`
- `docs/questions/securite/purge-historique-dump.md`, `docs/questions/securite/rotation-credentials.md` (questions à créer ou compléter)

## Stratégie
1. Contrôler la visibilité du dépôt `origin` (public ou privé) sans ouvrir le dump. Consigner le résultat, la date et la méthode dans `purge-historique-dump.md`.
2. `git rm --cached backups/*.sql.gz`, commit dédié.
3. Règles d'ignore ; vérifier avec `git check-ignore -v`.
4. Vérifier que l'historique est intact : `git log --all -- backups/` liste toujours le commit d'origine.
5. Rédiger la question de purge (options : conservation avec rotation et dépôt privé ; réécriture `git filter-repo` avec force-push). Recommandation : considérer le contenu comme compromis, faire tourner les identifiants, et ne pas réécrire l'historique sans accord écrit du commanditaire.
6. Rédiger `rotation-credentials.md` : liste des identifiants à faire tourner (mot de passe de la base `zylo_office`, compte Holykell, mot de passe de démo de `scripts/bootstrap_demo_org.py`, jetons présents dans `e2e/.auth/`), propriétaire et date cible pour chacun.

## Tests attendus
- `git ls-files backups/` vide.
- `git check-ignore -v backups/test.sql.gz` et `.env.migration` renvoient une règle.
- `git log --all -- backups/` non vide (preuve de non-réécriture).
- Le hook de T-004 refuse un `*.sql.gz` ajouté (test sur un dépôt jetable hors `office/`).

## Critères d'acceptation
- Dump absent de l'index, présent sur disque.
- Visibilité du dépôt consignée (public ou privé, date, méthode).
- Liste des identifiants à faire tourner avec propriétaire et date cible, dans `rotation-credentials.md`.
- Décision sur la réécriture consignée par écrit par le commanditaire (l'agent ne la prend pas).
- Condition de **clôture** (pas de fusion) : rotation attestée par le propriétaire, sans valeur de secret dans le dépôt.
- Deux questions dans `docs/questions/securite/`, avec options, recommandation et état « En attente de réponse ».

## Risque et retour arrière
Faible pour le code. Risque opérationnel : tout clone existant garde le fichier dans son historique, et un dépôt public rend la fuite exploitable immédiatement. Retour arrière : `git add` du fichier rétablit l'index (sans effet sur l'historique).

## Livrable documentaire
- `docs/questions/securite/purge-historique-dump.md`
- `docs/questions/securite/rotation-credentials.md`

## Parallélisable avec
T-002, T-003, T-005, T-041.

## Exécution (2026-10-08, branche `fix/T-001-retrait-dump-index`)

- Commits : `8f2a72b` (retrait du dump de l'index), `2b743b4` (`.gitignore`, contrôle `controle_fichiers_sensibles.sh`, hook délégué, test), puis le commit de documentation.
- Vérifications : `git ls-files backups/` vide ; `git check-ignore` ok ; test pytest `tests/test_controle_fichiers_sensibles.py` (4 passés) ; hook refusant dump et `.env` sur dépôt jetable.
- Constat : dépôt `origin` **public** (`gh repo view`, 2026-10-08). Traité comme fuite dans `purge-historique-dump.md`.
- Reste à faire (hors agent) : réponses écrites du commanditaire (visibilité, purge), propriétaires et dates de rotation, attestation de rotation. La fiche reste « À vérifier » tant que la rotation n'est pas attestée.
