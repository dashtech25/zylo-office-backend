import uuid

from pydantic import BaseModel, EmailStr, field_validator, model_validator

from app.auth.politique_mot_de_passe import verifie_mot_de_passe


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    fullName: str

    @model_validator(mode="after")
    def _politique_mot_de_passe(self) -> "RegisterRequest":
        # Intention (T-013) : l'e-mail et le nom sont connus ici, donc la règle
        # « pas d'e-mail ni de nom dans le mot de passe » s'applique.
        verifie_mot_de_passe(self.password, email=self.email, nom_complet=self.fullName)
        return self


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
    # Colonnes additives du module Personnel (voir app/identity/models.py) —
    # réutilisées ici plutôt que de dupliquer un second schéma de réponse
    # pour PATCH /users/{user_id} (identity/router.py).
    firstName: str | None = None
    lastName: str | None = None
    phone: str | None = None
    photoStorageReference: str | None = None

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    currentPassword: str
    newPassword: str
    # Optionnel : refresh token de la session qui effectue le changement. Cette
    # session reste ouverte ; toutes les autres sont révoquées (T-020 partiel).
    # Absent : toutes les sessions sont révoquées, la session courante comprise.
    refreshToken: str | None = None

    @field_validator("newPassword")
    @classmethod
    def _politique_mot_de_passe(cls, valeur: str) -> str:
        # Le nom et l'e-mail ne sont vérifiés qu'au service (ils viennent de la base).
        verifie_mot_de_passe(valeur)
        return valeur
