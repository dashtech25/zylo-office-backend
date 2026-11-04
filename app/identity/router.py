import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.schemas import UserResponse
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user
from app.identity import service
from app.identity import invitations
from app.identity.models import Organization, User
from app.identity import membres
from app.identity.permissions import (
    MEMBERS_INVITE,
    MEMBERS_READ,
    MEMBERS_REMOVE,
    ORGANIZATION_MANAGE,
    ORGANIZATION_SETTINGS_UPDATE,
    USER_MANAGE,
)
from app.identity.schemas import (
    CreatedUserResponse,
    CreateOrganizationInvitationRequest,
    CreateOrganizationRequest,
    OrganizationInvitationResponse,
    CreateUserRequest,
    OrganizationResponse,
    ReissuedInvitationResponse,
    UpdateOrganizationRequest,
    UpdateUserProfileRequest,
    UpdateUserStatusRequest,
    UserStatusResponse,
)
from app.rbac import affectation_membres
from app.rbac.guards import get_current_organization_id
from app.rbac.permissions import ROLE_MANAGE
from app.rbac.schemas import OrganizationMemberResponse, ReplaceMemberRolesRequest
from app.rbac.service import require_permission

router = APIRouter()

# Router séparé (préfixe /users) monté dans app/main.py à côté du router
# /organizations — un même module `identity` peut exposer plusieurs préfixes,
# jamais un nouveau module pour une seule route.
users_router = APIRouter()

# BE-020 : profil de compte en lecture seule, préfixe /account. Volontairement
# sans route d'édition : PUT et PATCH sur le même chemin renvoient 405 (FastAPI
# répond 405 quand le chemin existe mais que la méthode n'y est pas déclarée).
account_router = APIRouter()


@account_router.get(
    "/profile",
    response_model=UserResponse,
    summary="Lire le profil de l'utilisateur de la session (lecture seule)",
)
async def get_account_profile(current_user: User = Depends(get_current_user)) -> User:
    """Renvoie le profil de l'utilisateur authentifié par la session, et lui seul.

    Intention (BE-020, CA-3) : aucun identifiant d'utilisateur n'est lu dans la
    requête (ni chemin, ni paramètre, ni en-tête). Le profil vient uniquement de
    la session validée par `get_current_user`, ce qui rend impossible de lire le
    profil d'un autre compte par manipulation de la requête.

    Refus : sans session valide, 401 (`get_current_user`). Un compte qui doit
    changer son mot de passe reçoit 403 `password_change_required`, comme les
    autres routes métier ; seul GET /auth/me reste accessible dans ce cas.

    Le schéma `UserResponse` ne contient ni condensat de mot de passe ni secret.
    Aucune route d'édition n'existe ici : le profil se modifie par les routes
    dédiées du socle (changement de mot de passe, BE-018).
    """
    return current_user


@users_router.patch("/{user_id}", response_model=UserResponse)
async def update_user_profile(
    user_id: uuid.UUID,
    data: UpdateUserProfileRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Périmètre volontairement restreint à `photoStorageReference` pour
    l'instant (voir UpdateUserProfileRequest) — self-service ou owner de
    l'organisation de la cible, contrôlé dans `service.update_user_profile`."""
    return await service.update_user_profile(db, user_id, current_user, data)


@router.get("", response_model=list[OrganizationResponse])
async def list_my_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Organization]:
    return await service.list_user_organizations(db, current_user.id)


