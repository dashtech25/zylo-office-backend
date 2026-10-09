"""Schémas des rôles de module (T-018)."""

import uuid

from pydantic import BaseModel, Field


class ModuleRoleCreateRequest(BaseModel):
    moduleCode: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=255)
    permissionCodes: list[str] = Field(default_factory=list)


class ModuleRoleResponse(BaseModel):
    id: uuid.UUID
    organizationId: uuid.UUID
    moduleCode: str
    code: str
    name: str


class ModuleRoleAssignRequest(BaseModel):
    userId: uuid.UUID
    roleId: uuid.UUID


class ModuleRoleAssignmentResponse(BaseModel):
    assignmentId: uuid.UUID
    userId: uuid.UUID
    organizationId: uuid.UUID
    roleId: uuid.UUID
    moduleCode: str
    roleCode: str
    roleName: str


class ModuleRightsRoleItem(BaseModel):
    assignmentId: uuid.UUID
    roleId: uuid.UUID
    code: str
    name: str


class ModuleRightsItem(BaseModel):
    moduleCode: str
    active: bool
    roles: list[ModuleRightsRoleItem]
    permissionCodes: list[str]
