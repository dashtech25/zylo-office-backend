# Flux réseau autorisés et isolement des plans (BE-254)

Document de module. Code : `app/securite/flux_reseau.py`. Source : SEC-06 de
`00-pilotage/architecture-fondation/exigences-exploitation-securite-qualite.md`.

Version de la matrice : **2026-11-05.1** (`VERSION_MATRICE`). Toute modification de la
matrice ou de la liste de sorties incrémente cette version et ce document.

## Principes

- Refus par défaut : un flux absent de la matrice est refusé (`flux_non_liste`).
- Un flux est unidirectionnel ; le port est celui de destination.
- Trois règles passent avant la matrice et ne se lèvent par aucune ligne :
  - le plan opérateur n'est jamais joignable depuis Internet, le point d'entrée public
    ou une intégration externe (`plan_operateur_inaccessible`) ;
  - les données d'un tenant ne sont jamais joignables par un autre tenant (`tenant_croise`) ;
  - les métadonnées cloud sont refusées depuis toute source (`metadonnees_interdites`).

## Zones

| Zone | Rôle |
|---|---|
| `internet` | Clients publics, hors contrôle de Zylo |
| `entree_publique` | Point d'entrée HTTPS, seul exposé publiquement |
| `application` | API Zylo Office |
| `plan_operateur` | Console d'exploitation, réservée à l'allowlist opérateur |
| `donnees_tenant` | Base PostgreSQL des données des tenants |
| `integration_externe` | Systèmes tiers qui appellent Zylo (webhooks) |
| `observabilite` | Collecteur de traces et métriques |
| `metadonnees_cloud` | Endpoint de métadonnées du fournisseur cloud, isolé |

## Matrice source-destination-port (version 2026-11-05.1)

| Identifiant | Source | Destination | Port | Protocole | Motif |
|---|---|---|---|---|---|
| F-01 | internet | entree_publique | 443 | tcp | HTTPS public vers le point d'entrée |
| F-02 | entree_publique | application | 8000 | tcp | relais du point d'entrée vers l'application |
| F-03 | application | donnees_tenant | 5432 | tcp | accès PostgreSQL de l'application |
| F-04 | application | plan_operateur | 8000 | tcp | console d'exploitation, allowlist opérateur |
| F-05 | application | observabilite | 4318 | tcp | export OTLP des traces et métriques |
| F-06 | integration_externe | entree_publique | 443 | tcp | webhooks entrants signés |

## Sorties contrôlées

`SORTIES_AUTORISEES` est vide. Aucune sortie de l'application vers un hôte externe
n'est autorisée tant que la liste n'est pas renseignée et revue par la sécurité
(QE-EXP-19 : fournisseurs et ports à décider). Les métadonnées cloud sont refusées
avant cette liste.

## Endpoint de métadonnées

Refusé depuis l'application, quelle que soit la forme de la cible :
- adresses `169.254.0.0/16` (AWS, Azure, GCP) ;
- adresse IPv6 `fd00:ec2::254` ;
- nom d'hôte `metadata.google.internal`.

## Limites

- Le module décide ; il ne configure aucun pare-feu. Les règles réelles de
  l'hébergement doivent reproduire cette matrice (segmentation et mode d'hébergement
  à décider).
- La détection des connexions anormales, des erreurs DNS et TLS, et des refus réseau
  relève de la supervision (BE-241), non de ce module.
