"""Routes d'intégration, montées sous `/api/v1` par `app/api/v1/router.py`.

Deux familles, sans lien entre elles, réunies ici :

Lettres mortes (BE-165), sous `/integrations` :

- `GET  /integrations/lettres-mortes` : liste des échecs définitifs du tenant courant
  (permission `integrations.read`) ;
- `POST /integrations/lettres-mortes/{lettre_id}/reprises` : reprise manuelle avec motif
  (permission `integrations.manage`).

Le tenant vient toujours du contexte serveur (`get_current_organization_id`), jamais du corps.
La logique reste dans `app/integrations/lettres_mortes.py` ; ce module ne fait que traduire
les appels HTTP. La relance réelle n'a pas d'adaptateur en BE-165 : la route passe une relance
qui ne fait que marquer la reprise, le branchement sur le consommateur est à faire (QE-165-02).

Connecteurs (BE-162), sous `/connecteurs` :

- `GET /connecteurs` : liste des connecteurs visibles par l'organisation courante (lecture) ;
- `POST /connecteurs` : création d'un connecteur tenant, à l'état `création`, `201` ;
- `POST /connecteurs/{id}/transitions` : transition d'état, `200` ou `409` ;
- `PUT /connecteurs/{id}/configuration` : reprise d'une version de configuration.

Organisation : résolue par l'en-tête `X-Organization-Id` via `get_current_organization_id`.
Un non-membre reçoit l'erreur de garde de `app/rbac/guards.py`.

Droits : `GET` exige `integrations.read` ; les écritures exigent `integrations.manage`.
Refus : `403` `PERMISSION_DENIED`. Le contrôle est fait par `exiger_permission`, qui lève le
code du catalogue : `require_permission` renvoie `permission_denied` (minuscules), écart
signalé dans `app/integrations/routes.md`.

Périmètre : les routes ne créent que des connecteurs de portée `tenant`. La portée `global`
reste réservée à l'administration plateforme et n'est pas exposée ici (le registre la
supporte, la route ne la propose pas).

Isolation : la lecture et les écritures passent par le registre (BE-160), qui applique la
règle de portée. Un connecteur d'un autre tenant répond `404` (`TENANT_MISMATCH`) ou
`connecteur_introuvable`, sans révéler son existence.

Configuration : `PUT .../configuration` transmet `validee=False` tant qu'aucun validateur de
configuration de connecteur n'existe. La réponse est donc `409` `CONNECTEUR_CONFIGURATION_NON_VALIDEE`
(échec fermé, QE-BE162-02). Aucun secret ne transite par ces routes.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.ecriture import IdentiteEmettrice
from app.core.database import get_db
from app.core.erreurs.codes import CodeErreur, ErreurCatalogue
from app.core.security import get_current_user
from app.identity.models import User
from app.integrations import registre
from app.integrations.lettres_mortes import lister_lettres_mortes, reprendre_lettre_morte
from app.integrations.models import PORTEE_TENANT, LettreMorte
from app.integrations.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.rbac.guards import get_current_organization_id
from app.rbac.service import user_has_permission

router = APIRouter()
lettres_mortes_router = APIRouter()


def exiger_permission(code: str):
    """Dépendance qui refuse `403` `PERMISSION_DENIED` si le membre n'a pas `code`.

    Même décision que `require_permission` (`user_has_permission`, refus par défaut), avec le
    code du catalogue exigé par la définition BE-162 (CA-3).
    """

    async def dependance(
        current_user: User = Depends(get_current_user),
        organization_id: uuid.UUID = Depends(get_current_organization_id),
        db: AsyncSession = Depends(get_db),
    ) -> None:
        if not await user_has_permission(db, current_user.id, organization_id, code):
            raise ErreurCatalogue(CodeErreur.PERMISSION_DENIED, detail=f"permission manquante : {code}")

    return dependance


class ConnecteurCreation(BaseModel):
    """Corps de `POST /connecteurs`. Le libellé est non vide ; la portée est toujours `tenant`."""

    model_config = ConfigDict(extra="forbid")

    nom: str = Field(min_length=1, max_length=255)


class TransitionDemande(BaseModel):
    """Corps de `POST /connecteurs/{id}/transitions` : l'état cible, un libellé de la définition."""

    model_config = ConfigDict(extra="forbid")

    cible: Literal["activé", "suspendu", "révoqué"]


class ConfigurationDemande(BaseModel):
    """Corps de `PUT /connecteurs/{id}/configuration` : la version à reprendre (au moins 1)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)


class ConnecteurReponse(BaseModel):
    """Forme publique d'un connecteur. Aucun champ de secret ni de configuration brute (CA-4)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nom: str
    portee: str
    etat: str
    versionConfiguration: int
    createdAt: datetime
    updatedAt: datetime


def _identite(current_user: User, organization_id: uuid.UUID) -> IdentiteEmettrice:
    return IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)


