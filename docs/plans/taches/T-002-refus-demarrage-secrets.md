# T-002 : Refuser le démarrage hors développement avec des secrets par défaut

- **Statut** : À vérifier · **Priorité** : P0 · **Vague** : 0 · **Taille** : S · **Dépôt(s)** : backend · **Domaine** : security · **Type** : security
- **Branche suggérée** : `fix/T-002-secrets-demarrage` · **Base de test** : `zylo_t002_test` · **Ports** : back 3102
- **Dépendances** : T-004
- **Décisions requises** : `architecture/environnement-par-defaut.md` (appliquée, à confirmer)

## Objectif
Un démarrage hors environnement explicitement `development` ou `test` est refusé si un secret vaut sa valeur de repli, est trop court, ou si la clé de chiffrement est absente. La valeur par défaut de `ENVIRONMENT` est `production` : une image ou un shell sans variable applique les règles strictes.

## Problèmes résolus
- BCK-002 (P0), ARC-001 (P0), IAM-009 (P0), REV-S-02 (Critique), REV-S-03 (défaut `changeme` de `DATABASE_URL`)

## Dépendances : justification
T-004 (base). T-027 utilise la clé de chiffrement déclarée ici. T-003 et T-005 modifient `config.py` et `conftest.py` : T-002 passe avant elles dans l'ordre des fichiers chauds.

## Fichiers / modules concernés
- `app/core/config.py` : `ENVIRONMENT` par défaut `production` (aujourd'hui `development`, ligne 8) ; validateur `model_validator` ; variable `APP_FIELD_ENCRYPTION_KEY` (obligatoire hors `development`/`test`, longueur minimale)
- `Dockerfile` : `ENV ENVIRONMENT=production` explicite
- `.env.example` : `ENVIRONMENT=development` déclaré pour le dev local
- `tests/test_config_secrets.py` (nouveau)
- `docs/process/configuration.md` (créé)

## Stratégie
1. `ENVIRONMENT` vaut `production` par défaut. Seules les valeurs `development` et `test` autorisent les secrets de repli. Toute autre valeur, absente comprise, applique les règles strictes.
2. Règles : `JWT_SECRET` et `STORAGE_SIGNED_URL_SECRET` refusés s'ils valent la valeur de repli ou font moins de 32 caractères ; `DATABASE_URL` refusée si elle contient le mot de passe de repli ; `APP_FIELD_ENCRYPTION_KEY` obligatoire hors `development`/`test`.
3. Le message d'erreur nomme la variable, jamais sa valeur.
4. Les tests existants déclarent `ENVIRONMENT=test` et des secrets de test explicites (dans `conftest.py`, en coordination avec T-005).

## Tests attendus
- Unitaires : `Settings` avec variable absente et secret de repli : erreur. `ENVIRONMENT=production` et secrets forts : passe. `development` : passe avec repli.
- Démarrage : `ENVIRONMENT` absente, secret de repli : `python -c "import app.main"` sort avec un code non nul.
- Pas de Playwright (aucun parcours métier touché).
- Suite pytest : aucun nouvel échec ; les échecs connus restent ceux de `baseline-tests.md`.

## Critères d'acceptation
- Aucun secret de repli utilisable hors `development` ou `test`, variable absente comprise.
- Le message d'erreur ne contient aucune valeur de secret.
- `docs/process/configuration.md` décrit chaque variable et son obligation.
- La décision d'environnement par défaut est consignée dans `docs/questions/architecture/environnement-par-defaut.md`.

## Risque et retour arrière
Moyen : un environnement qui démarre aujourd'hui avec les valeurs de repli ne démarrera plus, c'est voulu. Retour arrière : revert du commit ; aucune donnée n'est touchée.

## Livrable documentaire
- `docs/process/configuration.md`
- `docs/questions/architecture/environnement-par-defaut.md`

## Parallélisable avec
T-001, T-003, T-005 (après coordination sur `config.py` et `conftest.py`).
