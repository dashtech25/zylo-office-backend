"""Opérations asynchrones consultables (BE-236).

Rôle : donner à un appelant un `operationId` dès qu'une commande est acceptée, puis lui
permettre de suivre l'état de cette opération jusqu'à son issue, sans jamais le faire
attendre le résultat dans la même requête.

Contenu du package :
- `models.py` : table `operations` (une ligne par opération, rattachée à son tenant) ;
- `service.py` : seules fonctions qui changent l'état d'une opération (création,
  transitions, vérification) et la lecture avec contrôle de droit ;
- `schemas.py` : forme de la réponse HTTP ;
- `router.py` : `GET /api/v1/operations/{operation_id}` ;
- `permissions.py` et `seed.py` : permission de lecture par un non-initiateur.

Machine d'états (invariants) :

    recue --> en_cours --> succes | echec | inconnu
    recue --> echec                       (rejet avant démarrage)
    inconnu --> succes | echec            (seulement après une vérification enregistrée)

`succes` et `echec` sont terminaux. `inconnu` signifie que l'issue n'a pas pu être
établie (résultat incertain) : il n'est jamais présenté comme un échec ni comme un
succès, ni dans la lecture ni dans les transitions.

Droits : l'initiateur lit toujours son opération ; un autre membre de la même
organisation doit détenir `operations.operation.read`. Une opération d'un autre tenant
est introuvable (404), jamais refusée (403), pour ne pas révéler son existence.
"""