@router.get(
    "/connecteurs",
    response_model=list[ConnecteurReponse],
    dependencies=[Depends(exiger_permission(INTEGRATIONS_READ))],
    summary="Lister les connecteurs de l'organisation courante",
)
async def lister_connecteurs(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie les connecteurs du tenant et les connecteurs globaux, jamais ceux d'un autre tenant."""
    return await registre.lister_connecteurs(db, organization_id)


@router.post(
    "/connecteurs",
    response_model=ConnecteurReponse,
    status_code=201,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Créer un connecteur à l'état création",
)
async def creer_connecteur(
    corps: ConnecteurCreation,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Crée un connecteur tenant à l'état `création` (CA-1) et écrit son audit `EVT-INT-01`.

    Refus : `403` `PERMISSION_DENIED` sans `integrations.manage`, sans rien créer (CA-3).
    """
    connecteur = await registre.creer_connecteur(
        db,
        _identite(current_user, organization_id),
        portee=PORTEE_TENANT,
        nom=corps.nom,
        organization_id=organization_id,
    )
    await db.commit()
    await db.refresh(connecteur)
    return connecteur


@router.post(
    "/connecteurs/{connecteur_id}/transitions",
    response_model=ConnecteurReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Transitionner l'état d'un connecteur",
)
async def transitionner_connecteur(
    connecteur_id: uuid.UUID,
    corps: TransitionDemande,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Applique une transition autorisée (`200`, CA-2) ; une transition interdite répond `409`.

    Un connecteur d'un autre tenant répond `404` (`TENANT_MISMATCH`), jamais modifié.
    """
    connecteur = await registre.changer_etat(
        db,
        _identite(current_user, organization_id),
        connecteur_id,
        corps.cible,
    )
    await db.commit()
    await db.refresh(connecteur)
    return connecteur


@router.put(
    "/connecteurs/{connecteur_id}/configuration",
    response_model=ConnecteurReponse,
    dependencies=[Depends(exiger_permission(INTEGRATIONS_MANAGE))],
    summary="Reprendre une version de configuration validée",
)
async def reprendre_configuration(
    connecteur_id: uuid.UUID,
    corps: ConfigurationDemande,
    current_user: User = Depends(get_current_user),
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    db: AsyncSession = Depends(get_db),
):
    """Reprend la version demandée, seulement si elle est validée.

    Aucun validateur de configuration de connecteur n'existe encore : `validee` vaut `False`,
    donc la route répond `409` `CONNECTEUR_CONFIGURATION_NON_VALIDEE` (échec fermé).
    """
    connecteur = await registre.reprendre_configuration(
        db,
        _identite(current_user, organization_id),
        connecteur_id,
        corps.version,
        validee=False,
    )
    await db.commit()
    await db.refresh(connecteur)
    return connecteur


class LettreMorteResponse(BaseModel):
    """Vue d'une lettre morte : aucun contenu d'événement, seulement les métadonnées de reprise."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tentativeId: uuid.UUID
    originalId: uuid.UUID
    motif: str | None
    operateur: uuid.UUID | None
    reprisAt: datetime | None
    createdAt: datetime


class ReprendreLettreRequest(BaseModel):
    """Corps de la reprise : `motif` obligatoire. Vide ou absent, la reprise est refusée en 422."""

    motif: str | None = None


@lettres_mortes_router.get(
    "/lettres-mortes",
    response_model=list[LettreMorteResponse],
    summary="Lister les lettres mortes d'intégration du tenant courant (BE-165)",
)
async def lister(
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[LettreMorte]:
    """Liste les lettres mortes ; exige `integrations.read` (403 sinon, rien n'est lu)."""
    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)
    return await lister_lettres_mortes(db, identite, organization_id)


@lettres_mortes_router.post(
    "/lettres-mortes/{lettre_id}/reprises",
    response_model=LettreMorteResponse,
    summary="Reprendre manuellement une lettre morte, avec motif (BE-165)",
)
async def reprendre(
    lettre_id: uuid.UUID,
    corps: ReprendreLettreRequest,
    organization_id: uuid.UUID = Depends(get_current_organization_id),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LettreMorte:
    """Reprise avec motif (CA-2) ; 403 sans `integrations.manage` (CA-3), 404 hors tenant
    (CA-5), 409 `REPLAY_DUPLICATE` si la lettre a déjà été reprise (CA-4).

    La transaction est validée ici après la mutation et son audit, dans le même appel.
    """

    async def relance_sans_adaptateur(_lettre: LettreMorte) -> None:
        """Pas d'adaptateur d'intégration en BE-165 : la reprise est tracée, la relance est à brancher."""
        return None

    identite = IdentiteEmettrice(user_id=current_user.id, organization_id=organization_id)
    lettre = await reprendre_lettre_morte(
        db,
        identite=identite,
        organization_id=organization_id,
        lettre_id=lettre_id,
        motif=corps.motif,
        relance=relance_sans_adaptateur,
    )
    await db.commit()
    return lettre
