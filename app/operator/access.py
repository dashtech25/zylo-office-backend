"""Accès opérateur nominatif, JIT et approbation (BE-229).

Un opérateur de support n'agit sur le contenu d'un tenant qu'avec un accès
explicitement demandé, approuvé par un autre opérateur, limité à un tenant et à
une action, et borné dans le temps. Tant que cet accès n'est pas accordé, la
décision `exiger_acces_operateur` refuse.

Table `operator_access_request` : une ligne par demande. Son cycle de vie suit
`status` :
- `demandee` : demande créée, en attente d'approbation ;
- `approuvee` : accès accordé, valable jusqu'à `expiresAt` ;
- `revoquee` : accès retiré par un opérateur, effet immédiat (`revokedAt`).
Aucune ligne n'est supprimée : la trace de chaque accès reste lisible.

Routes (préfixe `/api/v1/admin`, toutes gardées par `require_operator`, allowlist
serveur `OPERATOR_READ_USER_IDS`) :
- `POST /access-requests` : crée une demande (201). Corps : `tenantId`, `action`,
  `motif`, `dureeMinutes`. Tenant absent : 404. Opérateur hors allowlist : 403.
- `POST /access-requests/{request_id}/approve` : approuve (200). Auto-approbation
  refusée (403) ; approbateur hors allowlist (403) ; demande expirée (403) ;
  demande déjà décidée (409).
- `DELETE /access-requests/{request_id}` : révoque (200). Tout opérateur de
  l'allowlist peut révoquer. Déjà révoquée : 409.

Décisions de conception (hypothèses, DELAI et BORNES non définis par la définition,
à confirmer) :
- la demande vaut `DELAI_DEMANDE` (1 h) ; passé ce délai elle ne peut plus être
  approuvée ;
- la durée accordée est `dureeMinutes`, bornée à `DUREE_MAX_MINUTES` (240) ;
- l'impersonation n'existe pas dans l'API : aucune route ne permet d'agir au nom
  d'un autre compte (CA-6, testé par inventaire des routes).

Pourquoi une décision unique `exiger_acces_operateur` : les routes de support qui
lisent un tenant doivent appeler cette fonction, pour que la règle (allowlist,
tenant, action, échéance, révocation) soit écrite une seule fois.
"""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base, get_db
from app.core.errors import AppError
from app.identity.models import Organization, User
from app.operator.permissions import assert_operator_user, require_operator

ETAT_DEMANDEE = "demandee"
ETAT_APPROUVEE = "approuvee"
ETAT_REVOQUEE = "revoquee"

DELAI_DEMANDE = timedelta(hours=1)
DUREE_MAX_MINUTES = 240

CODE_ACCES_REFUSE = "operator_access_not_granted"
CODE_AUTO_APPROBATION = "operator_access_self_approval"
CODE_DEMANDE_EXPIREE = "operator_access_request_expired"
CODE_DEJA_DECIDEE = "operator_access_request_already_decided"


class OperatorAccessRequest(Base):
    """Une demande d'accès opérateur à un tenant, pour une action, durée bornée (BE-229).

    `operatorId` est le demandeur, `approverId` l'approbateur (distinct). `expiresAt`
    a deux sens selon l'état : échéance de la demande tant qu'elle est `demandee`,
    fin de l'accès une fois `approuvee`. `revokedAt` non nul rend l'accès refusé
    immédiatement, sans attendre `expiresAt`.
    """

    __tablename__ = "operator_access_request"
    __table_args__ = (
        CheckConstraint(
            "status IN ('demandee', 'approuvee', 'revoquee')",
            name="ck_operator_access_request_status",
        ),
        CheckConstraint(
            f"\"dureeMinutes\" >= 1 AND \"dureeMinutes\" <= {DUREE_MAX_MINUTES}",
            name="ck_operator_access_request_duree",
        ),
        {"comment": "Demandes et accès opérateur nominatifs, JIT et approuvés (BE-229)."},
    )

    accessRequestId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operatorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    tenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    motif: Mapped[str] = mapped_column(String(500), nullable=False)
    dureeMinutes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ETAT_DEMANDEE)
    requestedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    approverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    approvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedById: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)


class CreationAccesOperateur(BaseModel):
    """Corps de demande d'accès. `motif` est obligatoire : il reste dans la trace."""

    tenantId: uuid.UUID
    action: str = Field(min_length=1, max_length=64)
    motif: str = Field(min_length=1, max_length=500)
    dureeMinutes: int = Field(ge=1, le=DUREE_MAX_MINUTES)


class AccesOperateurOut(BaseModel):
    """Représentation d'une demande ou d'un accès opérateur."""

    accessRequestId: uuid.UUID
    operatorId: uuid.UUID
    tenantId: uuid.UUID
    action: str
    motif: str
    dureeMinutes: int
    status: str
    requestedAt: datetime
    expiresAt: datetime
    approverId: uuid.UUID | None
    approvedAt: datetime | None
    revokedAt: datetime | None

    model_config = {"from_attributes": True}


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _refus(code: str, message: str) -> AppError:
    return AppError(code=code, message=message, status_code=403)


