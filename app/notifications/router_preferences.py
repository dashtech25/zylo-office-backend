"""Routes des préférences de notification par catégorie (BE-212).

Montées sous `/api/v1/notification-preferences` (voir `app/api/v1/router.py`). Elles
s'appuient sur le service des préférences de BE-168 (`app.notifications.preferences`) :
aucune table ni logique de consentement n'est dupliquée ici. Chaque utilisateur ne lit
et ne modifie que sa propre préférence, car l'identifiant vient du jeton et non du chemin.
"""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.identity.models import User
from app.notifications import preferences as preferences_service
from app.notifications.models import PreferenceNotification
from app.notifications.schemas import PreferenceCategorieRequest, PreferenceCategorieResponse
from app.rbac.service import get_current_organization_id

router = APIRouter()


def _vers_reponse(ligne: PreferenceNotification) -> PreferenceCategorieResponse:
    """Traduit une ligne `preference_notification` vers le vocabulaire de la définition BE-212."""
    return PreferenceCategorieResponse(
        category=ligne.categorieCode,
        enabled=ligne.consentement,
        updatedAt=ligne.horodatageConsentement,
    )


@router.get(
    "",
    response_model=list[PreferenceCategorieResponse],
    summary="Préférences de notification par catégorie de l'utilisateur courant",
    description="Une entrée par catégorie renseignée. Une catégorie sans entrée n'a pas de préférence enregistrée.",
)
async def lire_preferences_categories(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PreferenceCategorieResponse]:
    lignes = await preferences_service.lire_preferences(
        db, organization_id=organization_id, acteur_id=current_user.id, utilisateur_id=current_user.id
    )
    return [_vers_reponse(ligne) for ligne in lignes]


@router.put(
    "",
    response_model=PreferenceCategorieResponse,
    summary="Modifier la préférence d'une catégorie",
    description="Enregistre le choix de l'utilisateur courant pour la catégorie du corps. Catégorie inconnue : 422.",
)
async def modifier_preference_categorie(
    data: PreferenceCategorieRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PreferenceCategorieResponse:
    ligne = await preferences_service.definir_preference_categorie(
        db,
        organization_id=organization_id,
        acteur_id=current_user.id,
        categorie=data.category,
        enabled=data.enabled,
    )
    return _vers_reponse(ligne)
