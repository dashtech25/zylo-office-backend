"""Export de données par sujet ou tenant (BE-243).

Contrat d'une demande, dans cet ordre (voir app/exports/router.py) :
1. Permission `donnees.export.creer` (`verifier_permission`). Sans elle : 403 `permission_denied`,
   aucun job, et une entrée `donnees.export.refus` (résultat `refused`) est journalisée (CA-3).
2. Durée de vie : `settings.EXPORT_EXPIRATION_SECONDS` doit être configurée. Sans valeur,
   503 `export_retention_missing`, rien n'est écrit (QE-EXP-12, pas de valeur par défaut).
3. Portée (CA-1, CA-4) :
   - `tenantId` fourni et différent de l'organisation courante : 404 `export_tenant_not_found` ;
   - `sujet` : le sujet doit être membre de l'organisation, sinon 404 `export_sujet_not_found`.
4. Contenu : une liste d'enregistrements de membres, triée par identifiant. Périmètre `tenant` :
   tous les membres de l'organisation courante ; périmètre `sujet` : ce seul membre. Champs
   listés explicitement dans `_membres` : aucun mot de passe haché ni secret n'en sort (CA-4).
5. Empreinte : SHA-256 de la forme canonique du contenu (`json.dumps` avec clés triées,
   séparateurs compacts, `ensure_ascii=False`, encodé en UTF-8). Calculée à la création.
6. Trace : l'action `donnees.export.demande` est journalisée dans la même transaction que le job.

Téléchargement : si `expireAt` est atteint, le contenu est purgé et la réponse est 410
`export_expired` (CA-2, CA-5). Sinon le contenu et l'empreinte sont renvoyés.
Purge : `purger_exports_expires` met `contenu` à NULL et le statut à `expire` pour tous les jobs
échus. Son déclencheur périodique n'est pas branché ici (voir app/exports/__init__.py).

Isolation : toute lecture est filtrée par `organizationId` ; un job d'une autre organisation
est indiscernable d'un job absent (404 `export_not_found`).
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit_event
from app.core.config import settings
from app.core.errors import AppError
from app.exports.models import STATUT_EXPIRE, STATUT_PRET, ExportJob
from app.exports.permissions import DONNEES_EXPORT_CREER
from app.identity.models import OrganizationUser, User
from app.rbac.service import user_has_permission

ACTION_DEMANDE = "donnees.export.demande"
ACTION_REFUS = "donnees.export.refus"
PERIMETRE_TENANT = "tenant"
PERIMETRE_SUJET = "sujet"

def est_expire(job: ExportJob, maintenant: datetime | None = None) -> bool:
    """Vrai dès que `expireAt` est atteint ou dépassé (borne incluse : expiré à l'instant exact)."""
    reference = maintenant or datetime.now(timezone.utc)
    return job.expireAt <= reference


def statut_du_job(job: ExportJob) -> str:
    """`expire` si l'échéance est passée, même avant la purge ; `pret` sinon."""
    return STATUT_EXPIRE if est_expire(job) else STATUT_PRET


def forme_canonique(contenu: list[dict[str, Any]]) -> str:
    """Forme sérialisée stable servant à calculer l'empreinte (voir le contrat du module)."""
    return json.dumps(contenu, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def empreinte_du_contenu(contenu: list[dict[str, Any]]) -> str:
    """SHA-256 hexadécimal de la forme canonique du contenu."""
    return hashlib.sha256(forme_canonique(contenu).encode("utf-8")).hexdigest()


async def verifier_permission(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID) -> None:
    """Refuse sans `donnees.export.creer` et journalise le refus (CA-3).

    Le journal est commité avant la levée de 403 : le refus reste tracé même si la requête échoue."""
    if await user_has_permission(db, utilisateur_id, organization_id, DONNEES_EXPORT_CREER):
        return
    await record_audit_event(
        db,
        organization_id,
        utilisateur_id,
        ACTION_REFUS,
        "export_job",
        None,
        "Demande d'export de données refusée : permission manquante.",
        {"permission": DONNEES_EXPORT_CREER},
        result="refused",
    )
    await db.commit()
    raise AppError(
        code="permission_denied",
        message=f"Permission manquante : {DONNEES_EXPORT_CREER}.",
        status_code=403,
    )


async def _membres(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID | None) -> list[dict[str, Any]]:
    """Enregistrements des membres de l'organisation, limités à un utilisateur si `user_id` est fourni."""
    requete = (
        select(User, OrganizationUser)
        .join(OrganizationUser, OrganizationUser.userId == User.id)
        .where(OrganizationUser.organizationId == organization_id, User.deletedAt.is_(None))
        .order_by(User.id)
    )
    if user_id is not None:
        requete = requete.where(User.id == user_id)
    lignes = (await db.execute(requete)).all()
    return [
        {
            "userId": str(utilisateur.id),
            "email": utilisateur.email,
            "fullName": utilisateur.fullName,
            "status": utilisateur.status,
            "membreDepuis": appartenance.createdAt.isoformat(),
        }
        for utilisateur, appartenance in lignes
    ]


def _lire_perimetre(perimetre: dict[str, Any]) -> tuple[str, uuid.UUID | None]:
    """Type de périmètre et identifiant du sujet (None pour un tenant)."""
    if perimetre["type"] == PERIMETRE_SUJET:
        return PERIMETRE_SUJET, uuid.UUID(str(perimetre["sujetId"]))
    return PERIMETRE_TENANT, None


async def demander_export(
    db: AsyncSession,
    organization_id: uuid.UUID,
    demandeur_id: uuid.UUID,
    perimetre: dict[str, Any],
) -> ExportJob:
    """Crée le job, son contenu et son empreinte, puis journalise la demande (voir le contrat du module).

    `perimetre` est le corps validé par le schéma : `type`, `sujetId` si `sujet`, `tenantId` optionnel.
    Lève 503, 404 selon le contrat ; aucune ligne n'est écrite en cas d'erreur."""
    duree = settings.EXPORT_EXPIRATION_SECONDS
    if duree is None:
        raise AppError(
            code="export_retention_missing",
            message="Export indisponible : durée de vie non configurée.",
            status_code=503,
        )

    tenant_demande = perimetre.get("tenantId")
    if tenant_demande is not None and uuid.UUID(str(tenant_demande)) != organization_id:
        raise AppError(code="export_tenant_not_found", message="Tenant introuvable.", status_code=404)

    type_perimetre, sujet_id = _lire_perimetre(perimetre)
    if sujet_id is not None:
        membre = (
            await db.execute(
                select(OrganizationUser.id).where(
                    OrganizationUser.organizationId == organization_id, OrganizationUser.userId == sujet_id
                )
            )
        ).first()
        if membre is None:
            raise AppError(code="export_sujet_not_found", message="Sujet introuvable.", status_code=404)

    contenu = await _membres(db, organization_id, sujet_id)
    maintenant = datetime.now(timezone.utc)
    job = ExportJob(
        id=uuid.uuid4(),
        organizationId=organization_id,
        demandeur=demandeur_id,
        perimetre={"type": type_perimetre, "sujetId": str(sujet_id) if sujet_id else None},
        statut=STATUT_PRET,
        expireAt=maintenant + timedelta(seconds=duree),
        empreinte=empreinte_du_contenu(contenu),
        contenu=contenu,
    )
    db.add(job)
    await record_audit_event(
        db,
        organization_id,
        demandeur_id,
        ACTION_DEMANDE,
        "export_job",
        job.id,
        f"Demande d'export de données (périmètre {type_perimetre}).",
        {"perimetre": type_perimetre, "sujetId": str(sujet_id) if sujet_id else None, "nombre": len(contenu)},
    )
    await db.commit()
    await db.refresh(job)
    return job


async def obtenir_job(db: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> ExportJob:
    """Job de l'organisation courante. 404 `export_not_found` si absent ou d'un autre tenant."""
    job = (
        await db.execute(
            select(ExportJob).where(ExportJob.id == job_id, ExportJob.organizationId == organization_id)
        )
    ).scalar_one_or_none()
    if job is None:
        raise AppError(code="export_not_found", message="Export introuvable.", status_code=404)
    return job


async def telecharger(db: AsyncSession, organization_id: uuid.UUID, job_id: uuid.UUID) -> ExportJob:
    """Job prêt au téléchargement. Un job échu est purgé puis refusé en 410 `export_expired` (CA-2, CA-5)."""
    job = await obtenir_job(db, organization_id, job_id)
    if est_expire(job) or job.contenu is None:
        await _purger_job(db, job)
        raise AppError(code="export_expired", message="Export expiré.", status_code=410)
    return job


async def _purger_job(db: AsyncSession, job: ExportJob) -> None:
    job.contenu = None
    job.statut = STATUT_EXPIRE
    await db.commit()


async def purger_exports_expires(db: AsyncSession, maintenant: datetime | None = None) -> int:
    """Efface le contenu de tous les jobs échus et les marque `expire` ; renvoie leur nombre.

    Garantit qu'aucune copie d'export ne subsiste au-delà de `expireAt` (CA-5)."""
    reference = maintenant or datetime.now(timezone.utc)
    resultat = await db.execute(
        update(ExportJob)
        .where(ExportJob.expireAt <= reference, ExportJob.contenu.is_not(None))
        .values(contenu=None, statut=STATUT_EXPIRE)
        .execution_options(synchronize_session=False)
    )
    await db.commit()
    return resultat.rowcount or 0