async def exiger_acces_operateur(
    db: AsyncSession,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    action: str,
    now: datetime | None = None,
) -> None:
    """Lève 403 sauf si `user_id` détient un accès approuvé, valide et non révoqué.

    Conditions cumulées : le compte figure encore dans l'allowlist serveur (CA-1) ;
    une ligne `approuvee` existe pour ce compte, ce `tenant_id` et cette `action`
    (CA-5) ; `now` est strictement avant `expiresAt` (CA-3) ; `revokedAt` est vide
    (CA-4). `now` est injectable pour les tests ; par défaut l'heure UTC courante.
    """
    assert_operator_user(user_id)
    instant = now or _maintenant()
    acces = (await db.scalars(
        select(OperatorAccessRequest).where(
            OperatorAccessRequest.operatorId == user_id,
            OperatorAccessRequest.tenantId == tenant_id,
            OperatorAccessRequest.action == action,
            OperatorAccessRequest.status == ETAT_APPROUVEE,
            OperatorAccessRequest.revokedAt.is_(None),
            OperatorAccessRequest.expiresAt > instant,
        ).limit(1)
    )).first()
    if acces is None:
        raise _refus(CODE_ACCES_REFUSE, "Aucun accès opérateur valide pour ce tenant et cette action.")


router = APIRouter()


async def _demande_ou_404(db: AsyncSession, request_id: uuid.UUID) -> OperatorAccessRequest:
    demande = await db.get(OperatorAccessRequest, request_id)
    if demande is None:
        raise AppError(code="operator_access_request_not_found", message="Demande d'accès introuvable.", status_code=404)
    return demande


@router.post(
    "/access-requests",
    status_code=201,
    response_model=AccesOperateurOut,
    summary="Demander un accès opérateur à un tenant (BE-229)",
    responses={403: {"description": "Opérateur hors allowlist."}, 404: {"description": "Tenant absent."}},
)
async def creer_demande_acces(
    data: CreationAccesOperateur,
    operateur: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> OperatorAccessRequest:
    """Crée une demande en attente d'approbation, valable `DELAI_DEMANDE`."""
    if await db.get(Organization, data.tenantId) is None:
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    maintenant = _maintenant()
    demande = OperatorAccessRequest(
        operatorId=operateur.id,
        tenantId=data.tenantId,
        action=data.action,
        motif=data.motif,
        dureeMinutes=data.dureeMinutes,
        status=ETAT_DEMANDEE,
        requestedAt=maintenant,
        expiresAt=maintenant + DELAI_DEMANDE,
    )
    db.add(demande)
    await db.commit()
    await db.refresh(demande)
    return demande


@router.post(
    "/access-requests/{request_id}/approve",
    response_model=AccesOperateurOut,
    summary="Approuver une demande d'accès opérateur (BE-229)",
    responses={
        403: {"description": "Auto-approbation, approbateur hors allowlist ou demande expirée."},
        404: {"description": "Demande introuvable."},
        409: {"description": "Demande déjà décidée."},
    },
)
async def approuver_demande_acces(
    request_id: uuid.UUID,
    approbateur: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> OperatorAccessRequest:
    """Accorde l'accès : `expiresAt` = maintenant + `dureeMinutes`.

    L'ordre des contrôles est : existence (404), distinction avec le demandeur (403),
    échéance de la demande (403), état (409). Un demandeur ne peut donc pas découvrir
    l'état d'une demande qu'il n'a pas le droit d'approuver.
    """
    demande = await _demande_ou_404(db, request_id)
    if demande.operatorId == approbateur.id:
        raise _refus(CODE_AUTO_APPROBATION, "Un opérateur ne peut pas approuver sa propre demande.")
    maintenant = _maintenant()
    if demande.status == ETAT_DEMANDEE and demande.expiresAt <= maintenant:
        raise _refus(CODE_DEMANDE_EXPIREE, "La demande d'accès a expiré.")
    if demande.status != ETAT_DEMANDEE:
        raise AppError(code=CODE_DEJA_DECIDEE, message="La demande a déjà été décidée.", status_code=409)
    demande.status = ETAT_APPROUVEE
    demande.approverId = approbateur.id
    demande.approvedAt = maintenant
    demande.expiresAt = maintenant + timedelta(minutes=demande.dureeMinutes)
    await db.commit()
    await db.refresh(demande)
    return demande


@router.delete(
    "/access-requests/{request_id}",
    response_model=AccesOperateurOut,
    summary="Révoquer un accès opérateur (BE-229)",
    responses={
        403: {"description": "Opérateur hors allowlist."},
        404: {"description": "Demande introuvable."},
        409: {"description": "Demande déjà révoquée."},
    },
)
async def revoquer_acces(
    request_id: uuid.UUID,
    operateur: User = Depends(require_operator),
    db: AsyncSession = Depends(get_db),
) -> OperatorAccessRequest:
    """Révoque immédiatement : `exiger_acces_operateur` refuse dès le commit."""
    demande = await _demande_ou_404(db, request_id)
    if demande.status == ETAT_REVOQUEE:
        raise AppError(code="operator_access_already_revoked", message="L'accès a déjà été révoqué.", status_code=409)
    demande.status = ETAT_REVOQUEE
    demande.revokedAt = _maintenant()
    demande.revokedById = operateur.id
    await db.commit()
    await db.refresh(demande)
    return demande
