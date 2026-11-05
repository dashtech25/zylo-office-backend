"""Export de données par sujet ou tenant (BE-243).

Capacité du socle : elle produit un export de données (membres d'une organisation, ou un
sujet de cette organisation) sous forme de job traçable, à durée de vie limitée.

Routes (app/exports/router.py, montées sous `/api/v1/exports`) :
- `POST /api/v1/exports` : demande d'export (périmètre `tenant` ou `sujet`) ;
- `GET /api/v1/exports/{export_id}` : statut du job, empreinte, expiration ;
- `GET /api/v1/exports/{export_id}/download` : contenu, 410 une fois expiré.

Fichiers :
- `models.py` : table `export_jobs` ;
- `service.py` : contrôle de permission journalisé, validation de portée, construction du
  contenu, empreinte, expiration, purge ;
- `schemas.py` : corps et réponses HTTP ;
- `permissions.py` / `seed.py` : permission `donnees.export.creer`, accordée au propriétaire.

Limites provisoires (questions QE-EXP-xx à trancher) : nom de permission non défini dans la
définition ; contenu limité aux membres de l'organisation ; purge à déclencher par un
traitement planifié (la fonction `purger_exports_expires` existe, son déclencheur non).
"""
