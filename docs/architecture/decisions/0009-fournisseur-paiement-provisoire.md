# ADR 0009 — Fournisseur de paiement provisoire derrière un adaptateur

- **Statut :** Proposée, réversible; aucun merchant account connecté.
- **Date :** 2026-11-02.

## Contexte

Le backend avait des plans et essais, mais pas de snapshots de prix, entitlements
liés aux abonnements, factures API, tentatives ou journal d'événements webhook.
Le marché de lancement n'est pas confirmé et aucun paiement réel n'est autorisé
dans cette tranche.

## Décision proposée

Garder le fournisseur derrière `PaymentProvider` et préparer Flutterwave comme
premier adaptateur envisagé, avec mode `test` par défaut. Pour une hypothèse
Cameroun/Afrique francophone, la doc officielle de Flutterwave liste XAF au
Cameroun et MTN/Orange Money. Ses Payment Plans récurrents imposent le moyen
carte; le Mobile Money devra donc rester manuel ou être reproposé par cycle si
ce flux est confirmé. Ce choix géographique est une inférence réversible,
aucun pays de lancement n'étant arrêté.

Jusqu'à ce qu'un checkout sandbox et une vérification transaction serveur-à-
serveur soient implémentés et revus, l'API ne crée pas de tentative et retourne
`provider_not_configured`. Le webhook authentifié ne fait qu'enregistrer un
digest idempotent et ne règle jamais une facture. Aucun numéro de carte, secret
marchand ou payload complet n'est stocké.

## Conséquences

Une migration additive versionne les prix et ajoute entitlements, tentatives
et événements. Elle rétro-remplit le snapshot initial de chaque plan; les
souscriptions historiques restent attachées au même plan et sont liées à sa
version initiale. Le downgrade supprime seulement les tables/colonnes ajoutées
par cette migration. `OrganizationModule.status` n'est pas interprété comme une
preuve de paiement.

## Sources officielles consultées

- [Flutterwave — Mobile Money francophone](https://developer.flutterwave.com/docs/francophone)
- [Flutterwave — Payment Plans](https://developer.flutterwave.com/docs/payment-plans-1)
- [Flutterwave — Webhooks](https://developer.flutterwave.com/docs/webhooks)
- [Stripe — disponibilité internationale](https://stripe.com/global)
- [Paystack — pays desservis](https://paystack.com/countries)
