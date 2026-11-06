"""Jobs d'import et d'export d'un tenant (BE-213).

Fichiers :
- `models.py` : tables `job` et `job_error_report` ;
- `permissions.py` : une permission par type de job (`jobs.export.create`, `jobs.import.create`) ;
- `seed.py` : déclaration de ces permissions au démarrage ;
- `schemas.py` : corps et réponses HTTP ;
- `service.py` : isolation par tenant, permission par type, création idempotente, téléchargement ;
- `worker.py` : traitement d'un job (`traiter_job`), reprise après interruption ;
- `router.py` : routes montées sous `/api/v1/jobs`.
"""
