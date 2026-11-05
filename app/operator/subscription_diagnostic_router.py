"""Routes du diagnostic abonnement guidé (BE-133), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/cases/{case_id}/subscription-diagnostics` : enregistre un diagnostic
  sur un cas (droit de lecture sur le cas, règle de BE-123) ;
- `GET /api/v1/admin/cases/{case_id}/subscription-diagnostics/{diagnostic_id}` : lit un
  diagnostic du cas (404 si le diagnostic n'appartient pas à ce cas).

Aucune route d'écriture sur la ressource de diagnostic : PATCH, PUT et DELETE renvoient 405
(BE-133 CA-2). Les corrections d'abonnement passent par BE-135.

Le parcours tient dans un corps de requête : qualification, référence de preuve,
résultat et vérification. Le serveur déduit l'action permise, le chemin d'échec et la
clôture, via `app.operator.payment_diagnostic.issue_du_diagnostic` (règle partagée avec BE-132).

Codes : 201 à la création ; 403 `admin_scope_denied` pour un refus de droit, de portée ou
une correction demandée ; 404 pour un cas ou un diagnostic introuvable ; 422 pour un corps
invalide.

Trace (BE-133 CA-4 et journal) : ouverture, échec ou résultat non concluant, clôture, via
`ecrire_evenement_admin` (BE-122) dans la transaction du diagnostic.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.admin_audit import ecrire_evenement_admin
from app.core.database import get_db
from app.core.logging import request_id_ctx
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.cases import InterventionCase, charger_cas, exiger_lecture
from app.operator.payment_diagnostic import erreur_diagnostic_introuvable, issue_du_diagnostic
from app.operator.subscription_diagnostic import (
    ACTION_CLOTURE,
    ACTION_ECHEC,
    ACTION_OUVERTURE,
    ACTION_PERMISE,
    TYPE_ENTITE_DIAGNOSTIC,
    SubscriptionDiagnostic,
    exiger_pas_de_correction_d_abonnement,
)

router = APIRouter()


class SubscriptionDiagnosticCreate(BaseModel):
    """Corps du diagnostic : les saisies de l'agent. Les décisions viennent du serveur."""

    qualification: str = Field(min_length=1, max_length=200)
    proofConsultedRef: str = Field(min_length=1, max_length=200)
    result: Literal["conforme", "echec", "non_concluant"]
    verificationStatus: Literal["verifiee", "non_verifiee"]
    actionDemandee: str | None = Field(default=None, max_length=60)


class SubscriptionDiagnosticResponse(BaseModel):
    """Représentation d'un diagnostic abonnement (mêmes champs que le diagnostic paiement)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    caseId: uuid.UUID
    qualification: str
    proofConsultedRef: str
    permittedAction: str
    result: str
    verificationStatus: str
    failurePath: str | None
    escalationId: uuid.UUID | None
    closedAtUtc: datetime | None


def _correlation() -> str | None:
    return request_id_ctx.get()


@router.post(
    "/cases/{case_id}/subscription-diagnostics",
    response_model=SubscriptionDiagnosticResponse,
    status_code=201,
    summary="Lancer un diagnostic abonnement (BE-133)",
)
async def lancer_diagnostic_abonnement(
    case_id: uuid.UUID,
    data: SubscriptionDiagnosticCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionDiagnostic:
    """Enregistre le diagnostic, déduit son chemin d'échec et sa clôture, puis écrit la trace.

    Ordre des contrôles : cas existant (404), droit de lecture sur le cas (403), correction
    d'abonnement ou action financière refusée (403), puis écriture. Une demande refusée
    n'écrit rien.
    """
    cas: InterventionCase = await charger_cas(db, case_id)
    await exiger_lecture(db, current_user.id, cas)
    exiger_pas_de_correction_d_abonnement(data.actionDemandee)

    chemin, cloture = issue_du_diagnostic(data.result, data.verificationStatus)
    diagnostic = SubscriptionDiagnostic(
        id=uuid.uuid4(),
        caseId=cas.id,
        qualification=data.qualification,
        proofConsultedRef=data.proofConsultedRef,
        permittedAction=ACTION_PERMISE,
        result=data.result,
        verificationStatus=data.verificationStatus,
        failurePath=chemin,
        escalationId=None,
        closedAtUtc=cloture,
    )
    db.add(diagnostic)
    await db.flush()

    await ecrire_evenement_admin(
        db,
        organization_id=cas.tenantId,
        actor_user_id=current_user.id,
        action=ACTION_OUVERTURE,
        entity_type=TYPE_ENTITE_DIAGNOSTIC,
        entity_id=diagnostic.id,
        summary=f"Diagnostic abonnement lancé (résultat {data.result})",
        correlation_id=_correlation(),
        changes={"caseId": str(cas.id), "result": data.result, "verificationStatus": data.verificationStatus},
    )
    if chemin is not None:
        await ecrire_evenement_admin(
            db,
            organization_id=cas.tenantId,
            actor_user_id=current_user.id,
            action=ACTION_ECHEC,
            entity_type=TYPE_ENTITE_DIAGNOSTIC,
            entity_id=diagnostic.id,
            summary=f"Diagnostic abonnement en échec : chemin {chemin}",
            correlation_id=_correlation(),
            changes={"failurePath": chemin, "result": data.result},
        )
    if cloture is not None:
        await ecrire_evenement_admin(
            db,
            organization_id=cas.tenantId,
            actor_user_id=current_user.id,
            action=ACTION_CLOTURE,
            entity_type=TYPE_ENTITE_DIAGNOSTIC,
            entity_id=diagnostic.id,
            summary="Diagnostic abonnement clos",
            correlation_id=_correlation(),
            changes={"closedAtUtc": cloture.isoformat()},
        )
    await db.commit()
    return diagnostic


@router.get(
    "/cases/{case_id}/subscription-diagnostics/{diagnostic_id}",
    response_model=SubscriptionDiagnosticResponse,
    summary="Lire un diagnostic abonnement (BE-133)",
)
async def lire_diagnostic_abonnement(
    case_id: uuid.UUID,
    diagnostic_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionDiagnostic:
    """Lit le diagnostic si le compte peut lire le cas et si le diagnostic appartient à ce cas."""
    cas = await charger_cas(db, case_id)
    await exiger_lecture(db, current_user.id, cas)
    diagnostic = (
        await db.execute(
            select(SubscriptionDiagnostic).where(
                SubscriptionDiagnostic.id == diagnostic_id,
                SubscriptionDiagnostic.caseId == cas.id,
            )
        )
    ).scalar_one_or_none()
    if diagnostic is None:
        raise erreur_diagnostic_introuvable()
    return diagnostic
