import uuid

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    fullName: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refreshToken: str


class TokenResponse(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    fullName: str
    status: str
    # Module Personnel — vrai après une création de compte par un tiers
    # (mot de passe temporaire) : le frontend force l'écran de changement
    # avant tout accès normal à l'application.
    mustChangePassword: bool = False

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str = Field(min_length=8)
