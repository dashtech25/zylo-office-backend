"""Idempotence des commandes mutantes (BE-232).

Contrat, pour toute commande qui modifie l'état (POST, PUT, PATCH, DELETE) :

- Le client envoie l'en-tête `Idempotency-Key` (16 à 120 caractères, valeur
  choisie par le client, par exemple un UUID). Il est obligatoire pour les
  routes qui utilisent `require_idempotency_key`.
- La clé est scopée à l'organisation ET à l'acteur : la même valeur envoyée
  par un autre tenant, ou par un autre utilisateur, n'est jamais reconnue
  (CA-3). Le contrôle de droit (`require_permission`) s'exécute AVANT
  `run_idempotent`, car il est une dépendance de la route : un refus renvoie
  403 sans rien mémoriser (CA-4).
- Première réception : la clé est réservée (ligne sans réponse, avec le hash du
  payload), la commande s'exécute dans la même transaction, puis la réponse
  (statut et corps JSON) est mémorisée et la transaction validée. Si la
  commande lève une erreur, la transaction est annulée : ni effet, ni clé.
- Réception répétée, même clé et même payload : la réponse mémorisée est
  rendue, sans nouvelle exécution (CA-1).
- Réception répétée, même clé et payload différent : 409
  `idempotency_key_reused`, sans effet (CA-2).
- Clé expirée (`expiresAt` dépassé, TTL `IDEMPOTENCY_KEY_TTL_HOURS`) : la ligne
  est supprimée et la clé est traitée comme nouvelle (CA-5).
- Réservation concurrente (deux requêtes simultanées avec la même clé) : la
  contrainte unique rejette la seconde ; elle rejoue la réponse si la première
  est terminée, sinon répond 409 `idempotency_key_in_progress`.

Le hash du payload couvre la méthode, le chemin et le corps JSON canonique
(clés triées), pour qu'une même clé ne puisse pas être rejouée sur une autre
commande.

Ce module ne connaît aucun module métier : il reçoit la fonction qui produit
l'effet (`produire`) depuis la route. Il est utilisé par les routes qui le
déclarent ; les endpoints existants (ex. facturation, BE-072) gardent leur
mécanisme propre tant qu'ils ne sont pas migrés.
"""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Header
from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.core.errors import AppError
from app.shared.models import UUIDPrimaryKeyMixin, TimestampMixin

# En-tête lu par `require_idempotency_key`. Bornes : une clé trop courte est
# devinable, une clé trop longue ne tient pas dans la colonne.
EN_TETE_IDEMPOTENCE = "Idempotency-Key"
LONGUEUR_CLE_MIN = 16
LONGUEUR_CLE_MAX = 120


class IdempotencyKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Clé d'idempotence mémorisée pour un couple (organisation, acteur).

    `responseStatus` et `responseBody` restent NULL tant que la commande n'a
    pas terminé : une ligne sans réponse signifie « en cours ».
    """

    __tablename__ = "idempotencyKeys"
    __table_args__ = (
        UniqueConstraint("organizationId", "actorId", "idempotencyKey", name="uq_idempotencyKey_scope"),
        Index("ix_idempotencyKey_expiresAt", "expiresAt"),
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotencyKey: Mapped[str] = mapped_column(String(LONGUEUR_CLE_MAX), nullable=False)
    # SHA-256 hexadécimal de la méthode, du chemin et du corps canonique.
    requestHash: Mapped[str] = mapped_column(String(64), nullable=False)
    responseStatus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    responseBody: Mapped[Any | None] = mapped_column(JSONB, nullable=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class IdempotentResponse:
    """Réponse à rendre au client : statut, corps JSON, et indicateur de rejeu."""

    statut: int
    corps: Any
    rejouee: bool = False


def require_idempotency_key(
    cle: str = Header(..., alias=EN_TETE_IDEMPOTENCE, min_length=LONGUEUR_CLE_MIN, max_length=LONGUEUR_CLE_MAX),
) -> str:
    """Dépendance FastAPI : valide et renvoie la clé d'idempotence de la requête.

    Absente ou hors bornes : 422 géré par l'enveloppe d'erreur (BE-220).
    """
    return cle


def _hash_de_requete(methode: str, chemin: str, charge: Any) -> str:
    """Empreinte stable de la commande. JSON canonique (clés triées, sans espaces)
    pour qu'un même contenu donne toujours le même hash, quel que soit l'ordre
    des champs dans la requête."""
    canonique = json.dumps(
        {"methode": methode, "chemin": chemin, "charge": charge},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str,
    )
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


async def _lire_cle(db: AsyncSession, organisation_id: uuid.UUID, acteur_id: uuid.UUID, cle: str) -> IdempotencyKey | None:
    return await db.scalar(
        select(IdempotencyKey).where(
            IdempotencyKey.organizationId == organisation_id,
            IdempotencyKey.actorId == acteur_id,
            IdempotencyKey.idempotencyKey == cle,
        )
    )


async def run_idempotent(
    db: AsyncSession,
    *,
    cle: str,
    organisation_id: uuid.UUID,
    acteur_id: uuid.UUID,
    methode: str,
    chemin: str,
    charge: Any,
    produire: Callable[[], Awaitable[tuple[int, Any]]],
) -> IdempotentResponse:
    """Exécute la commande une seule fois pour une clé donnée (BE-232).

    `produire` effectue les écritures avec la session `db` SANS valider ; cette
    fonction valide la transaction une seule fois, avec la mémorisation de la
    réponse. Elle renvoie `(statut, corps)` ; le corps doit être sérialisable en
    JSON. Une `AppError` levée par `produire` annule la transaction et n'est pas
    mémorisée : le client peut réessayer la même clé.

    Lève `AppError` 409 si la clé est connue avec un autre payload
    (`idempotency_key_reused`) ou si la commande précédente est encore en cours
    (`idempotency_key_in_progress`).
    """
    empreinte = _hash_de_requete(methode, chemin, charge)
    maintenant = datetime.now(timezone.utc)

    existante = await _lire_cle(db, organisation_id, acteur_id, cle)
    if existante is not None:
        if _expiree(existante, maintenant):
            await db.delete(existante)
            await db.flush()
        else:
            return _reponse_existante(existante, empreinte)

    reservation = IdempotencyKey(
        organizationId=organisation_id,
        actorId=acteur_id,
        idempotencyKey=cle,
        requestHash=empreinte,
        expiresAt=maintenant + timedelta(hours=settings.IDEMPOTENCY_KEY_TTL_HOURS),
    )
    db.add(reservation)
    try:
        await db.flush()
    except IntegrityError:
        # Requête concurrente déjà réservée : on relit la ligne validée (ou non).
        await db.rollback()
        concurrente = await _lire_cle(db, organisation_id, acteur_id, cle)
        if concurrente is None or concurrente.responseStatus is None:
            raise AppError(
                code="idempotency_key_in_progress",
                message="Une commande avec cette clé d'idempotence est déjà en cours.",
                status_code=409,
            ) from None
        return _reponse_existante(concurrente, empreinte)

    try:
        statut, corps = await produire()
    except Exception:
        await db.rollback()
        raise

    reservation.responseStatus = statut
    reservation.responseBody = corps
    await db.commit()
    return IdempotentResponse(statut=statut, corps=corps, rejouee=False)


def _expiree(ligne: IdempotencyKey, maintenant: datetime) -> bool:
    """Une clé dont le TTL est échu est traitée comme jamais vue (CA-5)."""
    return ligne.expiresAt <= maintenant


def _reponse_existante(ligne: IdempotencyKey, empreinte: str) -> IdempotentResponse:
    """Rejoue la réponse mémorisée, ou refuse si le payload diffère (CA-2)."""
    if ligne.requestHash != empreinte:
        raise AppError(
            code="idempotency_key_reused",
            message="Cette clé d'idempotence a déjà été utilisée avec un autre contenu.",
            status_code=409,
        )
    if ligne.responseStatus is None:
        raise AppError(
            code="idempotency_key_in_progress",
            message="Une commande avec cette clé d'idempotence est déjà en cours.",
            status_code=409,
        )
    return IdempotentResponse(statut=ligne.responseStatus, corps=ligne.responseBody, rejouee=True)


async def purger_cles_expirees(db: AsyncSession) -> int:
    """Supprime les clés dont le TTL est échu. Renvoie le nombre de lignes supprimées.

    Appel réservé à une tâche de maintenance ; la lecture ne purge jamais.
    """
    resultat = await db.execute(
        delete(IdempotencyKey).where(IdempotencyKey.expiresAt <= datetime.now(timezone.utc))
    )
    await db.commit()
    return resultat.rowcount or 0
