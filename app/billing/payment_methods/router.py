"""Routes des moyens de paiement, domaine facturation, montées sous `/api/v1/organizations` (BE-116).

- `POST /organizations/{organization_id}/billing/payment-methods` : ajout ou remplacement par token (201) ;
- `POST /organizations/{organization_id}/billing/payment-methods/{method}/select` : sélection (200).

Ordre de contrôle d'une requête : portée et permission (`exiger_action`, 401/403/404) ; donnée de
carte présente dans le corps (400, rien n'est lu ni écrit) ; réauthentification par mot de passe
courant (403) ; validation du corps (422) ; écriture et événement (`service.py`).
"""

import re
import uuid
from typing import Any

from fastapi import APIRouter, Body, Depends
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import PaymentMethodReference
from app.billing.payment_methods.schemas import AjoutMoyenPaiementRequest, MoyenPaiementResponse
from app.billing.payment_methods.service import add_payment_method, select_payment_method
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import get_current_user, verify_password
from app.identity.models import User
from app.rbac.portee_organisation import OrgScope, exiger_action

router = APIRouter()

# Action du portail : sa permission (`billing.payment_method.manage`) est dans POLITIQUE_PORTAIL (BE-116).
PAYMENT_METHOD_PORTAIL_ACTION = "portail.moyen_paiement.gerer"

# Noms de champs qui désignent une donnée de carte, après normalisation (minuscules, sans `_` ni `-`).
CLES_DONNEES_CARTE = frozenset({
    "pan", "cvv", "cvc", "cardnumber", "numerocarte", "cryptogramme",
    "securitycode", "expirydate", "dateexpiration", "expiration",
})
# Une suite de 13 à 19 chiffres (espaces et tirets tolérés) est traitée comme un PAN : une référence
# de token du prestataire n'a pas cette forme. Choix de sûreté : un faux positif refuse, il ne stocke pas.
MOTIF_PAN = re.compile(r"^\d{13,19}$")


def _contient_donnee_carte(valeur: Any) -> bool:
    """Vrai si le corps contient une clé de carte ou une valeur ressemblant à un PAN, à tout niveau.

    Parcourt récursivement dicts et listes. La valeur d'une clé de carte n'est jamais lue ni
    renvoyée : seul le nom de la clé et la forme des chaînes comptent.
    """
    if isinstance(valeur, dict):
        for cle, sous_valeur in valeur.items():
            if isinstance(cle, str) and re.sub(r"[_\-\s]", "", cle).lower() in CLES_DONNEES_CARTE:
                return True
            if _contient_donnee_carte(sous_valeur):
                return True
        return False
    if isinstance(valeur, list):
        return any(_contient_donnee_carte(element) for element in valeur)
    if isinstance(valeur, str):
        return MOTIF_PAN.match(re.sub(r"[\s\-]", "", valeur)) is not None
    return False


def _exiger_donnees_sans_carte(corps: dict[str, Any]) -> None:
    """Refuse 400 `card_data_refused` si le corps contient une donnée de carte ; ne lit rien d'autre."""
    if _contient_donnee_carte(corps):
        raise AppError(
            code="card_data_refused",
            message="Les données de carte ne sont pas acceptées : envoyer une référence de token uniquement.",
            status_code=400,
        )


def _exiger_reauthentification(corps: dict[str, Any], utilisateur: User) -> None:
    """Refuse 403 `reauthentification_requise` si le mot de passe courant est absent ou faux (QE-POR-16)."""
    mot_de_passe = corps.get("motDePasse")
    if not isinstance(mot_de_passe, str) or not verify_password(mot_de_passe, utilisateur.hashedPassword):
        raise AppError(
            code="reauthentification_requise",
            message="Réauthentification requise pour modifier un moyen de paiement.",
            status_code=403,
        )


@router.post(
    "/{organization_id}/billing/payment-methods",
    status_code=201,
    response_model=MoyenPaiementResponse,
    summary="Ajouter ou remplacer un moyen de paiement par token (BE-116)",
)
async def post_payment_method(
    corps: dict[str, Any] = Body(...),
    scope: OrgScope = Depends(exiger_action(PAYMENT_METHOD_PORTAIL_ACTION)),
    utilisateur: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MoyenPaiementResponse:
    """Ajoute une référence de token pour l'organisation du chemin et la sélectionne.

    La méthode précédente est désélectionnée. La réponse ne contient pas le token (CA-2).
    """
    _exiger_donnees_sans_carte(corps)
    _exiger_reauthentification(corps, utilisateur)
    try:
        requete = AjoutMoyenPaiementRequest.model_validate(corps)
    except ValidationError as erreur:
        raise RequestValidationError(erreur.errors())
    ligne = await add_payment_method(db, scope.organization_id, scope.user_id, requete.tokenReference)
    return MoyenPaiementResponse.model_validate(ligne)


@router.post(
    "/{organization_id}/billing/payment-methods/{method}/select",
    response_model=MoyenPaiementResponse,
    summary="Sélectionner un moyen de paiement de l'organisation (BE-116)",
)
async def post_select_payment_method(
    method: uuid.UUID,
    corps: dict[str, Any] = Body(...),
    scope: OrgScope = Depends(exiger_action(PAYMENT_METHOD_PORTAIL_ACTION)),
    utilisateur: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MoyenPaiementResponse:
    """Sélectionne la méthode `method` de l'organisation du chemin ; les autres sont désélectionnées.

    Une méthode inconnue ou d'une autre organisation répond 404 `payment_method_not_found`.
    """
    _exiger_donnees_sans_carte(corps)
    _exiger_reauthentification(corps, utilisateur)
    ligne: PaymentMethodReference = await select_payment_method(db, scope.organization_id, scope.user_id, method)
    return MoyenPaiementResponse.model_validate(ligne)
