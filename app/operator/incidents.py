"""Gestion des incidents et chronologie (BE-247).

Module de documentation et de service : il porte les règles métier des incidents
d'exploitation. Les routes sont dans `app.operator.incidents_router` (sous
`/api/v1/admin/incidents`, garde `require_admin_scope` de BE-120).

Règles :
- CA-1 : un incident est créé avec un propriétaire non vide, une sévérité du
  vocabulaire et l'état initial `ouvert`. L'horodatage `occurredAt` est posé par la
  base. Un propriétaire blanc est refusé en 422 avant toute écriture.
- CA-2 : la chronologie n'a qu'une opération, `ajouter_evenement`. Il n'existe ni
  fonction de modification ni de suppression d'une entrée ; la base refuse de toute
  façon UPDATE et DELETE (trigger de la migration BE-247). Un correctif s'écrit donc
  comme un nouvel événement qui référence le précédent dans son résumé.
- CA-3 : `lire_incident` et `lister_incidents` ne renvoient que les colonnes
  d'exploitation (identifiant, sévérité, propriétaire, état, horodatage, tenant
  concerné). Le nom ou tout autre contenu du tenant n'est jamais lu ici.
- CA-4 : ce module ne contrôle pas le droit d'accès ; c'est le rôle de la route.

Choix (NON DÉFINI dans la définition, retenus avec QE-BE247-01 à 03) :
- l'autorité de lecture est la portée plateforme de BE-120 (`operateur_plateforme`) ;
- l'état d'un incident est `ouvert`, `en_cours`, `resolu` ou `cloture` ;
- aucune transition d'état n'est encore imposée : elle relève d'une tâche ultérieure.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operator.incidents_models import ETAT_INITIAL, SEVERITES_INCIDENT, Incident, IncidentEvent


def _incident_introuvable() -> AppError:
    return AppError(code="incident_not_found", message="Incident introuvable.", status_code=404)


async def creer_incident(
    db: AsyncSession,
    *,
    severite: str,
    owner: str,
    tenant_id: uuid.UUID | None = None,
) -> Incident:
    """Crée un incident à l'état `ouvert`, avec propriétaire obligatoire (CA-1).

    `owner` est normalisé (espaces retirés) et refusé s'il est vide : un incident
    sans responsable n'est pas une donnée valable, même si la base l'accepterait.
    `severite` doit appartenir à `SEVERITES_INCIDENT`. Le tenant est facultatif ;
    il sert seulement à désigner le tenant concerné, jamais à lire son contenu.
    """
    proprietaire = owner.strip()
    if not proprietaire:
        raise AppError(
            code="incident_owner_required",
            message="Un incident doit avoir un propriétaire.",
            status_code=422,
            field_errors={"owner": ["obligatoire"]},
        )
    if severite not in SEVERITES_INCIDENT:
        raise AppError(
            code="incident_severity_invalid",
            message="Sévérité d'incident inconnue.",
            status_code=422,
            field_errors={"severity": [f"valeurs attendues : {', '.join(SEVERITES_INCIDENT)}"]},
        )
    incident = Incident(severity=severite, owner=proprietaire, state=ETAT_INITIAL, tenantId=tenant_id)
    db.add(incident)
    await db.flush()
    return incident


async def ajouter_evenement(
    db: AsyncSession,
    incident_id: uuid.UUID,
    *,
    type_evenement: str,
    acteur_id: uuid.UUID | None = None,
    resume: str = "",
    audit_event_id: uuid.UUID | None = None,
) -> IncidentEvent:
    """Ajoute une entrée à la chronologie d'un incident (CA-2, append-only).

    C'est la seule écriture sur la chronologie. L'incident doit exister (404 sinon),
    ce qui évite une entrée orpheline. L'ordre est fixé par `sequence`, attribuée
    par la base à l'insertion.
    """
    existe = await db.scalar(select(func.count()).select_from(Incident).where(Incident.id == incident_id))
    if not existe:
        raise _incident_introuvable()
    evenement = IncidentEvent(
        incidentId=incident_id,
        eventType=type_evenement,
        summary=resume,
        actorUserId=acteur_id,
        auditEventId=audit_event_id,
    )
    db.add(evenement)
    await db.flush()
    return evenement


async def lire_incident(db: AsyncSession, incident_id: uuid.UUID) -> tuple[Incident, list[IncidentEvent]]:
    """Renvoie l'incident et sa chronologie, dans l'ordre d'insertion (CA-2).

    Lève 404 si l'incident n'existe pas. La chronologie ne contient que les entrées
    de `incident_events`, sans lecture du tenant référencé.
    """
    incident = await db.get(Incident, incident_id)
    if incident is None:
        raise _incident_introuvable()
    evenements = (
        await db.execute(
            select(IncidentEvent)
            .where(IncidentEvent.incidentId == incident_id)
            .order_by(IncidentEvent.sequence)
        )
    ).scalars().all()
    return incident, list(evenements)


async def lister_incidents(db: AsyncSession, *, limit: int, offset: int) -> tuple[list[Incident], int]:
    """Page d'incidents, du plus récent au plus ancien, et total (CA-3).

    Les lignes ne portent que les colonnes d'exploitation ; le schéma de réponse de
    la route ne reprend pas davantage (test de redaction).
    """
    total = await db.scalar(select(func.count()).select_from(Incident)) or 0
    lignes = (
        await db.execute(
            select(Incident).order_by(Incident.occurredAt.desc(), Incident.id).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(lignes), total
