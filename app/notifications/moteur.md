# Moteur de notification (BE-169)

Module : `app/notifications/moteur.py`. Table : `notification` (migration `9a4f1c6d2e75`).
Entrée unique : `produire_notifications`. Le moteur ne livre rien : la livraison par canal
relève de BE-170, qui fait évoluer `statut` vers `envoyee` ou `echec`.

## Entrée

| Paramètre | Rôle |
| --- | --- |
| `eventId` | Événement d'origine ; clé de déduplication avec la catégorie et le destinataire |
| `evenementType` | Type d'événement, cherché dans `regle_notification` |
| `tenantId` | Organisation de l'événement ; seule son audience est résolue |
| `producteur` | Utilisateur qui produit l'événement ; `None` est refusé |
| `permissionConsultation`, `sujetType`, `sujetId`, `sujetTenantId` | Droit de consulter le sujet, passé à `decide` (BE-226) |

## Règles

| Règle | Comportement |
| --- | --- |
| CA-1 | Une ligne `en_attente` par membre éligible et consentant de l'audience, résolue à l'envoi |
| CA-2 | Non éligible (compte non `active` ou supprimé) ou désinscrit (BE-168) : ligne `supprimee`, motif `CONSENT_SUPPRESSED` |
| CA-3 | Producteur sans droit de consulter le sujet : `403` PERMISSION_DENIED, aucune écriture |
| CA-4 | Rejeu du même événement : `ON CONFLICT DO NOTHING` sur `(eventId, categorieCode, destinataireId)` ; seules les lignes nouvelles sont renvoyées |
| CA-5 | Audience lue dans le tenant de l'événement uniquement |

Audience connue : `membres_organisation`. Une autre référence lève `422` SCHEMA_INVALID.

## Points ouverts

- QE-PAR-27 : le droit de consulter le sujet est porté par `decide` (BE-226) ; le moteur ne
  réimplémente aucune règle d'accès. La permission exacte est fournie par le producteur.
- « Éligible » n'est pas défini dans la source. Retenu : compte `active` et non supprimé.
- CA-2 donne le même motif `CONSENT_SUPPRESSED` à « non éligible » et à « désinscrit ».
  Le motif distinct pour un compte non éligible reste à trancher.
- Table `notification` sans colonne de tenant : le tenant reste celui de l'événement d'origine.
