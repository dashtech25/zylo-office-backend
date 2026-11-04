# Console support opérateur (lecture seule)

Précondition: ajouter les UUID de comptes opérateur dédiés à
`OPERATOR_READ_USER_IDS` (liste séparée par des virgules) puis redémarrer le
processus backend. Valeur absente ou vide = refus par défaut. Une configuration
mal formée ne peut pas accorder d'accès. Il ne s'agit pas d'un rôle tenant ni
d'une route d'impersonation; la capability est globale, explicite et en lecture
seule.

Toutes les routes sont préfixées par `/api/v1/operator`. Elles exigent une
session authentifiée et l'allowlist opérateur. Les erreurs utilisent
`{error:{code,message,field_errors,details},request_id}`.

- `GET /organizations?limit=20&offset=0` — liste paginée des identifiants,
  noms, slugs et états des organisations non supprimées.
- `GET /organizations/{organization_id}` — aperçu minimal d'une organisation,
  son abonnement courant et le statut des modules. Aucun utilisateur, email,
  facture ou paiement n'est inclus.
- `GET /health` — état de disponibilité de la base et request ID courant.
- `GET /requests/{request_id}` — traces persistées minimales provenant des
  lignes d'audit qui contiennent un request ID ou des webhooks de paiement.
  Aucun summary d'audit, chemin de requête, payload ni donnée d'identité n'est
  exposé. Les journaux HTTP généraux ne sont pas persistés pour cette recherche;
  `found:false` signifie qu'aucune trace persistée n'a été trouvée.
- `GET /payment-events/{event_id}` — fournisseur, type d'événement, request ID,
  outcome et horodatages. Ni digest ni payload ne sont exposés.

Les lectures opérateur n'écrivent pas dans l'audit métier, afin de garder ces
routes strictement read-only. Elles ne contournent pas le périmètre tenant des
routes normales et ne permettent pas d'agir sous l'identité d'un autre membre.
