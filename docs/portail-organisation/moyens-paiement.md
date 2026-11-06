# Moyens de paiement (BE-116)

Routes (domaine facturation, sous `/api/v1/organizations`) :

- `POST /{organization_id}/billing/payment-methods` : ajoute une référence de token et la sélectionne (201). La méthode précédente est désélectionnée, non supprimée.
- `POST /{organization_id}/billing/payment-methods/{method}/select` : sélectionne une méthode de l'organisation (200) ; les autres sont désélectionnées.

Corps (les deux routes) : `motDePasse` (mot de passe courant, réauthentification) ; pour l'ajout, `tokenReference` (référence de token fournie par le prestataire).

Réponse : `id`, `selected`, `createdAt`. La valeur du token n'est jamais renvoyée.

## Codes de refus

| Cas | HTTP | Code |
|---|---|---|
| Pas de session | 401 | garde d'authentification (`get_current_user`) |
| Permission `billing.payment_method.manage` absente | 403 | `permission_denied` |
| Organisation hors appartenance ou inexistante | 404 | `organization_not_found` |
| Méthode inconnue ou d'une autre organisation (sélection) | 404 | `payment_method_not_found` |
| PAN ou CVV dans le corps (clé de carte, ou suite de 13 à 19 chiffres) | 400 | `card_data_refused` ; rien n'est lu ni écrit |
| Mot de passe absent ou faux | 403 | `reauthentification_requise` |

## Données et événement

- Table `payment_method_reference` : `id`, `organizationId`, `tokenReference`, `selected`, `createdAt`. Index partiel unique : une seule méthode sélectionnée par organisation.
- Chaque changement émet `PaymentMethodChanged` (payload : `paymentMethodId`, `action` = `added` ou `selected`, `selected`) dans la même transaction que l'écriture. Le token n'entre pas dans l'événement.

## Écarts avec la fiche

- Permission écrite `billing.payment_method.manage` (format `domaine.entite.action`), et non `billing:payment-method:manage`.
- Réauthentification par mot de passe courant ; le délai de PH-08 n'est pas repris.
- Détection de PAN : toute suite de 13 à 19 chiffres est refusée ; c'est un choix de sûreté.
