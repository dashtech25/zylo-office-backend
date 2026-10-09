# Appel direct ou événement en mémoire

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

## 4. Appel direct vs événement en mémoire

Deux patrons de communication entre modules, jamais un troisième (pas
d'appel HTTP interne entre modules du même process, pas de queue externe
pour une simple notification interne) :

**Appel direct** (`app.x.service.fn(...)`) — quand l'appelant a besoin
d'une réponse pour continuer son traitement dans la même requête/transaction
(id créé, succès/échec, URL signée...). C'est un couplage assumé et normal :
l'appelant connaît l'API publique de l'appelé.
> Exemple en place : `generate_purchase_order_document` a besoin de l'id du
> `Document` créé pour construire la réponse — appel direct à
> `app.files.service.create_document`.

**Événement en mémoire** (`publish("NomEvenement", payload)`) — quand le
code signale un fait qui vient de se produire, sans savoir ni se soucier de
qui réagit (zéro, un ou plusieurs abonnés, aujourd'hui ou demain). L'émetteur
ne référence jamais le module abonné.
> Exemple en place (Phase 5) : la détection d'arrêt non qualifié dans
> `location` publie `TruckStopUnqualified` (`app.shared.events.publish`)
> au lieu d'appeler directement `app.alerts.service.upsert_active_alert`
> comme le faisait la Phase 3. `alerts` s'abonne à cet événement via
> `handle_truck_stop_unqualified` — inscription faite dans `app/main.py`
> (le point de composition central, le seul endroit autorisé à faire se
> connaître deux modules qui, sinon, n'ont plus besoin de s'importer).
> `location` n'importe plus `app.alerts` du tout — si demain un second
> module veut aussi réagir à un arrêt non qualifié (ex. notifications), il
> s'abonne au même événement sans que `location` change une ligne.

Mécanique (Phase 5) : `app/shared/events.py` expose `subscribe(event_name,
handler)` / `publish(event_name, payload)`. Les handlers s'exécutent après
le commit de la transaction qui déclenche l'événement (jamais avant — un
handler ne doit jamais voir un état non committé).

**Règle de décision courte** : besoin du retour pour continuer → appel
direct. Simple signal, nombre de consommateurs variable → événement. Dans le
doute, commencer par un appel direct (plus simple, plus traçable) et ne
migrer vers un événement que lorsqu'un deuxième consommateur réel apparaît
— ne pas anticiper des abonnés hypothétiques.
