"""Readiness interne et statut technique opérateur (BE-240).

Ce module porte deux routes, montées dans `app/api/v1/router.py` :

- `GET /api/v1/internal/ready` : readiness réservée au réseau interne. Les
  adresses autorisées sont la liste `HEALTH_INTERNAL_NETWORKS` (CIDR). Liste
  vide, ou pair hors liste : la route répond 404, comme si elle n'existait pas.
- `GET /api/v1/admin/status` : statut technique pour la page d'exploitation
  `/ops/status`. Réservé à l'opérateur habilité (`require_operator`) ; sans
  droit, 403 `operator_access_denied`. Chaque lecture est journalisée dans le
  journal opérateur (`status.read`).

Modèle de réponse commun : `status` global, `verifiedAt` (UTC, moment de la
sonde) et `components`, une entrée par composant avec `name` et `status`.

Statuts de composant, chacun issu d'une sonde :

- `ok` : la sonde a répondu positivement ;
- `unavailable` : la sonde a répondu négativement (base injoignable) ;
- `unknown` : la sonde a échoué de façon inattendue ; l'état est indéterminé.

Règle de sécurité : le statut global vaut `ready` seulement si chaque composant
vaut `ok`. Un composant `unknown` ou `unavailable` donne `not ready` (HTTP 503 sur
la readiness). Un statut indéterminé n'est jamais présenté comme sain.

Garanties de contenu : la réponse ne contient ni message d'erreur, ni URL de
connexion, ni hôte, ni donnée d'utilisateur. Seuls les noms de composant, leur
statut et la date sortent de ce module.

Piège évité : une sonde qui lève une exception inattendue est convertie en
`unknown` et non relancée, sinon la readiness renverrait une erreur 500 sans
information. Après cette exception, un `rollback` est émis pour ne pas laisser
la session dans un état invalide.

Ce module vit dans `app/operator/` (support opérateur) et n'importe que la
sonde de `app/core/health.py`, la garde `require_operator` et le journal
opérateur ; il ne connaît aucun module métier.
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.health import base_repond
from app.identity.models import User
from app.operator.audit import record_operator_read
from app.operator.permissions import require_operator
from app.operator.schemas import ComposantSante, StatutTechnique

STATUT_OK = "ok"
STATUT_INDISPONIBLE = "unavailable"
STATUT_INCONNU = "unknown"

internal_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_operator)])


async def _sonde_base(db: AsyncSession) -> ComposantSante:
    """Interroge la base et classe le résultat en `ok`, `unavailable` ou `unknown`.

    Une sonde qui répond False donne `unavailable`. Toute autre exception
    donne `unknown` : l'état est indéterminé, il n'est donc jamais `ok`.
    """
    try:
        repond = await base_repond(db)
    except Exception:
        await db.rollback()
        return ComposantSante(name="database", status=STATUT_INCONNU)
    return ComposantSante(name="database", status=STATUT_OK if repond else STATUT_INDISPONIBLE)


async def verifie_composants(db: AsyncSession) -> StatutTechnique:
    """Lance toutes les sondes et calcule le statut global.

    Le statut global vaut `ready` seulement si chaque composant vaut `ok`.
    `verifiedAt` est l'horodatage UTC pris après les sondes.
    """
    composants = [await _sonde_base(db)]
    tous_ok = all(c.status == STATUT_OK for c in composants)
    return StatutTechnique(
        status="ready" if tous_ok else "not ready",
        verifiedAt=datetime.now(timezone.utc),
        components=composants,
    )


def _adresse_interne(request: Request) -> bool:
    """Vrai si le pair direct figure dans `HEALTH_INTERNAL_NETWORKS`.

    Liste vide, pair absent ou adresse illisible : faux. Une entrée CIDR
    invalide est ignorée, elle n'élargit jamais l'accès.
    """
    if request.client is None:
        return False
    try:
        adresse = ipaddress.ip_address(request.client.host)
    except ValueError:
        return False
    for entree in settings.HEALTH_INTERNAL_NETWORKS:
        try:
            reseau = ipaddress.ip_network(entree, strict=False)
        except ValueError:
            continue
        if adresse in reseau:
            return True
    return False


@internal_router.get("/internal/ready", response_model=StatutTechnique)
async def readiness_interne(
    request: Request, response: Response, db: AsyncSession = Depends(get_db),
) -> StatutTechnique:
    """Readiness composant par composant, réservée au réseau interne.

    - 200 et `status: ready` quand tous les composants sont `ok` ;
    - 503 et `status: not ready` sinon (un composant `unavailable` ou `unknown`) ;
    - 404 depuis une adresse hors `HEALTH_INTERNAL_NETWORKS`, ou liste vide.

    Sans session ni en-tête d'authentification, car l'orchestrateur interne
    n'en possède pas. La réponse ne contient aucun secret ni donnée personnelle.
    """
    if not _adresse_interne(request):
        raise HTTPException(status_code=404)
    statut = await verifie_composants(db)
    if statut.status != "ready":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return statut


@admin_router.get("/status", response_model=StatutTechnique)
async def statut_operateur(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> StatutTechnique:
    """Statut technique des composants pour l'opérateur habilité.

    Même contenu que la readiness interne, sans code 503 : le statut est porté
    par le corps. Chaque lecture est journalisée (`status.read`, résultat
    `success`). Sans droit opérateur, la garde répond 403 avant cette fonction.
    """
    statut = await verifie_composants(db)
    await record_operator_read(
        db, actor_user_id=current_user.id, scope="platform", action="status.read",
        target_type="service_status", outcome="success", request_id=request.state.request_id,
    )
    return statut
