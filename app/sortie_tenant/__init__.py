"""Sortie d'un tenant : suppression, hold et attestation (BE-246).

Capacité du socle. Elle efface les données d'une organisation qui quitte la plateforme, sauf
celles tenues par un hold actif, et produit une attestation listant ce qui est effacé, différé
et conservé.

Routes (app/sortie_tenant/router.py, montées sous `/api/v1/organizations`) :
- `POST /{organization_id}/exit` : demande de sortie, approuvée par une seconde personne ;
- `GET /{organization_id}/exit/attestation` : attestation de la dernière sortie.

Fichiers :
- `models.py` : tables `tenant_exit_requests` et `legal_holds` ;
- `service.py` : plan de suppression, hold, exécution, attestation, contrôle de permission ;
- `schemas.py` : corps et réponses HTTP ;
- `permissions.py` / `seed.py` : permissions `donnees.sortie.decider` et `donnees.sortie.lire`,
  créées au démarrage et accordées à aucun rôle par défaut.

Documentation : docs/donnees/sortie-tenant.md.
"""
