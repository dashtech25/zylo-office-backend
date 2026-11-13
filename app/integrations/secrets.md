# Secrets d'intégration (BE-161)

Module : `app/integrations/secrets.py` ; table `secret_integration` (`app/integrations/models.py`, migration `7a2c9d1e4f60`).

## Séparation

- La base ne porte que `referenceSecret` (nom dans le coffre), `version`, `expireAt` (nullable) et `createdAt`.
- La valeur vit dans le coffre (`SecretStore` pour l'instant). Elle n'apparaît dans aucune table, aucun audit, aucune réponse ni aucun journal.

## Fonctions

| Fonction | Rôle | Refus |
|---|---|---|
| `enregistrer_secret` | nouvelle version du secret d'un connecteur, audit sans valeur | 403 / `TENANT_MISMATCH` selon la portée |
| `resoudre_secret_pour_envoi` | valeur courante, réservée à `SERVICE_INTEGRATION` | 403 `PERMISSION_DENIED` pour tout autre appelant ; `TENANT_MISMATCH` ; `SECRET_EXPIRED` (401) |

## Points ouverts

- Coffre persistant non choisi : la valeur est perdue au redémarrage (QE-BE161-01).
- Code local `secret_integration_absent` à ramener au catalogue (QE-BE161-02).
- Les routes n'exposent que les métadonnées (BE-162).