@router.get("/current", response_model=OrganizationResponse, summary="Lire l'organisation courante validée")
async def get_current_organization(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Résout l'organisation sélectionnée par `X-Organization-Id` après
    validation de l'appartenance active. L'en-tête reste un sélecteur, jamais
    une preuve d'accès; les routes portant un organization_id imposent aussi
    que le chemin et l'en-tête concordent."""
    organization = await db.get(Organization, organization_id)
    # Le résolveur vérifie déjà l'appartenance, mais conserve une erreur métier
    # structurée si la ligne disparaît entre la vérification et la lecture.
    if organization is None:
        raise AppError(code="organization_not_found", message="Organisation introuvable.", status_code=404)
    return organization


@router.get(
    "/current/settings",
    response_model=OrganizationResponse,
    summary="Lire les réglages de l'organisation courante (BE-011)",
)
async def get_current_settings(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Réglages minimaux (nom, identifiant, statut, version) de l'organisation courante.

    Lecture ouverte à tout membre actif, sans permission particulière (BE-011,
    CA-1). L'organisation vient de `X-Organization-Id` validée par la garde
    BE-009 : hors appartenance, 404 `organization_not_found`, jamais une liste vide.
    Réutilise la lecture de GET /organizations/current (BE-010), sans second chemin.
    """
    return await get_current_organization(organization_id=organization_id, db=db)


@router.put(
    "/current/settings",
    response_model=OrganizationResponse,
    summary="Modifier les réglages de l'organisation courante (BE-011)",
)
async def update_current_settings(
    data: UpdateOrganizationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(ORGANIZATION_SETTINGS_UPDATE)),
) -> Organization:
    """Modifie le nom de l'organisation courante et renvoie la ligne relue.

    Corps : `name` (1 à 255 caractères, un nom vide est refusé en 422 avec
    `field_errors`, format BE-001) et `version` optionnelle (BE-233 : une version
    obsolète donne 409 `version_conflict`). Le slug et le statut ne sont pas
    modifiables ici.

    Ordre des contrôles : session (401), appartenance active (404 hors organisation),
    permission `organization.settings.update` (403, rien n'est écrit), puis validation
    du corps (422). Une modification réussie écrit une entrée d'audit
    `identity.organization.update` via `service.update_organization`, dans la même
    transaction que la mutation. Le service est partagé avec PATCH /organizations/{id}.
    """
    return await service.update_organization(db, str(organization_id), current_user.id, data)


@router.get(
    "/current/members",
    response_model=list[OrganizationMemberResponse],
    summary="Lister les membres de l'organisation courante, avec leurs rôles (BE-014)",
    dependencies=[Depends(require_permission(MEMBERS_READ))],
)
async def list_current_members(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Membres de l'organisation validée par la garde BE-009 (`X-Organization-Id`).
    Refus : 404 si l'utilisateur n'est pas membre, 403 sans `organization.members.read`.
    Une liste vide ne signifie jamais un refus : le propriétaire est toujours membre."""
    return await membres.list_members(db, organization_id)


@router.delete(
    "/current/members/{user_id}",
    status_code=204,
    summary="Retirer un membre de l'organisation courante (BE-014)",
    dependencies=[Depends(require_permission(MEMBERS_REMOVE))],
)
async def remove_current_member(
    user_id: uuid.UUID,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Retire l'appartenance et les rôles du membre dans l'organisation courante.
    Refus : 404 si la cible n'est pas membre, 403 si la cible est propriétaire
    et l'acteur ne l'est pas, 409 `last_owner` si le retrait viderait l'organisation
    de son dernier propriétaire actif. Détail et audit : `app/identity/membres.py`."""
    await membres.remove_member(db, organization_id, current_user, user_id)


@router.put(
    "/current/members/{user_id}/roles",
    response_model=OrganizationMemberResponse,
    summary="Fixer les rôles transverses d'un membre de l'organisation courante (BE-015)",
    dependencies=[Depends(require_permission(ROLE_MANAGE))],
)
async def replace_current_member_roles(
    user_id: uuid.UUID,
    data: ReplaceMemberRolesRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Remplace les rôles transverses du membre par `roleIds` et renvoie le membre mis à jour.
    Refus : 403 sans `rbac.role.manage`, 403 `owner_assignment_forbidden` pour le rôle propriétaire
    sans être propriétaire, 404 si la cible n'est pas membre ou si un rôle est d'une autre
    organisation, 409 `last_owner`, 403 `privilege_escalation_denied`. Détail : `app/rbac/affectation_membres.py`."""
    return await affectation_membres.replace_member_roles(db, organization_id, current_user, user_id, data.roleIds)


@router.post("", response_model=OrganizationResponse, status_code=201)
async def create_organization(
    data: CreateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    return await service.create_organization(db, current_user, data)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: str,
    data: UpdateOrganizationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(ORGANIZATION_MANAGE)),
) -> Organization:
    return await service.update_organization(db, organization_id, current_user.id, data)


@router.get("/{organization_id}/protected-demo")
async def protected_demo(
    organization_id: str,
    _: None = Depends(require_permission(ORGANIZATION_MANAGE)),
) -> dict[str, str]:
    """Endpoint de démonstration Phase 5+6 — prouve qu'un accès est bien refusé
    sans la permission identity.organization.manage et accordé avec elle."""
    return {"status": "accès autorisé", "permission": ORGANIZATION_MANAGE}


@router.post(
    "/current/invitations",
    response_model=OrganizationInvitationResponse,
    status_code=201,
    summary="Inviter une personne à rejoindre l'organisation courante (jeton envoyé par e-mail, jamais dans la réponse)",
)
async def create_organization_invitation(
    data: CreateOrganizationInvitationRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(MEMBERS_INVITE)),
) -> OrganizationInvitationResponse:
    """BE-012 : organisation désignée par `X-Organization-Id` (membre actif exigé).
    Permission `organization.members.invite` ; sans elle, 403 et rien n'est créé.
    Rôle proposé hors organisation : 404. Voir `invitations.create_organization_invitation`."""
    return await invitations.create_organization_invitation(db, current_user, organization_id, data)


@router.get(
    "/current/invitations",
    response_model=list[OrganizationInvitationResponse],
    summary="Lister les invitations en attente de l'organisation courante",
)
async def list_organization_invitations(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(MEMBERS_INVITE)),
) -> list[OrganizationInvitationResponse]:
    """BE-012 : seules les invitations `pending` non expirées de l'organisation courante
    (jamais celles d'une autre organisation). Même permission que la création."""
    return await invitations.list_organization_invitations(db, organization_id)


@router.post(
    "/{organization_id}/users",
    response_model=CreatedUserResponse,
    status_code=201,
    summary="Créer un utilisateur dans l'organisation (compte en attente, sans mot de passe connu du créateur)",
)
async def create_user(
    organization_id: uuid.UUID,
    data: CreateUserRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(USER_MANAGE)),
) -> CreatedUserResponse:
    """T-021 : le compte est `pending`. Le titulaire active son compte par le lien
    envoyé hors API (POST /auth/activate). Aucun secret dans la réponse."""
    return await invitations.create_user_account(db, current_user, organization_id, data)


@router.post(
    "/{organization_id}/users/{user_id}/invitation",
    response_model=ReissuedInvitationResponse,
    status_code=201,
    summary="Réémettre le lien d'activation d'un compte en attente (l'ancien lien est révoqué)",
)
async def reissue_user_invitation(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(USER_MANAGE)),
) -> ReissuedInvitationResponse:
    return await invitations.reissue_invitation(db, current_user, organization_id, user_id)


@router.patch(
    "/{organization_id}/users/{user_id}",
    response_model=UserStatusResponse,
    summary="Désactiver (suspended) ou réactiver (active) un membre de l'organisation",
)
async def update_user_status(
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    data: UpdateUserStatusRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_permission(USER_MANAGE)),
) -> UserStatusResponse:
    return await invitations.update_user_status(db, current_user, organization_id, user_id, data.status)
