# Contrat d'usage de `files` par `zylo_liquid`

- **Date** : 2026-10-09 (T-036, ARC-005/006 : frontières entre capacité et module).
- **Capacité** : `app/files/` (propriétaire technique : le paquet, voir `capacites-proprietaires.md` §1).
- **Source de vérité** : contrats `zylo-liquid-files-through-service-only` et `files-never-imports-zylo-liquid` dans `.importlinter`.

## 1. Ce que `zylo_liquid` peut faire

| Besoin | Import autorisé | Exemple actuel |
|---|---|---|
| Créer un document lié à une action métier déjà autorisée | `app.files.service` | `generate_purchase_order_document` appelle `create_document_for_trusted_caller` (`app/modules/zylo_liquid/service.py`) |
| Créer un document à l'initiative d'un utilisateur (upload) | `app.files.service.create_document` (contrôle `DOCUMENT_CREATE`) | à utiliser pour tout nouvel upload |
| Lier un document à une entité, lister, compter, obtenir l'URL, supprimer | `app.files.service` (`create_document_link`, `list_document_links_for_entity`, `count_documents_by_entity`, `get_document_download_url`, `delete_document`) | - |
| Typer une réponse | `app.files.schemas` (`DocumentResponse`, `DocumentLinkResponse`) | `zylo_liquid/router.py`, `zylo_liquid/service.py` |
| Déclarer les permissions Files dans les rôles par défaut | `app.files.permissions` | `zylo_liquid/seed.py`, `zylo_liquid/roles_seed.py` |

## 2. Ce que `zylo_liquid` ne fait jamais

- Importer `app.files.models` (`Document`, `DocumentLink`), ni lire ou écrire ces tables par une requête maison.
- Appeler `create_document_for_trusted_caller` pour un upload libre : cette variante ne contrôle pas `DOCUMENT_CREATE`. Elle n'est réservée qu'aux documents **dérivés** d'une action métier dont la permission a déjà été vérifiée (ex. bon de commande, `PURCHASE_ORDER_MANAGE`).
- Passer par `app.files.service` pour contourner l'autorisation d'un tiers : l'acteur (`actor_user_id`) est toujours transmis.
- Stocker dans `Document` des informations métier propres à `zylo_liquid` : seuls `linked_entity_type` et `linked_entity_id` relient le document au métier.

## 3. Sens inverse

`files` ne dépend jamais de `zylo_liquid` (contrat `files-never-imports-zylo-liquid`). Si `files` a besoin d'une information métier, c'est l'appelant qui la fournit en argument.

## 4. Ajout d'un nouveau consommateur

Un deuxième module métier (ex. `zylo_tanker`) suit le même contrat. Il faut :

1. vérifier la permission de l'action métier avant l'appel ;
2. appeler `app.files.service` (jamais les modèles) ;
3. étendre le contrat `zylo-liquid-files-through-service-only` à son paquet (ajouter `app.modules.<nouveau>` aux `source_modules`) dans la même PR.

## 5. Limite connue

`zylo_liquid` importe `app.files.schemas` et `app.files.permissions`, deux types et constantes publics : c'est voulu. Aucun contrat n'interdit encore l'appel direct d'une fonction privée (`_check_org_scope`) de `app.files.service` ; la revue de code couvre ce point.
