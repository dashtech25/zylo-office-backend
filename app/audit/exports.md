# Export du journal d'audit (BE-173)

Job d'export traçable du journal `audit_event`, à rétention limitée. Table `export_audit`
(migration `a7c3e91b2f54`). Code : `app/audit/export_job.py`, routes dans `app/audit/router.py`.

## Routes

| Méthode et chemin | Droit | Réponses |
|---|---|---|
| `POST /api/v1/audit/exports` | `audit.export` | 201 job ; 422 motif absent ou vide, ou période inversée ; 403 `permission_denied` ; 503 rétention non configurée |
| `GET /api/v1/audit/exports/{job_id}` | `audit.export` | 200 statut (`pret` / `expire`) et `lienTelechargement` (nul si expiré) ; 404 hors tenant |
| `GET /api/v1/audit/exports/{job_id}/telechargement` | `audit.export` | 200 `{"data": [...]}` ; 410 `audit_export_expired` ; 404 hors tenant |

En-tête `X-Organization-Id` obligatoire, comme les autres routes d'audit.

## Règles

- Motif obligatoire, non vide. Il est journalisé dans `reason` de l'entrée
  `audit.export.request` (EVT-AUD-02), écrite dans la même transaction que le job.
- Rétention : `AUDIT_EXPORT_EXPIRATION_SECONDS` (configuration, sans valeur par défaut,
  QE-PAR-07). Sans elle, aucune demande n'est acceptée.
- Contenu : événements du sujet (`entityType`) sur la période, reconstitués depuis
  `audit_event` à chaque téléchargement. Seuls les champs listés dans `CHAMPS_EXPORTES`
  sortent : pas d'adresse IP, pas d'agent utilisateur, pas de `changes`.
- Un export n'est pas stocké. Un téléchargement tardif peut donc contenir des événements
  postérieurs à la demande, dans la même période et le même sujet.
