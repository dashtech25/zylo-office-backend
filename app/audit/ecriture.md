# Écriture d'audit fail-closed (BE-153)

Module : `app/audit/ecriture.py`. Tests : `tests/test_be153_ecriture_audit.py`.

## Quand l'utiliser

Un service métier qui modifie une donnée sensible appelle `executer_mutation_sensible`.
Une lecture qui doit être journalisée sans bloquer la réponse appelle
`executer_lecture_non_sensible`.

## Garanties

| Cas | Comportement | Code |
|---|---|---|
| Émetteur non authentifié (`identite=None`) | Refus avant toute écriture | 403 `PERMISSION_DENIED` |
| `organization_id` différent de celui de l'identité | Refus avant toute écriture | 404 `TENANT_MISMATCH` |
| Échec de l'écriture d'audit lors d'une mutation | Mutation annulée (SAVEPOINT) | 500 `AUDIT_WRITE_FAILED` |
| Échec de l'écriture d'audit lors d'une lecture | Valeur rendue, échec journalisé | aucun |

## Transaction

Mutation et audit sont dans un SAVEPOINT (`begin_nested`). L'appelant fait le `commit()`.

## Points ouverts

- Tolérance des lectures : recommandation appliquée, décision humaine QE-PAR-05.
- Code exact du refus sans identité : PERMISSION_DENIED retenu (QE-PAR-01).
