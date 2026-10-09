import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator


class UpdateUserProfileRequest(BaseModel):
    """PATCH /users/{user_id} — pour l'instant, seule la photo de profil est
    modifiable via cet endpoint (périmètre volontairement restreint, voir
    l'audit qui a précédé sa création : aucun endpoint ne permettait de
    modifier un `User` existant). `exclude_unset` (voir `service.py`) fait la
    différence entre "champ absent" (inchangé) et "champ envoyé à `null`"
    (efface la photo) — jamais la même sémantique que `Field` requis."""

    photoStorageReference: str | None = Field(
        default=None,
        max_length=255,
        description="Référence opaque renvoyée par le service de stockage (app.shared.storage) après upload — jamais interprétée ici. `null` efface la photo existante.",
    )


class CreateOrganizationRequest(BaseModel):
    name: str
    slug: str


class UpdateOrganizationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    """POST /organizations/{id}/users — aucun mot de passe : le titulaire le choisit
    lui-même à l'activation (T-049). Le créateur ne fournit que l'identité."""

    email: EmailStr = Field(max_length=320)
    fullName: str = Field(min_length=1, max_length=255)

    @field_validator("fullName")
    @classmethod
    def _nom_non_vide(cls, valeur: str) -> str:
        nettoye = valeur.strip()
        if not nettoye:
            raise ValueError("Le nom complet ne peut pas être vide.")
        return nettoye


class CreatedUserResponse(BaseModel):
    """Réponse de création : identifiant, statut, échéance de l'invitation.
    Jamais de secret (mot de passe, hachage, jeton d'activation)."""

    id: uuid.UUID
    email: str
    fullName: str
    status: str
    organizationId: uuid.UUID
    invitationExpiresAt: datetime


class UpdateUserStatusRequest(BaseModel):
    status: Literal["active", "suspended"]


class UserStatusResponse(BaseModel):
    id: uuid.UUID
    email: str
    fullName: str
    status: str


class ReissuedInvitationResponse(BaseModel):
    userId: uuid.UUID
    invitationExpiresAt: datetime


class ActivateAccountRequest(BaseModel):
    token: str = Field(min_length=20, max_length=200)
    password: str = Field(min_length=8, max_length=255)


class AccountActivatedResponse(BaseModel):
    id: uuid.UUID
    email: str
    status: str
