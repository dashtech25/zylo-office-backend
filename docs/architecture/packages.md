# Arborescence réelle de `app/` (source unique)

> Découpé depuis [`docs/archive/ARCHITECTURE.md`](../archive/ARCHITECTURE.md) (archive, contenu source conservé). Lignes source indiquées dans chaque section.

Source unique de l'arborescence. Les README et `CLAUDE.md` renvoient ici. Vérifié contre le dépôt le 2026-10-09 (`find app -maxdepth 3 -type d`).

```text
app/
├── main.py                  # création de l'application FastAPI, montage des routers
├── core/                    # config, base, sécurité (JWT), erreurs, journal, chiffrement de champs
├── shared/                  # briques réutilisables sans logique métier (pagination, devises, géo, événements)
│   └── data/                # données de référence
├── identity/                # Organization, User, OrganizationUser
├── auth/                    # login, register, refresh, logout
├── rbac/                    # Role, Permission, require_permission(), affectation par module
├── modules_registry/        # registre des modules, activation par organisation
├── billing/                 # plan, abonnement, facture (pas de paiement réel)
├── audit/                   # journal d'audit
├── files/                   # capacité partagée : fichiers et liens
├── alerts/                  # capacité partagée : alertes
├── location/                # capacité partagée : localisation et suivi GPS
├── integrations/
│   └── holykell/            # adaptateur Holykell (client HTTP, DTO)
├── modules/
│   ├── zylo_liquid/         # module métier : cuves, stations, livraisons, fuites, prix
│   └── zylo_tanker/         # module métier : navires (Vessel), voir docs/modules/zylo-tanker/
└── api/v1/                  # agrégation des routers et versionnage REST (/api/v1)
```

## 2. Trois catégories de packages, jamais mélangées

```
app/
├── core/                    # fondation transverse : sécurité JWT, erreurs globales
├── shared/                  # briques génériques sans logique métier : pagination, devises, geo, storage bas niveau
├── identity/ rbac/ audit/   # SOCLE — comptes, permissions, journal d'audit
├── files/ location/         # CAPACITÉS PARTAGÉES — en cours d'extraction (voir §5)
│   alerts/ integrations/holykell/    même statut : transverses, jamais propriété d'un module métier
├── modules/
│   └── zylo_liquid/         # MÉTIER — logique carburant, un dossier par domaine (demain crm/, stock/...)
└── api/v1/router.py         # agrégation des routers, un include_router par module
```

Différence clé entre "capacité partagée" et "domaine du socle" : le socle
(`identity`/`rbac`/`audit`) définit *qui peut faire quoi* — c'est
transversal à toute action de l'application. Une capacité partagée
(`files`/`location`/`alerts`/`integrations/holykell`) rend un *service
technique* réutilisable par plusieurs modules métier, mais n'a pas de sens
sans qu'un module métier l'utilise (un fichier existe toujours pour quelque
chose : un bon de commande, une facture...). D'où la règle : **un module
métier consomme une capacité partagée, il ne la possède jamais** — c'est
toujours le module métier qui décide *quand* créer un document/une
alerte/un suivi GPS, jamais l'inverse.
