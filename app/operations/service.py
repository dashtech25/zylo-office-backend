"""Service des opérations asynchrones (BE-236).

Seul endroit qui écrit `Operation.statut`. Les fonctions ne committent pas : la
transaction appartient à l'appelant, pour que la création d'une opération puisse être
faite dans la même transaction que la commande qu'elle décrit.

Transitions autorisées (voir `TRANSITIONS`) :
- recue -> en_cours | echec ;
- en_cours -> succes | echec | inconnu ;
- inconnu -> succes | echec, uniquement si `derniereVerificationAt` est renseigné ;
- succes et echec sont terminaux.

Toute autre transition lève `AppError` 409 `transition_operation_interdite`, sans
modifier la ligne. Les horodatages viennent de `maintenant` (paramètre optionnel, utile
aux tests) ou de l'horloge UTC.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.operations.models import STATUTS_OPERATION, Operation
from app.operations.permissions import OPERATION_READ
from app.operations.schemas import OperationResponse
from app.rbac.service import user_has_permission

TRANSITIONS: dict[str, frozenset[str]] = {
    "recue": frozenset({"en_cours", "echec"}),
    "en_cours": frozenset({"succes", "echec", "inconnu"}),
    "inconnu": frozenset({"succes", "echec"}),
    "succes": frozenset(),
    "echec": frozenset(),
}


def _maintenant(maintenant: datetime | None) -> datetime:
    return maintenant if maintenant is not None else datetime.now(timezone.utc)


async def creer_operation(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    type_operation: str,
    acteur_id: uuid.UUID,
    maintenant: datetime | None = None,
) -> Operation:
    """Crée une opération à l'état « recue », avant tout traitement.

    L'identifiant est généré ici pour être rendu à l'appelant (CA-1) avant que le
    traitement commence. Aucun résultat ni motif n'existe à cette étape.
    """
    instant = _maintenant(maintenant)
    operation = Operation(
        id=uuid.uuid4(),
        tenantId=tenant_id,
        type=type_operation,
        statut="recue",
        transitions=[{"statut": "recue", "horodatage": instant.isoformat()}],
        acteurId=acteur_id,
    )
    db.add(operation)
    await db.flush()
    return operation


async def transitionner(
    db: AsyncSession,
    operation: Operation,
    nouveau_statut: str,
    *,
    maintenant: datetime | None = None,
    resultat: dict | None = None,
    motif_echec: str | None = None,
) -> Operation:
    """Fait passer l'opération à `nouveau_statut` si la transition est permise.

    `resultat` est accepté seulement pour `succes`, `motif_echec` seulement pour `echec`.
    Un `inconnu` résolu en `succes` ou `echec` exige une vérification antérieure
    (`enregistrer_verification`), sinon 409.
    """
    if nouveau_statut not in STATUTS_OPERATION:
        raise AppError(code="statut_operation_inconnu", message="Statut d'opération inconnu.", status_code=422)
    if nouveau_statut not in TRANSITIONS[operation.statut]:
        raise AppError(
            code="transition_operation_interdite",
            message=f"Transition interdite : {operation.statut} vers {nouveau_statut}.",
            status_code=409,
        )
    if operation.statut == "inconnu" and operation.derniereVerificationAt is None:
        raise AppError(
            code="transition_operation_interdite",
            message="Une opération inconnue doit être vérifiée avant d'être tranchée.",
            status_code=409,
        )
    if nouveau_statut == "succes":
        operation.resultat = resultat
    if nouveau_statut == "echec":
        operation.motifEchec = motif_echec

    instant = _maintenant(maintenant)
    operation.statut = nouveau_statut
    operation.transitions = [*operation.transitions, {"statut": nouveau_statut, "horodatage": instant.isoformat()}]
    await db.flush()
    return operation


async def enregistrer_verification(db: AsyncSession, operation: Operation, *, maintenant: datetime | None = None) -> Operation:
    """Note qu'une vérification de l'issue a eu lieu ; condition pour sortir de `inconnu`."""
    operation.derniereVerificationAt = _maintenant(maintenant)
    await db.flush()
    return operation


async def lire_operation(
    db: AsyncSession,
    *,
    operation_id: uuid.UUID,
    organization_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
) -> Operation:
    """Renvoie l'opération si elle appartient au tenant et si le lecteur y a droit.

    Ordre des contrôles : l'opération doit exister dans le tenant (sinon 404, y compris
    pour un autre tenant) ; l'initiateur la lit toujours ; un autre membre doit détenir
    `OPERATION_READ` (sinon 403).
    """
    operation = await db.scalar(
        select(Operation).where(Operation.id == operation_id, Operation.tenantId == organization_id)
    )
    if operation is None:
        raise AppError(code="operation_introuvable", message="Opération introuvable.", status_code=404)
    if operation.acteurId == utilisateur_id:
        return operation
    if not await user_has_permission(db, utilisateur_id, organization_id, OPERATION_READ):
        raise AppError(
            code="permission_denied",
            message=f"Permission manquante : {OPERATION_READ}.",
            status_code=403,
        )
    return operation


def serialiser_operation(operation: Operation) -> OperationResponse:
    """Forme de lecture : `resultat` seulement au succès, `motifEchec` seulement à l'échec.

    Une opération `inconnu` sort avec `resultat` et `motifEchec` nuls (CA-2).
    """
    return OperationResponse(
        operationId=operation.id,
        type=operation.type,
        statut=operation.statut,
        transitions=operation.transitions,
        resultat=operation.resultat if operation.statut == "succes" else None,
        motifEchec=operation.motifEchec if operation.statut == "echec" else None,
        derniereVerificationAt=operation.derniereVerificationAt,
    )
