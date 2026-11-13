# Classification et minimisation des données sensibles (BE-174)

Module : `app/securite/classification.py`, table `classification_champ` (`app/securite/models.py`).

## Règles

- Tout champ de premier niveau d'un payload d'événement doit avoir une ligne de classification
  pour son type d'événement. Sinon : `SCHEMA_INVALID`.
- Un numéro de carte (13 à 19 chiffres, valide au sens de Luhn) est refusé dans tout champ
  texte du payload : `SCHEMA_INVALID`, sans écho de la valeur.
- Un champ `public` est visible de tout consommateur du tenant.
- Un autre champ n'est reçu que par un consommateur détenant une permission listée dans
  `consommablePar`. Les autres champs sont expurgés. `consommablePar` NULL : jamais exposé.
- Une sortie vers un autre tenant est refusée : `TENANT_MISMATCH`.

## Non encore branché

`verifier_classification_payload` n'est pas appelé par `enregistrer_evenement` : les événements
de BE-150 et BE-166 publient des champs non déclarés. Le branchement exige de déclarer ces champs
ou d'assouplir CA-1, à trancher (QE-PAR-16).

## Colonnes

- `outbox_evenement.dataClassification` : renseignée à l'écriture depuis l'enveloppe. NULL pour
  les lignes antérieures à la migration `174a0b1c2d3e`.
- `audit_event.dataClassification` : déjà présente (BE-007), non alimentée par BE-174.
