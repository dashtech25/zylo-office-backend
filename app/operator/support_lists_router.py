"""Listes filtrées des objets de support (BE-131), sous `/api/v1/admin`.

Routes (lecture seule) :
- `GET /api/v1/admin/organizations/{organization_id}/subscriptions`
- `GET /api/v1/admin/organizations/{organization_id}/invoices`
- `GET /api/v1/admin/organizations/{organization_id}/payments`
- `GET /api/v1/admin/organizations/{organization_id}/entitlements`
- `GET /api/v1/admin/organizations/{organization_id}/incidents`

Paramètres communs : `status`, `dateFrom`, `dateTo`, `id`, `limit`, `offset`. Tout
autre paramètre de requête est refusé en 422 (BE-131 CA-2).

Garde : `require_admin_scope` (BE-120), déclarée sur chaque route et sur le montage.
Sans autorité plateforme : 403 avant toute lecture (CA-4). Règles de rattachement,
de portée et de projection : `app/operator/support_lists.py`.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import User
from app.operator.scope import AdminScope, require_admin_scope
from app.operator.support_lists import (
    FILTRES_AUTORISES,
    REGISTRE_LISTES,
    ObjetSupport,
    exiger_lecture,
    lister_objets,
    normaliser_periode,
)
from app.shared.pagination import PaginationParams
from app.shared.schemas import PageMeta

router = APIRouter()

PARAMETRES_PAGINATION = ("limit", "offset")


class FiltresSupport:
    """Filtres communs d'une liste de support, avec la pagination bornée.

    Un paramètre de requête hors de `FILTRES_AUTORISES` et de la pagination est refusé
    en 422 (`filtre_non_autorise`) : c'est la liste blanche de champs filtrables (CA-2).
    """

    def __init__(
        self,
        request: Request,
        pagination: PaginationParams = Depends(),
        status: str | None = Query(None, max_length=50, description="Statut de la ligne (valeur propre à la liste)."),
        date_from: datetime | None = Query(None, alias="dateFrom", description="Début de période, inclus."),
        date_to: datetime | None = Query(None, alias="dateTo", description="Fin de période, incluse."),
        identifiant: uuid.UUID | None = Query(None, alias="id", description="Identifiant exact de la ligne."),
    ) -> None:
        inconnus = sorted(set(request.query_params) - set(FILTRES_AUTORISES) - set(PARAMETRES_PAGINATION))
        if inconnus:
            raise AppError(
                code="filtre_non_autorise",
                message="Filtre non autorisé pour cette liste.",
                status_code=422,
                field_errors={champ: ["filtre non autorisé"] for champ in inconnus},
            )
        self.statut = status
        self.date_debut, self.date_fin = normaliser_periode(date_from, date_to)
        self.identifiant = identifiant
        self.limit = pagination.limit
        self.offset = pagination.offset


async def _repondre(
    db: AsyncSession,
    objet: ObjetSupport,
    *,
    organization_id: uuid.UUID,
    scope: AdminScope,
    acteur: User,
    filtres: FiltresSupport,
) -> dict:
    """Vérifie la portée puis renvoie la page de `objet` au format `Page` (data, meta)."""
    await exiger_lecture(db, acteur_id=acteur.id, scope=scope, organisation_id=organization_id, objet=objet)
    donnees, total = await lister_objets(
        db,
        objet,
        organisation_id=organization_id,
        statut=filtres.statut,
        date_debut=filtres.date_debut,
        date_fin=filtres.date_fin,
        identifiant=filtres.identifiant,
        limit=filtres.limit,
        offset=filtres.offset,
    )
    return {
        "data": donnees,
        "meta": PageMeta(total=total, limit=filtres.limit, offset=filtres.offset).model_dump(),
    }


@router.get(
    "/organizations/{organization_id}/subscriptions",
    summary="Abonnements d'une organisation (console de support, lecture)",
)
async def lister_abonnements(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    filtres: FiltresSupport = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Abonnements de l'organisation, filtrables par statut, période et identifiant."""
    return await _repondre(
        db, REGISTRE_LISTES["subscriptions"], organization_id=organization_id, scope=scope, acteur=current_user, filtres=filtres
    )


@router.get(
    "/organizations/{organization_id}/invoices",
    summary="Factures d'une organisation (console de support, lecture)",
)
async def lister_factures(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    filtres: FiltresSupport = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Factures des abonnements de l'organisation, filtrables par statut, période et identifiant."""
    return await _repondre(
        db, REGISTRE_LISTES["invoices"], organization_id=organization_id, scope=scope, acteur=current_user, filtres=filtres
    )


@router.get(
    "/organizations/{organization_id}/payments",
    summary="Tentatives de paiement d'une organisation (console de support, lecture)",
)
async def lister_paiements(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    filtres: FiltresSupport = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Tentatives de paiement de l'organisation (facture ou checkout), sans lien de paiement ni clé d'idempotence."""
    return await _repondre(
        db, REGISTRE_LISTES["payments"], organization_id=organization_id, scope=scope, acteur=current_user, filtres=filtres
    )


@router.get(
    "/organizations/{organization_id}/entitlements",
    summary="Droits d'une organisation (console de support, lecture)",
)
async def lister_droits(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    filtres: FiltresSupport = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Droits (entitlements) de l'organisation, filtrables par statut, période et identifiant."""
    return await _repondre(
        db, REGISTRE_LISTES["entitlements"], organization_id=organization_id, scope=scope, acteur=current_user, filtres=filtres
    )


@router.get(
    "/organizations/{organization_id}/incidents",
    summary="Incidents d'une organisation (console de support, lecture plateforme)",
)
async def lister_incidents_organisation(
    organization_id: uuid.UUID,
    scope: AdminScope = Depends(require_admin_scope),
    current_user: User = Depends(get_current_user),
    filtres: FiltresSupport = Depends(),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Incidents rattachés à l'organisation. Réservé à la portée plateforme : 403 en portée tenant."""
    return await _repondre(
        db, REGISTRE_LISTES["incidents"], organization_id=organization_id, scope=scope, acteur=current_user, filtres=filtres
    )
