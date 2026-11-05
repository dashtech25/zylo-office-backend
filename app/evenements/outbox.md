# Outbox et consommation idempotente (BE-166)

Module : `app/evenements/outbox.py`, tables dans `app/evenements/models.py`, migration `c166e0f1a2b3`.

## Publication

1. La mutation métier et `enregistrer_evenement(db, donnees, emetteur_tenant=...)` partagent la même session.
2. L'appelant fait `commit()`. L'événement n'est visible qu'à partir de ce commit (CA-1).
3. Un rollback supprime la mutation et l'événement ensemble.
4. Sans émetteur authentifié : `PERMISSION_DENIED` 403 (CA-3). Tenant différent de l'identité : `TENANT_MISMATCH` (CA-4).
5. Un `eventId` déjà présent ne crée pas de seconde ligne.

## Consommation

- `distribuer_pour_consommateur(db, consommateur, tenant_id, handler)` lit les événements committés du tenant, consigne chaque consommation dans `consommation_evenement`, et appelle le handler dans la même session.
- Un rejeu est refusé par la contrainte unique (consommateur, eventId) et journalisé `REPLAY_DUPLICATE` (CA-2).
- Un consommateur d'un autre tenant ne reçoit rien et rien n'est consigné (CA-4).

## Hors périmètre

Le mécanisme de file (worker, polling, ordre par entité, rétention) n'est pas défini : QE-PAR-10.

## Extension BE-234 (versionnée)

- Migration `b234a0d1e2f3` (revise `5e31981cf46c`) : colonnes `portee`, `acteur`, `correlationId`, `tentatives` ; `tenantId` devient nullable ; contraintes `ck_outbox_evenement_portee` et `ck_outbox_evenement_portee_tenant`. Le downgrade supprime les événements plateforme : perte volontaire.
- Événement plateforme : `enregistrer_evenement_plateforme(db, donnees, emetteur_plateforme=...)`. Le type doit commencer par `Plateforme.` (`PREFIXE_TYPE_PLATEFORME`), `tenantId` doit être nul. Émetteur non interne : `PERMISSION_DENIED` 403.
- Un événement sans tenant refusé par le chemin tenant : `SCHEMA_INVALID`.
- La lecture par tenant ne renvoie que `portee = tenant`.

Lacune connue : aucune table de consommateurs autorisés par tenant n'existe. L'isolation repose sur le `tenant_id` passé par l'appelant (QE à traiter avec BE-235).
