# Contrat backend — inbox de notifications

**Statut :** infrastructure API livrée; producteurs fonctionnels non raccordés. Ce document ne tranche pas PH-13/Q-29 et ne vaut pas validation d'une politique de notifications.

## Contrat HTTP

Toutes les routes sont sous `/api/v1/notifications` et exigent une session authentifiée ainsi que l'organisation courante (`X-Organization-Id`). Le backend vérifie l'appartenance existante à cette organisation. La lecture est automatiquement filtrée par organisation et utilisateur connecté.

| Méthode/route | Usage | Réponse |
|---|---|---|
| `GET /inbox?limit=20&offset=0&unreadOnly=false` | Liste paginée personnelle dans l'organisation active. `limit` est borné à 1–100; le tri est stable, `createdAt DESC, id DESC`. | `{data: NotificationInboxItem[], meta: {total, limit, offset}}` |
| `GET /inbox/{item_id}` | Détail d'un item appartenant à l'utilisateur courant et à l'organisation active. | `NotificationInboxItem`; 404 identique pour ID absent, autre utilisateur ou autre organisation. |
| `PATCH /inbox/{item_id}/read` | Marque comme lu; répétition idempotente. Aucun archivage/suppression n'est exposé. | Item actualisé; 404 hors portée personnelle. |

`NotificationInboxItem` retourne seulement `id`, `category`, `title`, `body`, `createdAt`, `readAt`. Le destinataire et l'organisation ne sont pas sérialisés. `title`/`body` sont du texte brut; les clients les rendent échappés, jamais comme HTML.

## Écriture interne et idempotence

`app.notifications.service.create_inbox_item` est le seul chemin d'écriture livré. Il n'existe aucune route HTTP de création. Un producteur interne doit fournir explicitement un destinataire déjà membre de l'organisation, un identifiant/type d'événement source, catégorie et contenu. La base garantit une insertion au plus une fois par `(organisation, destinataire, type d'événement, id d'événement)`; une réémission renvoie l'item existant.

À la livraison de cette tranche, **aucun producteur n'appelle cette fonction**. Il n'y a donc pas encore de messages de produit à afficher; une inbox vide est l'état réel, jamais remplie avec du contenu de démonstration. Web Push reste une capacité séparée; aucune préférence, livraison externe ou accusé fournisseur n'est impliqué.

## Limites ouvertes

- PH-13 et Q-29 laissent en suspens taxonomie/catégories, destinataires, canal, consentement/préférences, quiet hours et rétention. Aucun TTL, purge ou archivage automatique n'est introduit.
- Les événements existants `AlertCreated` sont une source candidate mais l'intégration Notifications ↔ Zylo Liquid présente le point ARC-007 ouvert. Elle n'est pas raccordée dans cette tranche. Recommandation: établir un contrat domaine indépendant contenant organisation/scope et destinataires autorisés, puis connecter l'inbox après contre-revue; ne pas ajouter une dépendance de notifications aux modèles métier.
- Les liens profonds vers les modules ne sont pas inclus : les cibles et règles de revalidation d'accès restent à préciser.

## Preuves attendues

Tests ciblés couvrent authentification, liste vide, cloisonnement utilisateur/organisation, 404 anti-énumération, marquage lu idempotent, et déduplication du service interne. L'application de migration doit être vérifiée uniquement sur une base jetable `zylo_t<NNN>_test`; aucun schéma distant ou de production n'est utilisé.
