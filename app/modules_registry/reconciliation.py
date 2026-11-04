"""Réconciliation des états incertains (BE-052).

Quand deux sources d'autorité se contredisent sur un sujet (ex. une activation de module), on ouvre un
cas `open` dans `module_reconciliations`. Règles, toutes vérifiées par tests/test_be052_reconciliation.py :

- La réconciliation signale, elle ne décide pas : elle ne modifie jamais l'état du sujet (CA-1).
  Elle compare seulement les valeurs lues, et n'invente jamais un état positif.
- L'ouverture est idempotente sur `idempotency_key` : un événement rejoué renvoie le cas existant (CA-2).
- Tant qu'un cas est `open`, `reconciliation_ouverte_pour` renvoie vrai. BE-053 (accessibilité effective)
  s'appuie sur cette lecture pour refuser `RECONCILIATION_PENDING` (CA-5).
- Résoudre exige une référence de preuve non vide (422, CA-4) et une décision parmi
  `confirm_granted`, `confirm_removed`, `escalate`. `confirm_*` ferme le cas (`resolved`),
  `escalate` le transfère (`escalated`). Un cas déjà traité ne se résout pas une seconde fois (409).
- Le droit de lecture et de résolution (`platform.reconciliation.resolve`) est vérifié par la route,
  pas ici ; ce module ne contrôle que les règles de domaine.

Ce module ne lit ni n'écrit les tables d'un autre module : il ne porte que `module_reconciliations`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules_registry.models import ETATS_RECONCILIATION, ModuleReconciliation

# Décisions acceptées à la résolution, et état du cas qu'elles produisent.
RESOLUTIONS: tuple[str, ...] = ("confirm_granted", "confirm_removed", "escalate")
ETAT_APRES_RESOLUTION: dict[str, str] = {
    "confirm_granted": "resolved",
    "confirm_removed": "resolved",
    "escalate": "escalated",
}


async def ouvrir_cas_si_contradiction(
    db: AsyncSession,
    *,
    subject_type: str,
    subject_id: uuid.UUID,
    organization_id: uuid.UUID,
    source_a: str,
    source_b: str,
    idempotency_key: str,
) -> ModuleReconciliation | None:
    """Ouvre un cas `open` si les deux sources diffèrent ; renvoie le cas, ou None si elles concordent.

    Si un cas existe déjà pour `idempotency_key`, il est renvoyé tel quel : aucun second cas (CA-2).
    Ne modifie aucune autre table, pas même celle du sujet (CA-1). L'appelant valide la transaction.
    """
    if source_a == source_b:
        return None

    existant = (
        await db.execute(select(ModuleReconciliation).where(ModuleReconciliation.idempotencyKey == idempotency_key))
    ).scalar_one_or_none()
    if existant is not None:
        return existant

    cas = ModuleReconciliation(
        subjectType=subject_type,
        subjectId=subject_id,
        organizationId=organization_id,
        state="open",
        sourceA=source_a,
        sourceB=source_b,
        idempotencyKey=idempotency_key,
        openedAt=datetime.now(timezone.utc),
    )
    db.add(cas)
    await db.flush()
    return cas


async def reconciliation_ouverte_pour(
    db: AsyncSession, organization_id: uuid.UUID, subject_type: str, subject_id: uuid.UUID
) -> bool:
    """Vrai tant qu'au moins un cas `open` existe pour ce sujet dans cette organisation (lecture seule).

    BE-053 appelle cette fonction pour refuser l'accès effectif avec `RECONCILIATION_PENDING` (CA-5).
    """
    requete = select(
        exists().where(
            ModuleReconciliation.organizationId == organization_id,
            ModuleReconciliation.subjectType == subject_type,
            ModuleReconciliation.subjectId == subject_id,
            ModuleReconciliation.state == "open",
        )
    )
    return bool((await db.execute(requete)).scalar())


async def lister_cas(db: AsyncSession, state: str) -> list[ModuleReconciliation]:
    """Cas dans l'état demandé, les plus anciens d'abord. Refuse un état hors de `ETATS_RECONCILIATION`."""
    if state not in ETATS_RECONCILIATION:
        raise AppError(code="reconciliation_state_invalide", message="État de réconciliation inconnu.", status_code=422)
    resultat = await db.execute(
        select(ModuleReconciliation).where(ModuleReconciliation.state == state).order_by(ModuleReconciliation.openedAt)
    )
    return list(resultat.scalars().all())


async def resoudre_cas(
    db: AsyncSession,
    *,
    reconciliation_id: uuid.UUID,
    resolution: str,
    evidence_reference: str | None,
    actor_user_id: uuid.UUID,
) -> ModuleReconciliation:
    """Résout un cas `open` avec une décision et une preuve, et journalise l'acteur.

    Erreurs : 422 si la décision est hors liste ou si la preuve est absente ou vide (CA-4) ;
    404 si le cas n'existe pas ; 409 si le cas n'est plus `open`. La preuve est rognée, puis stockée
    telle quelle : c'est une référence (ex. numéro de pièce), jamais un contenu.
    """
    if resolution not in RESOLUTIONS:
        raise AppError(code="reconciliation_resolution_invalide", message="Décision de résolution inconnue.", status_code=422)
    preuve = (evidence_reference or "").strip()
    if not preuve:
        raise AppError(
            code="evidence_reference_requise",
            message="Une référence de preuve est obligatoire pour résoudre un cas de réconciliation.",
            status_code=422,
        )

    cas = (
        await db.execute(select(ModuleReconciliation).where(ModuleReconciliation.id == reconciliation_id))
    ).scalar_one_or_none()
    if cas is None:
        raise AppError(code="reconciliation_not_found", message="Cas de réconciliation introuvable.", status_code=404)
    if cas.state != "open":
        raise AppError(code="reconciliation_deja_traitee", message="Ce cas de réconciliation est déjà traité.", status_code=409)

    cas.state = ETAT_APRES_RESOLUTION[resolution]
    cas.resolution = resolution
    cas.evidenceReference = preuve
    cas.resolvedBy = actor_user_id
    cas.resolvedAt = datetime.now(timezone.utc)
    await db.flush()
    return cas
