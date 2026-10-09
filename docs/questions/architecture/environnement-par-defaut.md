# Environnement par défaut : fail-closed

- **Question** : quelle valeur de `ENVIRONMENT` est appliquée quand la variable est absente, et quels secrets de repli sont alors autorisés ?
- **Tâches concernées** : T-002, T-015, T-027
- **Contexte** : `app/core/config.py`, ligne 8, fixe `ENVIRONMENT: str = "development"` (vérifié). Le `Dockerfile` ne définit pas `ENVIRONMENT` (vérifié). Une image lancée sans variable démarre donc avec les secrets de repli.
- **Options** :
  - A. Défaut `development` (état actuel) : rejeté, il autorise les secrets de repli par omission.
  - B. Défaut `production`, `development` et `test` déclarés explicitement (recommandation).
  - C. Aucun défaut : le démarrage échoue si la variable manque. Plus strict, mais casse les lancements locaux sans configuration.
- **Recommandation vérifiée** : option B, et `ENV ENVIRONMENT=production` dans le `Dockerfile`. Vérification : la constante et l'absence de `ENV` ont été relues dans les deux fichiers.
- **État** : Appliquée (décision du coordinateur, à confirmer par le client)
- **Mise en œuvre (T-002)** : `ENVIRONMENT` vaut `production` par défaut ; seule la valeur `development` autorise les replis. `APP_FIELD_ENCRYPTION_KEY` est exigée hors `development` et `test` (fiche T-002, stratégie point 2). `test` et toute valeur inconnue appliquent les règles strictes (plus strict que la recommandation B, qui listait aussi `test` parmi les environnements à replis ; `tests/conftest.py` fournit des secrets explicites). Le `Dockerfile` déclare `ENV ENVIRONMENT=production`. Détail : `docs/process/configuration.md`.
