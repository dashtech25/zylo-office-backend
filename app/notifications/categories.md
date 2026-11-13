# Catégories et règles de notification (BE-167)

Module : `app/notifications/categories.py`. Tables : `categorie_notification`, `regle_notification`
(migration `7c3e9d2b4a10`).

## Modèle

- `categorie_notification` : clé `code`, `libelle`, `audienceRegle` (obligatoire, non vide),
  `canalDefaut` (NULL par défaut), `actif` (vrai à la création).
- `regle_notification` : `evenementType` relié à `categorieCode` (unicité du couple),
  `audience` figée à l'écriture et résolue en destinataires seulement à l'envoi (BE-169).

## Règles

| Règle | Comportement |
| --- | --- |
| CA-1 | Catégorie sans audience : `422` SCHEMA_INVALID, rien d'écrit. CHECK en base en second rempart. |
| CA-2 | Type d'événement absent de `TYPES_EVENEMENT_CONNUS` : `422` SCHEMA_INVALID. Ensemble vide tant que le catalogue BE-176 n'est pas livré (refus fermé). |
| CA-3 | Création ou modification d'une règle sans autorité plateforme (`has_platform_authority`) : `403` PERMISSION_DENIED. |
| CA-4 | Aucun canal présumé. `canal_defaut_categorie` renvoie `NON DÉFINI` si le canal est absent. |

## Points ouverts

- QE-PAR-03 : périmètre exact des droits de configuration (le refus fermé plateforme est appliqué).
- QE-PAR-04 : sémantique du canal par défaut (NULL accepté, aucune valeur présumée).
- BE-176 : source du catalogue des types d'événement, à brancher sur `TYPES_EVENEMENT_CONNUS`.
