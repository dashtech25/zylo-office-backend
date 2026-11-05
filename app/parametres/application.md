# Application, défaut et restauration des paramètres (BE-157)

Module : `app/parametres/application.py`. Permission : `app/parametres/permissions.py`
(`parametres.setting.apply`), enregistrée par `app/parametres/seed.py`.

## Opérations

| Fonction | Effet |
|---|---|
| `appliquer_valeur` | nouvelle version appliquée avec la valeur donnée |
| `restaurer_version` | nouvelle version appliquée recopiant la valeur d'une version antérieure |
| `retablir_defaut` | nouvelle version appliquée avec `defaultValue` de la définition |

Chaque opération : une seule version appliquée par (clé, portée, scopeId) ; la précédente passe
à `applied = false` (seul ce drapeau change) ; une entrée d'audit `EVT-SET-01` est écrite dans le
même savepoint (BE-153). L'appelant fait le `commit()`.

## Erreurs

| Cas | Code | Statut | Écriture |
|---|---|---|---|
| organisation visée autre que celle de l'identité | `TENANT_MISMATCH` | 404 | aucune |
| identité absente | `PERMISSION_DENIED` | 403 | aucune |
| permission `parametres.setting.apply` absente | `PERMISSION_DENIED` | 403 | aucune |
| clé non déclarée, version source inconnue, raison vide | `SCHEMA_INVALID` | 422 | aucune |
| échec d'écriture d'audit | `AUDIT_WRITE_FAILED` | 500 | annulée (savepoint) |

## Audit

Action `parametre.valeur.appliquer`, entité `setting_value`. Détail : `evenement` (`EVT-SET-01`),
`cle`, `version`, `portee`, `scopeId`, `operation` (`application`, `restauration`, `defaut`),
`clesModifiees`, `diff` (avant/après ; masqué pour un paramètre `sensitive`).

## Points ouverts

- QE-PAR-03 : qui détient `parametres.setting.apply` (aucun rôle ne la reçoit par défaut) ;
- nom de l'action d'audit et forme du diff : non tranchés par la définition ;
- code d'erreur « introuvable » absent du catalogue BE-151 : `SCHEMA_INVALID` employé.
