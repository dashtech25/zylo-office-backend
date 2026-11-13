"""Export du journal d'audit en job traçable, à rétention limitée (BE-173).

Routes (app/audit/router.py) :
- `POST /api/v1/audit/exports` : demande d'export (sujet, période, motif obligatoire) ;
- `GET /api/v1/audit/exports/{job_id}` : statut et lien de téléchargement temporaire ;
- `GET /api/v1/audit/exports/{job_id}/telechargement` : contenu, 410 une fois expiré.

Contrat de la demande, dans cet ordre :
1. Permission `audit.export` : vérifiée par la dépendance de route (`require_permission`),
   avant toute lecture ou écriture. Sans elle, 403 et aucun job (CA-3).
2. Motif : obligatoire et non vide, contrôlé par le schéma (422, CA-1) puis par la base.
3. Rétention : `settings.AUDIT_EXPORT_EXPIRATION_SECONDS` doit être configurée. Elle n'a
   pas de valeur par défaut (QE-PAR-07, recommandation appliquée) : sans elle, 503
   `audit_export_retention_missing` et aucune ligne n'est écrite (CA-2).
4. Trace : une ligne `export_audit` et une entrée `audit.export.request` (EVT-AUD-02, motif
   dans `reason`) sont écrites dans la même transaction, puis commit.

Contenu : le fichier n'est pas stocké (aucun stockage de fichier branché). Il est reconstitué
à la lecture depuis `audit_event`, pour l'organisation du job, le sujet (`entityType`) et la
période du job. Conséquence documentée : un export relu plus tard peut contenir des événements
postérieurs à la demande, dans la même période et le même sujet. Les champs sont listés
explicitement (`CHAMPS_EXPORTES`) : adresse IP, agent utilisateur, `changes`,
`payloadMinimal` et les identifiants d'approbation n'en sortent jamais (CA-4).

Expiration : `expireAt` est fixé à la création. Passé cette date, le téléchargement renvoie
410 `audit_export_expired` (CA-2) et le statut passe à `expire`. Le job reste lisible par son
organisation (statut seul), jamais par une autre (404, CA-5).
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditEvent, ExportAudit
from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.errors import AppError

ACTION_DEMANDE = "audit.export.request"
STATUT_PRET = "pret"
STATUT_EXPIRE = "expire"

# Liste blanche des champs d'un événement exporté. Toute colonne absente de cette liste
# n'est jamais renvoyée, même si la base la contient (CA-4).
CHAMPS_EXPORTES = (
    "id", "actorUserId", "action", "entityType", "entityId", "summary", "reason",
    "result", "request_id", "createdAt", "scopeResourceType", "scopeResourceId",
)


def est_expire(job: ExportAudit, maintenant: datetime | None = None) -> bool:
    """Vrai dès que `expireAt` est atteint ou dépassé (borne exclue : expiré à l'instant exact)."""
    reference = maintenant or datetime.now(timezone.utc)
    return job.expireAt <= reference


def _valeur(valeur: Any) -> Any:
    """Rend une valeur JSON-compatible : dates en ISO 8601, UUID en texte."""
    if isinstance(valeur, datetime):
        return valeur.isoformat()
    if isinstance(valeur, uuid.UUID):
        return str(valeur)
    return valeur


async def demander_export(
    db: AsyncSession,
    organization_id: uuid.UUID,
    demandeur_id: uuid.UUID,
    sujet: str,
    date_debut: datetime,
    date_fin: datetime,
    motif: str,
) -> ExportAudit:
    """Crée le job d'export et journalise la demande (voir le contrat du module).

    Lève 503 `audit_export_retention_missing` si la durée de rétention n'est pas configurée.
    Aucune ligne n'est écrite en cas d'erreur."""
    duree = settings.AUDIT_EXPORT_EXPIRATION_SECONDS
    if duree is None:
        raise AppError(
            code="audit_export_retention_missing",
            message="Export d'audit indisponible : durée de rétention non configurée.",
            status_code=503,
        )

    maintenant = datetime.now(timezone.utc)
    job = ExportAudit(
        id=uuid.uuid4(),
        organizationId=organization_id,
        demandeur=demandeur_id,
        sujet=sujet,
        periode={"dateDebut": date_debut.isoformat(), "dateFin": date_fin.isoformat()},
        motif=motif,
        statut=STATUT_PRET,
        creeAt=maintenant,
        expireAt=maintenant + timedelta(seconds=duree),
    )
    db.add(job)
    await record_audit_event(
        db,
        organization_id,
        demandeur_id,
        ACTION_DEMANDE,
        "export_audit",
        job.id,
        f"Demande d'export du journal d'audit (sujet {sujet}).",
        {"sujet": sujet, "dateDebut": date_debut.isoformat(), "dateFin": date_fin.isoformat()},
        reason=motif,
    )
    await db.commit()
    await db.refresh(job)
    return job


async def obtenir_job(db: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> ExportAudit:
    """Job de l'organisation courante. 404 `audit_export_not_found` si absent ou d'un autre tenant."""
    job = (
        await db.execute(
            select(ExportAudit).where(ExportAudit.id == job_id, ExportAudit.organizationId == organization_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise AppError(code="audit_export_not_found", message="Export introuvable.", status_code=404)
    return job


async def contenu_export(db: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> list[dict[str, Any]]:
    """Événements du job, limités à `CHAMPS_EXPORTES`. 410 `audit_export_expired` une fois expiré.

    Lecture seule : le contenu est reconstitué depuis `audit_event` (voir le contrat du module)."""
    job = await obtenir_job(db, organization_id, job_id)
    if est_expire(job):
        raise AppError(code="audit_export_expired", message="Export expiré.", status_code=410)

    periode = job.periode
    debut = datetime.fromisoformat(periode["dateDebut"])
    fin = datetime.fromisoformat(periode["dateFin"])
    evenements = (
        await db.execute(
            select(AuditEvent)
            .where(
                AuditEvent.organizationId == organization_id,
                AuditEvent.entityType == job.sujet,
                AuditEvent.createdAt >= debut,
                AuditEvent.createdAt <= fin,
            )
            .order_by(AuditEvent.createdAt, AuditEvent.id)
        )
    ).scalars().all()
    return [{champ: _valeur(getattr(evenement, champ)) for champ in CHAMPS_EXPORTES} for evenement in evenements]


def statut_du_job(job: ExportAudit) -> str:
    """`pret` tant que l'expiration n'est pas atteinte, `expire` ensuite."""
    return STATUT_EXPIRE if est_expire(job) else STATUT_PRET
