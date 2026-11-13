# Rollback et compensation (BE-252)

Module `app/release/compensation.py`. Table : `compensations` (migration `b252c3d4e5f6`,
réversible). Droit de déclenchement : `release.compensation.executer` (`app/release/permissions.py`).

## Deux mécanismes, deux effets

| Mécanisme | Ce qu'il fait | Ce qu'il ne fait pas |
|---|---|---|
| Rollback du binaire (`identifier_rollback`, BE-250) | Identifie la release antérieure à redéployer, dont la configuration est compatible | Ne restaure aucune donnée |
| Compensation (`demander_compensation` / `executer_compensation`) | Annule l'effet d'une mutation asynchrone déjà produite, par une action explicite | Ne réécrit pas l'historique et ne remonte pas le temps |

## Limite documentée

Revenir à un binaire antérieur ne restaure pas les données écrites par la version défaillante.
Un schéma de données migré par la version v2 reste en place après le retour à v1. Restaurer
un effet exige une compensation explicite, déclenchée par une personne habilitée, avec une
action qui sait annuler cet effet précis. Le test `test_ca2_rollback_du_binaire_ne_restaure_pas_les_donnees`
fixe ce comportement.

## Idempotence et absence de doublon

- La clé `cle_idempotence` est unique. Redemander la même compensation renvoie la ligne existante.
- `executer_compensation` verrouille la ligne (`FOR UPDATE`). Une compensation `realisee` n'est
  jamais rejouée : deux exécutions produisent un seul effet.
- Une action absente du registre fourni par l'appelant donne 409 sans modifier la ligne.

## Droits

| Opération | Refus |
|---|---|
| Demande sans `release.compensation.executer` | 403 `release.compensation.refusee` |
| Approbateur identique au demandeur | 403 `release.compensation.approbation.non_distincte` |
| Compensation inconnue à l'exécution | 404 `release.compensation.introuvable` |
| Action inconnue | 409 `release.compensation.action.inconnue` |

La permission n'est pas encore semée (aucune route en BE-252) : personne ne peut déclencher
une compensation tant que le câblage IAM n'est pas livré.
