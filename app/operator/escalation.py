"""Escalade d'un cas d'intervention (BE-142).

Table `escalation` : une demande de prise en charge par un niveau supérieur, ouverte
sur un cas (`InterventionCase`, BE-123). Colonnes : `caseId`, `level`, `targetRole`,
`openedAtUtc`, `closedAtUtc` (NULL tant que l'escalade est ouverte), `closureReason`.

Règles (définition BE-142) :
- ouverture : rôle L1 ou L2 sur la portée du cas (`exiger_ouverture`, mêmes règles
  que BE-123) ; un cas clos ne s'escalade plus (409 `case_closed`) ;
- effet : l'ouverture passe le cas à l'état `escalade` (CA-2), dans la même
  transaction que l'insertion de l'escalade ;
- clôture : responsable de gestion de la portée du cas seulement (`exiger_gestion`,
  soit `securite_incident_commander` d'après QE-ADM-86) ; un agent L1 reçoit 403
  (CA-1) ; une escalade déjà close renvoie 409 `escalation_closed` ;
- isolation : la portée est celle du cas, donc un agent d'un autre tenant reçoit 403
  (CA-3) ;
- audit : chaque ouverture écrit `admin.escalation.open`, chaque clôture
  `admin.escalation.close` (CA-4), sur l'entité `Escalation`.

Choix provisoires (NON DÉFINI dans la définition, consignés) :
- niveaux : entiers 1 à 3 (QE-ADM-12) ;
- rôle cible : doit appartenir à `ROLES_CANDIDATS` de BE-121 (422 sinon) ;
- la clôture d'une escalade ne remet pas le cas dans son état précédent ; le cas reste
  à `escalade` jusqu'à une transition ultérieure (QE-BE142-01).

Ce module ne dépend d'aucun module métier. Les routes sont dans
`app.operator.escalation_router`, sous `/api/v1/admin`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import Base
from app.core.errors import AppError
from app.operator.cases import (
    ETAT_ESCALADE,
    InterventionCase,
    charger_cas,
    exiger_gestion,
    exiger_ouverture,
)
from app.shared.models import UUIDPrimaryKeyMixin

NIVEAU_MIN = 1
NIVEAU_MAX = 3
TYPE_ENTITE_ESCALADE = "Escalation"
ACTION_OUVERTURE_ESCALADE = "admin.escalation.open"
ACTION_CLOTURE_ESCALADE = "admin.escalation.close"


class Escalation(UUIDPrimaryKeyMixin, Base):
    """Une escalade ouverte sur un cas d'intervention.

    `closedAtUtc` et `closureReason` ne sont renseignés qu'à la clôture. Aucune ligne
    n'est supprimée : l'historique des escalades reste lisible."""

    __tablename__ = "escalation"
    __table_args__ = (
        CheckConstraint(
            f"level BETWEEN {NIVEAU_MIN} AND {NIVEAU_MAX}", name="ck_escalation_level",
        ),
        {"comment": "Escalades d'un cas d'intervention, ouvertes et closes par les agents (BE-142)."},
    )

    caseId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("intervention_case.id"), nullable=False, index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    targetRole: Mapped[str] = mapped_column(String(64), nullable=False)
    openedAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closedAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closureReason: Mapped[str | None] = mapped_column(String(500), nullable=True)


def erreur_escalade_introuvable() -> AppError:
    return AppError(code="escalation_not_found", message="Escalade introuvable.", status_code=404)


async def charger_escalade(db: AsyncSession, escalation_id: uuid.UUID) -> Escalation:
    """L'escalade, ou 404 si elle n'existe pas."""
    escalade = await db.get(Escalation, escalation_id)
    if escalade is None:
        raise erreur_escalade_introuvable()
    return escalade


async def ouvrir_escalade(
    db: AsyncSession,
    *,
    cas: InterventionCase,
    acteur_id: uuid.UUID,
    niveau: int,
    cible: str,
    correlation_id: str | None,
) -> Escalation:
    """Ouvre une escalade sur `cas`, passe le cas à `escalade`, écrit l'audit.

    Contrôles dans l'ordre : droit d'ouverture sur la portée du cas (403), cas clos
    (409). L'insertion, la mise à jour du cas et l'entrée d'audit sont faites sans
    commit : l'appelant valide la transaction une seule fois."""
    await exiger_ouverture(db, acteur_id, cas.tenantId)
    if cas.status == "cloture":
        raise AppError(code="case_closed", message="Cas déjà clos.", status_code=409)
    maintenant = datetime.now(timezone.utc)
    escalade = Escalation(
        caseId=cas.id,
        level=niveau,
        targetRole=cible,
        openedAtUtc=maintenant,
    )
    db.add(escalade)
    cas.status = ETAT_ESCALADE
    await db.flush()
    await ecrire_evenement_admin(
        db,
        organization_id=cas.tenantId,
        actor_user_id=acteur_id,
        action=ACTION_OUVERTURE_ESCALADE,
        entity_type=TYPE_ENTITE_ESCALADE,
        entity_id=escalade.id,
        summary=f"Escalade ouverte (niveau {niveau})",
        correlation_id=correlation_id,
        changes={"caseId": str(cas.id), "level": niveau, "targetRole": cible, "caseStatus": ETAT_ESCALADE},
    )
    return escalade


async def cloturer_escalade(
    db: AsyncSession,
    *,
    escalade: Escalation,
    acteur_id: uuid.UUID,
    motif: str,
    correlation_id: str | None,
) -> Escalation:
    """Clôt une escalade ouverte, réservé au responsable de gestion du cas (CA-1).

    Le droit se contrôle sur la portée du cas parent. Une escalade déjà close renvoie
    409. Le statut du cas n'est pas modifié (QE-BE142-01)."""
    cas = await charger_cas(db, escalade.caseId)
    await exiger_gestion(db, acteur_id, cas)
    if escalade.closedAtUtc is not None:
        raise AppError(code="escalation_closed", message="Escalade déjà close.", status_code=409)
    escalade.closedAtUtc = datetime.now(timezone.utc)
    escalade.closureReason = motif
    await ecrire_evenement_admin(
        db,
        organization_id=cas.tenantId,
        actor_user_id=acteur_id,
        action=ACTION_CLOTURE_ESCALADE,
        entity_type=TYPE_ENTITE_ESCALADE,
        entity_id=escalade.id,
        summary="Escalade close",
        correlation_id=correlation_id,
        changes={"caseId": str(cas.id), "closureReason": motif},
    )
    return escalade
