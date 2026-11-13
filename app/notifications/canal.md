# Adaptateur de canal et résultat de livraison (BE-170)

Module : `app/notifications/canal.py`. Table : `livraison` (migration `c4d8e1f2a903`).
Le module définit l'interface d'un canal et trace chaque tentative. Il ne choisit aucun
fournisseur : le canal est un nom opaque, et aucun canal n'est présumé (QE-PAR-04).

## Interface

| Élément | Rôle |
| --- | --- |
| `AdaptateurCanal.livrer(message)` | Remet un `MessageLivraison` et renvoie un `ResultatLivraison` |
| `enregistrer_adaptateur` / `retirer_adaptateur` | Registre en mémoire, par nom de canal |
| `livrer_notification` | Tente la remise d'une notification éligible et trace la tentative |
| `enregistrer_resultat` | Enregistre un résultat reçu d'un canal (rebond tardif, plainte) |

## Résultats

| Résultat | Statut de la notification | Effet |
| --- | --- | --- |
| `accepte` | `envoyee` | Pris en charge par le canal |
| `livre` | `envoyee` | Remise confirmée |
| `retarde` | `en_attente` | Nouvelle tentative à `prochaineTentativeAt` |
| `rebond` | `echec` | Arrête les envois au destinataire sur la catégorie |
| `plainte` | `echec` | Arrête les envois au destinataire sur la catégorie |
| `echec` | `echec` | Échec de cette tentative, sans arrêt |

## Erreurs

| Cas | Code | Statut HTTP |
| --- | --- | --- |
| Canal absent ou indisponible (tentative tracée `retarde`) | CHANNEL_UNAVAILABLE | 503 |
| Panne de l'adaptateur (exception autre que `AppError`, tentative tracée `retarde`, sans détail interne) | CHANNEL_UNAVAILABLE | 503 |
| Notification non éligible, ou destinataire déjà arrêté sur la catégorie | PERMISSION_DENIED | 403 |
| Canal inconnu ou résultat hors énumération | SCHEMA_INVALID | 422 |

## Points ouverts

- QE-PAR-04 : le canal n'est pas défini. La colonne `canal` est une chaîne libre, sans liste.
- QE-PAR-01 : le mapping HTTP reprend la recommandation appliquée de la définition.
- Le délai de nouvelle tentative (`DELAI_NOUVELLE_TENTATIVE`, 5 minutes) est provisoire ;
  le backoff réel relève de BE-164.
- Le destinataire réel (adresse) n'est jamais transmis ni journalisé par ce module (CA-4).
