# Tests de résilience (BE-258)

Module de tests qui vérifient la reprise et l'absence de corruption dans trois situations :

| Critère | Fichier | Ce qui est vérifié |
|---|---|---|
| CA-1 | `test_be258_ca1_migration_interrompue.py` | Une migration Alembic interrompue à chaque étape est annulée proprement, puis reprise jusqu'à la tête sans table en double. La chaîne est synthétique (table de version `alembic_version_be258`), jamais celle du dépôt. |
| CA-2 | `test_be258_ca2_replay_sans_doublon.py` | Le replay de la file de lettres mortes (BE-235) ne produit ni second effet, ni nouvelle entrée DLQ. |
| CA-3 | `test_be258_ca3_panne_dependance.py` | Une panne d'adaptateur de canal (BE-170) donne `CHANNEL_UNAVAILABLE` (503) et une tentative `retarde`, sans fuite du détail interne. |
| CA-4 | `test_be258_ca4_resultats_versionnes.py` | Chaque scénario a un résultat versionné dans `resultats/<scénario>.json`. |

## Exécution

Base de test jetable uniquement (`zylo_t258_test` pour ce lot), comme les autres tests :

```
export TEST_DATABASE_URL=...   # base zylo_t<NNN>_test
python -m pytest tests/resilience -q
```

Les tests de ce module créent et suppriment leurs propres tables (préfixe `be258_`) et ne touchent
pas aux tables des migrations du dépôt.

## Résultats versionnés

`resultats/BE258-CAn.json` contient l'identifiant du scénario, sa version (entier), le fichier de test,
le résultat de la dernière exécution verte et les fonctions de test qui le couvrent. Mettre à jour la
version et le résultat quand le scénario change.
