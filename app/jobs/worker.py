"""Worker des jobs d'import et d'export (BE-213).

`traiter_job(db, job_id, interrompre_apres=None)` fait passer un job de `queued` à `succeeded`.

Déroulement :
- un job `queued` passe en `running` ; un job `running` (interrompu) est repris ;
- un job terminal (`succeeded`, `failed`, `cancelled`, `expired`) est laissé tel quel ;
- le contenu est produit par lots de `TAILLE_LOT` lignes, dans un ordre stable (identifiant) ;
- le fichier n'est écrit dans le stockage qu'à la finalisation, puis le job passe en `succeeded`
  avec `filePointer` et `expiresAt`.

Reprise (CA-5) : le contenu est recalculé depuis la source à chaque passage. Comme rien n'est écrit
avant la finalisation, une reprise produit le même fichier qu'un passage ininterrompu, et aucun
fichier partiel ne subsiste.

`interrompre_apres=n` simule une interruption : le worker s'arrête après le n-ième lot, sans
finaliser. Le job reste `running` ; l'appelant doit committer la session.

Source du type `export.clients` : NON DÉFINIE par la fiche. Jeu retenu : les membres actifs de
l'organisation du tenant (même choix que app/exports). Le type `import.clients` n'a pas de
traitement défini : le worker le refuse.

Le worker n'est appelé par aucun déclencheur dans ce lot.
"""

import json
import math
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Organization, OrganizationUser, User
from app.jobs.models import (
    ETAT_CANCELLED,
    ETAT_EXPIRED,
    ETAT_FAILED,
    ETAT_QUEUED,
    ETAT_RUNNING,
    ETAT_SUCCEEDED,
    Job,
)
from app.jobs.permissions import JOB_EXPORT_CLIENTS
from app.jobs.service import echeance_fichier
from app.shared.storage import get_storage_backend

TAILLE_LOT = 500
ETATS_TERMINAUX = (ETAT_SUCCEEDED, ETAT_FAILED, ETAT_CANCELLED, ETAT_EXPIRED)


def _forme_canonique(lignes: list[dict]) -> bytes:
    """Forme sérialisée stable : deux passages sur les mêmes données donnent les mêmes octets."""
    return json.dumps(lignes, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


async def _lot_membres(db: AsyncSession, organization_id: uuid.UUID, numero: int) -> list[dict]:
    requete = (
        select(User.id, User.email, User.fullName, OrganizationUser.status)
        .join(User, User.id == OrganizationUser.userId)
        .where(OrganizationUser.organizationId == organization_id, OrganizationUser.status == "active")
        .order_by(User.id)
        .offset((numero - 1) * TAILLE_LOT)
        .limit(TAILLE_LOT)
    )
    return [
        {"userId": str(uid), "email": email, "fullName": nom, "status": statut}
        for uid, email, nom, statut in (await db.execute(requete)).all()
    ]


async def traiter_job(db: AsyncSession, job_id: uuid.UUID, interrompre_apres: int | None = None) -> None:
    """Traite le job jusqu'à sa finalisation, ou jusqu'à l'interruption demandée (voir le module)."""
    job = await db.scalar(select(Job).where(Job.jobId == job_id).with_for_update())
    if job is None:
        raise LookupError(f"Job {job_id} introuvable.")
    if job.state in ETATS_TERMINAUX:
        return
    if job.type != JOB_EXPORT_CLIENTS:
        raise ValueError(f"Type de job sans traitement défini : {job.type}.")
    if job.state in (ETAT_QUEUED, ETAT_RUNNING):
        job.state = ETAT_RUNNING
        await db.flush()

    organization_id = await db.scalar(select(Organization.id).where(Organization.tenantId == job.tenantId))
    if organization_id is None:
        raise LookupError(f"Aucune organisation pour le tenant du job {job_id}.")

    total = await db.scalar(
        select(func.count())
        .select_from(OrganizationUser)
        .where(OrganizationUser.organizationId == organization_id, OrganizationUser.status == "active")
    )
    nombre_lots = max(1, math.ceil((total or 0) / TAILLE_LOT))

    lignes: list[dict] = []
    for numero in range(1, nombre_lots + 1):
        lignes.extend(await _lot_membres(db, organization_id, numero))
        if interrompre_apres is not None and numero == interrompre_apres:
            return

    reference = get_storage_backend().upload(_forme_canonique(lignes), f"export-{job.jobId}.json", organization_id)
    job.filePointer = reference
    job.expiresAt = echeance_fichier(datetime.now(timezone.utc))
    job.state = ETAT_SUCCEEDED
    await db.flush()
