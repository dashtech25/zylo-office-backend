# Promotion de release (BE-250)

Module `app/release/`. Point d'entrée : `app/release/service.py`. Table : `release_records`
(migration `a250b1c2d3e4`, réversible).

## Principe

Un artefact est versionné et identifié par son hash SHA-256. Il est validé une fois, puis
promu tel quel d'un environnement à l'autre : aucune reconstruction n'est faite à la promotion.
Chaque présence d'une version dans un environnement est une ligne de `release_records`, avec
la provenance (référence source, SBOM), les résultats de gates, le demandeur, l'approbateur
et l'horodatage.

## Opérations

| Fonction | Rôle | Refus |
|---|---|---|
| `enregistrer_release` | enregistre la validation d'un artefact | 409 `release.version.existante` |
| `promouvoir_release` | copie la release source vers un environnement | 403 sans permission ou approbation par le demandeur ; 409 gate non réussi ou version déjà présente ; 404 source absente |
| `identifier_rollback` | renvoie la release antérieure compatible | renvoie `None` si aucune cible |

## Règles

- Permission de promotion : `release.promotion.executer` (`app/release/permissions.py`).
- Approbation distincte : l'approbateur ne peut pas être le demandeur.
- Gates : chaque gate requis doit valoir `reussi`. La liste des gates requis est passée par
  l'appelant ; elle n'est pas codée dans le service.
- Compatibilité de rollback : `config_version <= config_version_supportee`.

## Questions ouvertes

- Rôle « responsable livraison » et câblage IAM (seed, route) : non livrés par BE-250. Tant qu'ils
  manquent, aucun utilisateur ne peut promouvoir.
- Nom de table : la définition impose `release_records` (snake_case), alors que la règle
  générale des tables est camelCase. Retenu : définition.
- Les routes d'exploitation ne sont pas dans BE-250 (aucune route prévue).
