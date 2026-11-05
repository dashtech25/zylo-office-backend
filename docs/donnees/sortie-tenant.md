# Sortie de tenant : suppression, hold et attestation (BE-246)

Référence du code : `app/sortie_tenant/` (service, modèles, permissions, seed, schémas, routes) et
migration `alembic/versions/a246c1d2e3f4_be246_sortie_tenant.py`.

## Routes

| Méthode | Chemin | Effet | Codes |
|---|---|---|---|
| POST | `/api/v1/organizations/{organization_id}/exit` | Demande la sortie ; 201 avec `id`, `etat`, `attestation` | 403 sans droit ou approbation non distincte ; 409 si une dépendance n'est pas prise en charge (rien n'est effacé) |
| GET | `/api/v1/organizations/{organization_id}/exit/attestation` | Attestation de la dernière sortie | 403 pour un tiers sans droit ; 404 si aucune sortie |

Corps de la demande : `{"motif": "...", "approbateurId": "<uuid>"}`.

## Décision et approbation

- Le demandeur doit porter `donnees.sortie.decider`. Cette permission n'est accordée à aucun rôle
  par défaut : elle relève de l'opérateur habilité.
- L'approbateur désigné doit être une autre personne, titulaire de la même permission (QE-EXP-15,
  recommandation appliquée).
- Chaque refus (permission, approbateur identique ou sans droit) est journalisé dans `audit_event`
  (`donnees.sortie.refus`, résultat `refused`) avant la réponse 403.
- L'attestation est lisible par le demandeur, l'approbateur, ou un titulaire de
  `donnees.sortie.lire`.

## Holds

La table `legal_holds` porte les holds posés sur un tenant (motif, décideur, date). Un hold actif
vise tout le tenant : si au moins un hold existe, la sortie n'efface rien, la demande reçoit
l'état `tenue`, et l'attestation déclare chaque table comme conservée avec le motif « hold actif ».
Il n'existe pas de levée de hold dans ce lot. La pose se fait par `app/sortie_tenant/service.py::poser_hold`,
car la définition ne prévoit pas de route de pose.

## Plan de suppression

Le plan est calculé dans la base migrée (`information_schema` et `pg_constraint`), pas dans les modèles.

- **Effacées** : tables portant une colonne `organizationId`, plus les tables enfants qui ont une clé
  étrangère simple vers une telle table (les lignes effacées sont celles reliées au tenant). Effacement dans l'ordre de dépendance, enfants
  avant parents, dans une seule transaction.
- **Conservées avec motif** : la racine `organization`, les journaux `audit_event` et `export_audit`, et
  les deux tables de preuve `tenant_exit_requests` et `legal_holds`.
- **Différées avec motif** : index de recherche, objets de stockage, cache mémoire de processus,
  journaux applicatifs hors base. Aucun de ces stockages n'est branché au socle à ce jour.

Une table enfant du tenant est retenue dès qu'une de ses clés pointe vers une table du tenant ; ses
autres clés (vers une table globale comme `permission`) ne la font pas sortir du plan. Une dépendance
qui ne rentre pas dans ce plan (enfant de second niveau, par exemple) fait échouer la transaction :
la sortie est refusée en 409 et rien n'est effacé.

## Attestation

Forme stockée dans `tenant_exit_requests.attestation` :

- `efface` : liste `{table, lignes}`, nombre de lignes retirées par table ;
- `differe` : liste `{categorie, cible, motif, statut}` ;
- `conserve` : liste `{cible, motif}` ;
- `etat`, `demandeur`, `approbateur`, `motif`, `decideLe`, `holds`, `organizationId`.

## Écarts consignés

- Approbation par une seconde personne désignée dans la demande (QE-EXP-15).
- Pas de route de pose de hold ni de levée (non prévues par la définition).
- Un hold vise tout le tenant ; aucune granularité par catégorie de données.
- Les journaux `audit_event` et `export_audit` sont conservés comme preuves, pas effacés (décision à prendre, QE-EXP-15).
- La migration réconcilie les deux têtes présentes sur develop (`adce56acf5ff` et `f243a0b1c2d4`).
