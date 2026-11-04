# Facturation et paiements (socle P0)

Routes préfixées `/api/v1`. Les succès ne sont pas globalement enveloppés;
les listes de factures utilisent `{data,meta:{total,limit,offset}}`. Les
erreurs suivent `{error:{code,message,field_errors,details},request_id}`.

## Contrat disponible

- `GET /billing/plans` — liste historique étendue avec `version`,
  `amountMinor`, `entitlementCodes`; les champs historiques restent présents.
- `GET /billing/organizations/{organization_id}/subscription` — abonnement
  trial/actif courant et ses entitlements, ou `null`.
- `GET /billing/organizations/{organization_id}/invoices?limit=20&offset=0` —
  factures de l'organisation, paginées.
- `POST /billing/organizations/{organization_id}/invoices` avec
  `Idempotency-Key` et `{subscriptionId}` — crée une facture pending, capture
  le montant et la devise de la version du plan. Une répétition avec la même
  clé et la même souscription retourne la facture déjà créée.
- `GET /billing/organizations/{organization_id}/invoices/{invoice_id}/payment-attempts`
  — tentatives pour cette facture.
- `POST` sur la même route avec `Idempotency-Key` — répond actuellement
  `503 provider_not_configured`; aucune tentative n'est persistée et aucun
  fournisseur n'est appelé.
- `GET /billing/payment-provider` — expose `provider`, `mode`,
  `configured` et `checkoutAvailable` pour l'interface.
- `POST /billing/webhooks/flutterwave` — protégé par `verif-hash` comparé en
  temps constant au secret `FLUTTERWAVE_WEBHOOK_SECRET`. Les événements sont
  dédupliqués sur `(provider,eventId)` et seul un digest du corps est conservé.
  Une répétition identique reçoit `duplicate:true`; le même identifiant avec
  un digest différent reçoit `409 webhook_event_conflict`.
  L'événement est enregistré comme `recorded_unverified`; il ne règle aucune
  facture et n'active aucun abonnement. Sans secret, réponse 503; signature
  incorrecte, 401.

Les mutations d'abonnement/facture/paiement sont derrière
`billing.subscription.manage`; la lecture est réservée aux membres du tenant.
Une `Idempotency-Key` est un UUID généré une fois par intention utilisateur et
réutilisé uniquement pour retenter la même requête.

## Modèle et limites actuelles

`PlanVersion` conserve les versions immuables de montant en unités mineures,
devise, période et codes d'entitlement. Les souscriptions pointent vers leur
version; les factures copient le montant/devise. Les lignes de prix historiques
sont rétro-remplies par la migration. `Invoice.amountMinor` est rétro-rempli
par copie entière de `amountCents` sans conversion liée à la devise; les valeurs
NULL historiques restent NULL. `publish_plan_version` publie un nouveau
snapshot; les souscriptions existantes ne sont pas réécrites.

Les entitlements explicites du module sont vérifiés à l'activation et à
l'ouverture. En absence de ligne d'entitlement, l'accès historique reste
autorisé; un entitlement explicitement inactif/expiré/bloqué ou attaché à un
abonnement expiré/annulé refuse l'accès. Un entitlement actif ne marque pas le
module comme installé: `OrganizationModule.status` reste une décision séparée
et ne prouve pas le paiement. Aucun champ de carte n'est stocké. Le provider
Flutterwave est un adaptateur non réseau et demeure
désactivé, même si une clé de test apparaît dans l'environnement, jusqu'à ce
que checkout sandbox et vérification serveur-à-serveur soient implémentés.

La migration `c0b7d9a2e511` est additive et réversible. Son downgrade supprime
les tables versionnées/tentatives/événements créées par cette tranche et les
colonnes ajoutées; les trois tables historiques Plan/Subscription/Invoice
restent présentes.

## Choix provisoire du fournisseur

Recommandation réversible: Flutterwave comme premier adaptateur pour une
hypothèse de marché Cameroun/Afrique francophone, car sa documentation liste
XAF au Cameroun et MTN/Orange Money. C'est une inférence, pas une décision sur
le pays de lancement. La documentation Flutterwave précise que ses Payment
Plans récurrents imposent le moyen carte; un renouvellement Mobile Money
devrait donc rester manuel ou être redemandé à chaque cycle jusqu'à validation
d'un parcours adapté. Paystack publie une liste de pays opérés qui n'inclut pas
le Cameroun; la liste de disponibilité Stripe consultée n'inclut pas non plus
le Cameroun. Le provider est derrière `PaymentProvider` pour pouvoir être
remplacé sans migration des abonnements.

Sources officielles consultées le 2 novembre 2026:

- [Flutterwave — Mobile Money francophone](https://developer.flutterwave.com/docs/francophone)
- [Flutterwave — Payment Plans](https://developer.flutterwave.com/docs/payment-plans-1)
- [Flutterwave — Webhooks et `verif-hash`](https://developer.flutterwave.com/docs/webhooks)
- [Stripe — disponibilité internationale](https://stripe.com/global)
- [Paystack — pays desservis](https://paystack.com/countries)
