"""Compensation d'une mutation asynchrone passée (BE-252, table `compensations`).

Deux opérations :
  - `demander_compensation` : enregistre la demande, idempotente sur `cle_idempotence` ;
  - `executer_compensation` : applique l'action au plus une fois, verrou de ligne à l'appui.

Règles :
  - la demande exige `PERMISSION_COMPENSATION` chez l'approbateur, sinon 403 ;
  - l'approbateur doit être distinct du demandeur, sinon 403 ;
  - une compensation `realisee` renvoie la ligne sans rejouer l'action (idempotence) ;
  - une action absente du registre fourni par l'appelant lève 409, sans effet.

Le rollback du binaire (`identifier_rollback`) ne déclenche aucune compensation : restaurer
des données reste une décision explicite passant par cette table (voir docs/release/rollback.md).

Le service ne commit pas : l'appelant possède la transaction. Les permissions sont passées par
l'appelant, déjà résolues par `rbac`, comme dans `app.release.service`.
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.release.models import Compensation
from app.release.permissions import PERMISSION_COMPENSATION

ETAT_EN_ATTENTE = "en_attente"
ETAT_REALISEE = "realisee"

# Une action reçoit la session et la référence de l'opération d'origine, et ne renvoie rien.
ActionCompensation = Callable[[AsyncSession, str], Awaitable[None]]


async def demander_compensation(
    db: AsyncSession,
    *,
    operation_origine: str,
    action_compensation: str,
    cle_idempotence: str,
    demandeur_id: uuid.UUID,
    approbateur_id: uuid.UUID,
    permissions_approbateur: frozenset[str],
) -> Compensation:
    """Enregistre une compensation en attente et la renvoie (non commitée).

    Si une compensation porte déjà `cle_idempotence`, la ligne existante est renvoyée telle
    quelle, sans contrôle de droit supplémentaire ni nouvelle ligne.
    Sans `PERMISSION_COMPENSATION` : 403 `release.compensation.refusee`.
    Approbateur identique au demandeur : 403 `release.compensation.approbation.non_distincte`.
    """
    existante = (await db.execute(
        select(Compensation).where(Compensation.cle_idempotence == cle_idempotence)
    )).scalar_one_or_none()
    if existante is not None:
        return existante

    if PERMISSION_COMPENSATION not in permissions_approbateur:
        raise AppError(
            "release.compensation.refusee",
            "Droit insuffisant pour déclencher une compensation.",
            status_code=403,
        )
    if approbateur_id == demandeur_id:
        raise AppError(
            "release.compensation.approbation.non_distincte",
            "La compensation doit être approuvée par une personne distincte du demandeur.",
            status_code=403,
        )

    compensation = Compensation(
        operation_origine=operation_origine,
        action_compensation=action_compensation,
        etat=ETAT_EN_ATTENTE,
        cle_idempotence=cle_idempotence,
        demandeur_id=demandeur_id,
        approbateur_id=approbateur_id,
        demandee_le=datetime.now(timezone.utc),
        realisee_le=None,
    )
    db.add(compensation)
    await db.flush()
    return compensation


async def executer_compensation(
    db: AsyncSession,
    *,
    compensation_id: uuid.UUID,
    actions: Mapping[str, ActionCompensation],
) -> Compensation:
    """Applique l'action de la compensation une seule fois et la marque `realisee`.

    La ligne est verrouillée (`SELECT ... FOR UPDATE`) : deux exécutions concurrentes se
    succèdent, la seconde voit `realisee` et ne rejoue rien. Une compensation inconnue donne
    404 `release.compensation.introuvable` ; une action absente de `actions` donne 409
    `release.compensation.action.inconnue`, sans modifier la ligne.
    """
    compensation = await db.get(Compensation, compensation_id, with_for_update=True)
    if compensation is None:
        raise AppError("release.compensation.introuvable", "Compensation introuvable.", status_code=404)
    if compensation.etat == ETAT_REALISEE:
        return compensation

    action = actions.get(compensation.action_compensation)
    if action is None:
        raise AppError(
            "release.compensation.action.inconnue",
            "Action de compensation inconnue pour cette opération.",
            status_code=409,
        )
    await action(db, compensation.operation_origine)
    compensation.etat = ETAT_REALISEE
    compensation.realisee_le = datetime.now(timezone.utc)
    await db.flush()
    return compensation
