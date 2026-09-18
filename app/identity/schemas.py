import uuid

from pydantic import BaseModel, Field


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
