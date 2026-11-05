"""Routes du diagnostic paiement guidé (BE-132), montées sous `/api/v1/admin`.

Routes :
- `POST /api/v1/admin/cases/{case_id}/payment-diagnostics` : enregistre un diagnostic
  sur un cas (droit de lecture sur le cas, règle de BE-123) ;
- `GET /api/v1/admin/cases/{case_id}/payment-diagnostics/{diagnostic_id}` : lit un
  diagnostic du cas (même règle de lecture ; 404 si le diagnostic n'appartient pas au cas).

Le parcours guidé en huit étapes tient dans un seul corps de requête : l'agent saisit
la qualification, la référence de preuve consultée, le résultat et l'état de vérification.
Le serveur déduit l'action permise (toujours `consultation_seule`), le chemin d'échec et la
clôture (règles de `app.operator.payment_diagnostic.issue_du_diagnostic`).

Codes : 201 à la création ; 403 `admin_scope_denied` pour un refus de droit, de portée
ou une action financière demandée ; 404 pour un cas ou un diagnostic introuvable ;
422 pour un corps invalide (résultat hors enum, preuve absente).

Trace (BE-132 CA-4) : l'ouverture écrit `admin.payment_diagnostic.open`, un échec ou un
résultat non concluant écrit `admin.payment_diagnostic.failure`, une clôture écrit
`admin.payment_diagnostic.close`. Chaque écriture passe par `ecrire_evenement_admin`
(BE-122) dans la transaction du diagnostic.

QE-ADM-BE132 (consignée, appliquée sans attendre) : `escalationId` reste NULL car la table
d'escalade est BE-142, non livrée. Recommandation : renseigner l'escalade quand BE-142
existe, sans changer la règle de chemin d'échec. Le motif de l'action demandée est un
champ d'entrée (`actionDemandee`) : il n'est jamais stocké, seulement refusé.
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
from app.operator.payment_diagnostic import (
    ACTION_CLOTURE,
    ACTION_ECHEC,
    ACTION_OUVERTURE,
    ACTION_PERMISE,
    TYPE_ENTITE_DIAGNOSTIC,
    PaymentDiagnostic,
    erreur_diagnostic_introuvable,
    exiger_pas_d_action_financiere,
    issue_du_diagnostic,
)
router = APIRouter()


class DiagnosticCreate(BaseModel):
    """Corps du diagnostic : les saisies de l'agent. Les décisions viennent du serveur."""

    qualification: str = Field(min_length=1, max_length=200)
    proofConsultedRef: str = Field(min_length=1, max_length=200)
    result: Literal["conforme", "echec", "non_concluant"]
    verificationStatus: Literal["verifiee", "non_verifiee"]
    actionDemandee: str | None = Field(default=None, max_length=60)


class DiagnosticResponse(BaseModel):
    """Représentation d'un diagnostic paiement."""

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
    "/cases/{case_id}/payment-diagnostics",
    response_model=DiagnosticResponse,
    status_code=201,
    summary="Lancer un diagnostic paiement (BE-132)",
)
async def lancer_diagnostic(
    case_id: uuid.UUID,
    data: DiagnosticCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentDiagnostic:
    """Enregistre le diagnostic, déduit son chemin d'échec et sa clôture, puis écrit la trace.

    Ordre des contrôles : cas existant (404), droit de lecture sur le cas (403), action
    financière refusée (403), puis écriture. Une action financière n'écrit rien (CA-2).
    """
    cas: InterventionCase = await charger_cas(db, case_id)
    await exiger_lecture(db, current_user.id, cas)
    exiger_pas_d_action_financiere(data.actionDemandee)

    chemin, cloture = issue_du_diagnostic(data.result, data.verificationStatus)
    diagnostic = PaymentDiagnostic(
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
        summary=f"Diagnostic paiement lancé (résultat {data.result})",
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
            summary=f"Diagnostic paiement en échec : chemin {chemin}",
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
            summary="Diagnostic paiement clos",
            correlation_id=_correlation(),
            changes={"closedAtUtc": cloture.isoformat()},
        )
    await db.commit()
    return diagnostic


@router.get(
    "/cases/{case_id}/payment-diagnostics/{diagnostic_id}",
    response_model=DiagnosticResponse,
    summary="Lire un diagnostic paiement (BE-132)",
)
async def lire_diagnostic(
    case_id: uuid.UUID,
    diagnostic_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentDiagnostic:
    """Lit le diagnostic si le compte peut lire le cas et si le diagnostic appartient à ce cas."""
    cas = await charger_cas(db, case_id)
    await exiger_lecture(db, current_user.id, cas)
    diagnostic = (
        await db.execute(
            select(PaymentDiagnostic).where(
                PaymentDiagnostic.id == diagnostic_id,
                PaymentDiagnostic.caseId == cas.id,
            )
        )
    ).scalar_one_or_none()
    if diagnostic is None:
        raise erreur_diagnostic_introuvable()
    return diagnostic
