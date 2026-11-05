# Webhook entrant d'un connecteur (BE-163)

Route : `POST /api/v1/integrations/webhooks/{connecteur_id}`. Pas d'authentification
utilisateur : l'émetteur externe s'authentifie par signature. Code : `app/integrations/webhooks.py`.

## En-têtes

| En-tête | Rôle |
|---|---|
| `X-Zylo-Signature` | `t=<unix>,v1=<hex>` : HMAC-SHA256 de `"<t>." + corps brut`, clé = secret du connecteur |
| `X-Organization-Id` | Tenant adressé. Doit être celui du connecteur, sinon `404` TENANT_MISMATCH |

## Corps

Objet JSON avec `idExterne` (chaîne non vide, 255 caractères au plus) et `typeEvenement`
(chaîne non vide). Le reste n'est pas stocké.

## Réponses

| Cas | Statut | Code |
|---|---|---|
| Nouvel événement | `202` | corps `{webhookId, statut}` |
| Doublon de `(connecteur, idExterne)` | `200` | `REPLAY_DUPLICATE`, pas de nouvelle ligne |
| Signature absente, mal formée ou fausse | `401` | `SIGNATURE_INVALID` |
| Horodatage hors fenêtre anti-rejeu | `409` | `REPLAY_DUPLICATE` |
| Schéma invalide | `422` | `SCHEMA_INVALID` |
| Tenant différent du connecteur | `404` | `TENANT_MISMATCH` |
| Fenêtre anti-rejeu non configurée | `503` | `webhook_fenetre_non_configuree` |

Dans les cas `401`, `404`, `409` et `422`, rien n'est écrit.

## Configuration

- `WEBHOOK_FENETRE_ANTI_REJEU_SECONDS` : fenêtre de tolérance de l'horodatage (QE-PAR-09).
  Pas de valeur par défaut.
- Secret du connecteur : `enregistrer_secret` (BE-161) ; un secret expiré renvoie `SECRET_EXPIRED`.

## Table

`webhook_recu` : voir `app/integrations/models.py` (`WebhookRecu`). Unicité `(connecteurId, idExterne)`.
