"""Plans et versions de plan (BE-200), routes montées sous `/api/v1`.

Routes :
- `GET /plans` : liste des plans, avec leur dernière version (lecture publique) ;
- `GET /plans/{plan_code}/versions/{version}` : une version d'un plan (lecture publique) ;
- `POST /admin/plans/{plan_code}/versions` : crée une version (droit `platform.catalog.manage`,
  QE-API-27) ; un changement de prix crée une version, il ne réécrit jamais une version publiée.

Tables : `plan` et `planVersion` existantes (BE-023), camelCase conservé. Le montant est la colonne
`amountMinor`. Aucun montant n'est renvoyé par les réponses : la valeur n'est pas validée
(QE-API-24, CA-5) ; il n'apparaît que dans la requête d'écriture, sans valeur par défaut.

La publication s'appuie sur `app.billing.service.publish_plan_version` (version suivante, ancienne
version passée à `archived`). L'immutabilité est garantie par le listener `before_update` de
`app.billing.models.PlanVersion`.
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import service
from app.billing.models import Plan, PlanVersion
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.modules_registry.permissions import PLATFORM_CATALOG_MANAGE
from app.modules_registry.platform_rights import exiger_droit_plateforme

router = APIRouter()
admin_router = APIRouter()


class PlanLecture(BaseModel):
    """Plan du catalogue avec sa dernière version. Aucun montant (QE-API-24)."""

    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    moduleCode: str
    version: int
    status: str
    currency: str
    periodDays: int


class VersionPlanLecture(BaseModel):
    """Une version de plan. Aucun montant (QE-API-24)."""

    model_config = ConfigDict(from_attributes=True)

    planCode: str
    version: int
    status: str
    currency: str
    periodDays: int
    entitlementCodes: list[str]
    effectiveAt: datetime


class CreerVersionPlanRequest(BaseModel):
    """Corps de création d'une version. Le montant et la devise sont obligatoires (CA-4).

    Aucune valeur par défaut ni exemple sur `amountMinor` : la valeur n'est pas validée (CA-5).
    """

    amountMinor: int = Field(ge=0, description="Montant en unités mineures de la devise.")
    currency: str = Field(min_length=3, max_length=3)
    periodDays: int = Field(ge=1, le=3650)
    entitlementCodes: list[str] = Field(default_factory=list)


async def _version_courante(db: AsyncSession, plan: Plan) -> PlanVersion | None:
    """Dernière version (numéro le plus élevé) d'un plan, ou None s'il n'en a pas."""
    return await db.scalar(
        select(PlanVersion).where(PlanVersion.planId == plan.id).order_by(PlanVersion.version.desc()).limit(1)
    )


@router.get("/plans", response_model=list[PlanLecture], tags=["plans"], summary="Liste des plans du catalogue")
async def lister_plans(db: AsyncSession = Depends(get_db)) -> list[PlanLecture]:
    """Lecture publique : chaque plan avec sa dernière version. Un plan sans version est omis."""
    plans = (await db.scalars(select(Plan).order_by(Plan.code))).all()
    resultat: list[PlanLecture] = []
    for plan in plans:
        version = await _version_courante(db, plan)
        if version is None:
            continue
        resultat.append(PlanLecture(
            code=plan.code, name=plan.name, moduleCode=plan.moduleCode, version=version.version,
            status=version.status, currency=version.currency, periodDays=version.periodDays,
        ))
    return resultat


@router.get(
    "/plans/{plan_code}/versions/{version}",
    response_model=VersionPlanLecture,
    tags=["plans"],
    summary="Une version d'un plan",
)
async def lire_version_plan(plan_code: str, version: int, db: AsyncSession = Depends(get_db)) -> VersionPlanLecture:
    """Lecture publique d'une version. 404 `PLAN_NOT_FOUND` si le plan est inconnu, 404 `PLAN_VERSION_NOT_FOUND` sinon."""
    plan = await db.scalar(select(Plan).where(Plan.code == plan_code))
    if plan is None:
        raise AppError(code="PLAN_NOT_FOUND", message="Plan inconnu.", status_code=404)
    ligne = await db.scalar(select(PlanVersion).where(PlanVersion.planId == plan.id, PlanVersion.version == version))
    if ligne is None:
        raise AppError(code="PLAN_VERSION_NOT_FOUND", message="Version de plan inconnue.", status_code=404)
    return VersionPlanLecture(
        planCode=plan.code, version=ligne.version, status=ligne.status, currency=ligne.currency,
        periodDays=ligne.periodDays, entitlementCodes=list(ligne.entitlementCodes or []),
        effectiveAt=ligne.effectiveAt,
    )


@admin_router.post(
    "/plans/{plan_code}/versions",
    response_model=VersionPlanLecture,
    status_code=201,
    tags=["admin-plans"],
    summary="Crée une version de plan (publication immuable)",
)
async def creer_version_plan(
    plan_code: str,
    corps: CreerVersionPlanRequest,
    db: AsyncSession = Depends(get_db),
    utilisateur: User = Depends(get_current_user),
) -> VersionPlanLecture:
    """Publie une nouvelle version du plan. Droit `platform.catalog.manage` (403 `PERMISSION_DENIED` sinon).

    Réponses : 201, 401 sans session, 403 sans droit, 404 `plan_not_found`, 422 donnée invalide.
    Ne modifie jamais une version existante : la version précédente passe à `archived`.
    """
    exiger_droit_plateforme(utilisateur.id, PLATFORM_CATALOG_MANAGE)
    version = await service.publish_plan_version(
        db,
        plan_code=plan_code,
        amount_minor=corps.amountMinor,
        currency=corps.currency,
        period_days=corps.periodDays,
        entitlement_codes=corps.entitlementCodes,
    )
    return VersionPlanLecture(
        planCode=plan_code, version=version.version, status=version.status, currency=version.currency,
        periodDays=version.periodDays, entitlementCodes=list(version.entitlementCodes or []),
        effectiveAt=version.effectiveAt,
    )
