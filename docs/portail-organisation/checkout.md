# Session de paiement du portail (BE-110)

Routes (domaine facturation, sous `/api/v1/organizations`, code dans `app/billing/checkout_sessions/`) :

- `POST /{organization_id}/checkout-sessions` : crée une session `open` (201). En-tête `Idempotency-Key` obligatoire. Corps : `planCode`, `scenario`, `payerId`, `consentTextVersion`.
- `GET /{organization_id}/checkout-sessions/{session}` : lit l'état durable (200). La query string n'est jamais lue.

Réponse : `id`, `quoteId`, `status`, `version`, `createdAt`, `offre` (contenu figé de l'instantané de version d'offre capturé au devis, BE-075).

## Enchaînement d'une création

1. Devis (`creer_devis`, BE-077) : capture de l'offre et résolution du prix.
2. Acceptation du devis (`accepter_devis`).
3. Consentement versionné enregistré dans `consent_record` (BE-076) pour le compte payeur, avec la personne qui agit.
4. Checkout `open` (`creer_checkout`, BE-081).
5. Événement `CheckoutSessionCreated` écrit dans l'outbox, puis validé.

Un rejeu avec la même clé et la même charge renvoie la session initiale sans nouvel effet. La même clé avec une autre charge renvoie 409 `DUPLICATE`.

## Codes de refus

| Cas | HTTP | Code |
|---|---|---|
| Pas de session | 401 | garde d'authentification (`get_current_user`) |
| Permission `billing.checkout.purchase` absente (POST) | 403 | `permission_denied` |
| Permission `billing.subscription.read` absente (GET) | 403 | `permission_denied` |
| Organisation hors appartenance ou inexistante | 404 | `organization_not_found` |
| Session d'un autre tenant ou inconnue | 404 | `checkout_session_not_found` |
| `consentTextVersion` absent ou vide | 400 | `consent_required` ; rien n'est écrit |
| En-tête `Idempotency-Key` absent | 422 | validation du socle (`require_idempotency_key`) |
| Même clé, charge différente | 409 | `DUPLICATE` |

## Écarts avec la fiche

- Permissions écrites `billing:purchase` et `billing:read` : retenues `billing.checkout.purchase` et `billing.subscription.read` (format `domaine.entite.action`).
- Aucune table ni migration : la session est le checkout de BE-081 (table propriétaire BE-202, QE-POR-29). L'offre figée est lue par le devis (`planVersionSnapshotId`) ; la version de consentement est dans `consent_record`, non recopiée sur le checkout.
- Pas de transaction unique : les services existants commit à chaque étape. Un échec après l'acceptation du devis laisse un devis `accepted` sans checkout ; la clé est libérée.
- Absence d'en-tête d'idempotence : 422 (convention du socle) et non 400.
