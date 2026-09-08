import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PermissionResponse(BaseModel):
    id: uuid.UUID
    code: str
    moduleCode: str
    description: str | None

    model_config = {"from_attributes": True}


class RoleResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    code: str
    name: str

    model_config = {"from_attributes": True}


class RoleDetailResponse(RoleResponse):
    permissionCodes: list[str]


class CreateRoleRequest(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    permissionCodes: list[str] = Field(default_factory=list)


class UpdateRolePermissionsRequest(BaseModel):
    permissionCodes: list[str]


class AssignRoleRequest(BaseModel):
    userId: uuid.UUID
    roleId: uuid.UUID
    # null = organisation entière (comportement historique). Une valeur
    # restreint l'exercice de ce rôle, pour CET utilisateur, à cette
    # ressource précise (ex. "station" + son id) — le contenu du rôle ne
    # change pas, voir `UserRole` (rbac/models.py).
    resourceType: str | None = None
    resourceId: uuid.UUID | None = None


class UserRoleResponse(BaseModel):
    id: uuid.UUID
    userId: uuid.UUID
    organizationId: uuid.UUID
    roleId: uuid.UUID
    resourceType: str | None
    resourceId: uuid.UUID | None

    model_config = {"from_attributes": True}


class UserRoleAssignmentResponse(RoleResponse):
    """Un rôle tel qu'attribué à UN utilisateur précis — porte l'identifiant
    de CETTE attribution (pour pouvoir la retirer sans ambiguïté si le même
    rôle est attribué deux fois à des portées différentes) et sa portée."""

    assignmentId: uuid.UUID
    resourceType: str | None
    resourceId: uuid.UUID | None


class CreateGrantRequest(BaseModel):
    userId: uuid.UUID
    permissionCode: str
    effect: str = Field(pattern="^(allow|deny)$")
    resourceType: str | None = None
    resourceId: uuid.UUID | None = None
    validUntil: datetime | None = None
    auditNote: str | None = None
    delegatedFromGrantId: uuid.UUID | None = None


class GrantResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    userId: uuid.UUID
    permissionId: uuid.UUID
    effect: str
    resourceType: str | None
    resourceId: uuid.UUID | None
    origin: str
    delegatedFromGrantId: uuid.UUID | None
    grantedByUserId: uuid.UUID
    validFrom: datetime
    validUntil: datetime | None
    revokedAt: datetime | None
    auditNote: str | None

    model_config = {"from_attributes": True}


class OrganizationMemberResponse(BaseModel):
    """Utilisateur d'une organisation avec ses rôles — pour la page globale
    Utilisateurs (§14.1 du document d'architecture)."""

    userId: uuid.UUID
    email: str
    fullName: str
    status: str
    roles: list[UserRoleAssignmentResponse]
