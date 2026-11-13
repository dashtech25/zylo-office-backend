"""Garde serveur de contexte organisation (BE-009).

Intention : une requête d'organisation n'agit jamais sur une organisation
choisie par le seul client. L'en-tête `X-Organization-Id` (ou l'organisation du
chemin) n'est qu'un sélecteur ; il n'est accepté que si l'utilisateur authentifié
en est membre actif. Toutes les routes d'organisation passent par
`get_current_organization_id`, directement ou via `rbac.service.require_permission`.

Réponses (voir docs/questions/rbac/code-http-acces-interdit.md) :
- session absente ou invalide : 401 (refusé par `get_current_user`) ;
- organisation hors appartenance, inexistante, supprimée ou incohérente entre
  chemin et en-tête : 404 `organization_not_found`, réponse uniforme ;
- membre sans permission : 403 `permission_denied`, levé par `rbac.service`.

Ce module ne dépend ni de `rbac.service` (pas de cycle) ni de `app/modules/`.
"""

import uuid

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity.models import Organization, OrganizationUser, User


# ---------------------------------------------------------------------------
# Périmètre organisationnel : le client ne fait jamais autorité sur le tenant
# (T-010 : IAM-001, IAM-004 ; docs/architecture/bonnes-pratiques/securite-rbac-multitenant.md R1, R2).
#
# Règle unique, appliquée par `get_current_organization_id` à TOUTES les routes
# d'organisation (avec ou sans `{organization_id}` dans le chemin) :
#   1. l'organisation cible est celle du chemin si la route en porte une,
#      sinon celle de l'en-tête `X-Organization-Id` ;
#   2. l'en-tête doit désigner la même organisation que le chemin (sinon refus) ;
#   3. l'utilisateur doit être membre actif de l'organisation cible ;
#   4. toute permission est ensuite évaluée sur CETTE organisation.
# Un refus d'accès à une organisation étrangère ou inexistante répond toujours
# par la même erreur 404 (docs/questions/rbac/code-http-acces-interdit.md,
# option A) : aucune énumération d'identifiants. Un refus de droit au sein de
# la même organisation reste un 403 `permission_denied`.
# ---------------------------------------------------------------------------


def organisation_introuvable() -> AppError:
    """Erreur uniforme : organisation inexistante, supprimée, sans appartenance
    active, ou désignée de façon incohérente entre chemin et en-tête."""
    return AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)


async def assert_active_membership(db: AsyncSession, user_id: uuid.UUID, organization_id: uuid.UUID) -> None:
    """Exige une appartenance (`OrganizationUser`) à une organisation non
    supprimée. Intention : aucune donnée d'une organisation n'est accessible à
    qui n'y appartient pas, même si ce qui suit (rôle, grant) semble l'autoriser."""
    stmt = (
        select(OrganizationUser.id)
        .join(Organization, Organization.id == OrganizationUser.organizationId)
        .where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == user_id,
            # BE-189 : seul un membership actif ouvre une organisation (invited, suspended, revoked refusés).
            OrganizationUser.status == "active",
            Organization.deletedAt.is_(None),
        )
    )
    if (await db.execute(stmt)).first() is None:
        raise organisation_introuvable()


async def assert_target_is_member(db: AsyncSession, organization_id: uuid.UUID, target_user_id: uuid.UUID) -> None:
    """Un rôle ou un grant ne s'accorde qu'à un membre de l'organisation
    (IAM-004). Réponse 404 `user_not_found` : même principe de non-énumération."""
    stmt = select(OrganizationUser.id).where(
        OrganizationUser.organizationId == organization_id, OrganizationUser.userId == target_user_id
    )
    if (await db.execute(stmt)).first() is None:
        raise AppError(code="user_not_found", message="Utilisateur introuvable dans cette organisation.", status_code=404)


def organisation_cible(request: Request, selecteur: uuid.UUID) -> uuid.UUID:
    """Organisation sur laquelle la requête agit. Si la route porte
    `{organization_id}`, c'est elle ; l'en-tête doit alors être identique (un
    sélecteur incohérent est refusé, jamais arbitré). Sinon l'en-tête seul."""
    brut = request.path_params.get("organization_id")
    if brut is None:
        return selecteur
    try:
        cible = uuid.UUID(str(brut))
    except ValueError:
        raise organisation_introuvable()
    if cible != selecteur:
        raise organisation_introuvable()
    return cible


async def get_current_organization_id(
    request: Request,
    x_organization_id: uuid.UUID = Header(..., alias="X-Organization-Id"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> uuid.UUID:
    """Organisation courante, validée : l'en-tête (ou le chemin) n'est qu'un
    sélecteur, accepté seulement si l'utilisateur en est membre actif. Un
    utilisateur pouvant appartenir à plusieurs organisations, elle ne peut pas
    être déduite du seul token JWT."""
    organisation = organisation_cible(request, x_organization_id)
    await assert_active_membership(db, current_user.id, organisation)
    return organisation
