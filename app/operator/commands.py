"""Modèle de commande opérateur et idempotence (BE-124).

Table `admin_command` : une commande est une **intention** d'action sensible, pas son
exécution. Elle porte ce que l'opérateur demande (classe, cible, version attendue,
motif, clé d'idempotence) et qui l'a demandée, au nom de quel rôle et sur quelle
portée. L'effet lui-même est appelé chez le domaine propriétaire désigné par
QE-ADM-22 : BE-124 ne l'exécute pas. Les étapes suivantes (prévisualisation BE-125,
garde d'exécution BE-126, approbation BE-128) feront évoluer le `status`.

Idempotence (CA-1, CA-2) : le couple (`actorId`, `idempotencyKey`) est unique. Un
second envoi de la même clé avec le même corps renvoie la commande existante, sans
nouvelle ligne. Avec un corps différent, il renvoie 409 : la clé ne peut pas désigner
deux intentions. La clé est scopée par acteur : deux opérateurs peuvent employer la
même valeur sans se renvoyer la commande de l'autre.

Droits (CA-3, CA-5) : la commande est évaluée sur la portée de sa cible, comme les cas
de BE-123 (`portee_du_cas`). Un rôle habilité sur le tenant A ne vaut rien pour le
tenant B. La matrice `ROLES_PAR_CLASSE` est une hypothèse provisoire : seul le
responsable d'escalade (`securite_incident_commander`) peut demander une commande de
classe sensible, en attendant la décision des propriétaires (QE-ADM-89).

Champs non définis : `expiresAtUtc` reste NULL tant que la durée de validité d'une
intention n'est pas fixée (QE-ADM-90). `approverId` reste NULL jusqu'à BE-128.
`result` reste NULL jusqu'à l'exécution. Le `status` ne prend que la valeur
`intention` à ce stade.

Ce module réutilise la garde de cas de BE-123 (`app.operator.cases`) pour la portée et
les rôles actifs, et le registre des classes de BE-127 (`app.operator.sensitive_classes`)
pour valider `commandType`. Il ne dépend d'aucun module métier.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.errors import AppError
from app.operator.cases import ROLES_GESTION, erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.sensitive_classes import classe_par_code

ETAT_INTENTION = "intention"

# Matrice rôle -> classe, provisoire (QE-ADM-89) : seul le responsable d'escalade
# peut créer une intention de classe sensible.
ROLES_PAR_CLASSE: dict[str, frozenset[str]] = {}


class AdminCommand(Base):
    """Une intention de commande opérateur (BE-124).

    `commandId` est la clé primaire, nommée comme dans la définition. La contrainte
    d'unicité (`actorId`, `idempotencyKey`) porte l'idempotence au niveau base : une
    course entre deux envois identiques est tranchée par la base, pas par le code.
    """

    __tablename__ = "admin_command"
    __table_args__ = (
        UniqueConstraint("actorId", "idempotencyKey", name="uq_admin_command_actor_idempotency"),
        CheckConstraint("status IN ('intention', 'approuvee', 'rejetee')", name="ck_admin_command_status"),
        CheckConstraint("\"commandVersion\" >= 1", name="ck_admin_command_version"),
        {"comment": "Intentions de commande opérateur, idempotentes par acteur (BE-124)."},
    )

    commandId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commandType: Mapped[str] = mapped_column(String(80), nullable=False)
    commandVersion: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    approverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    effectiveRole: Mapped[str] = mapped_column(String(64), nullable=False)
    effectiveScope: Mapped[str] = mapped_column(String(80), nullable=False)
    tenantId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True,
    )
    targetObjectType: Mapped[str] = mapped_column(String(60), nullable=False)
    targetObjectId: Mapped[str] = mapped_column(String(120), nullable=False)
    targetVersionExpected: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasonTicket: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotencyKey: Mapped[str] = mapped_column(String(120), nullable=False)
    correlationId: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ETAT_INTENTION, server_default=ETAT_INTENTION)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    createdAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiresAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


def erreur_commande_introuvable() -> AppError:
    return AppError(code="command_not_found", message="Commande introuvable.", status_code=404)


def erreur_idempotence() -> AppError:
    """409 : la clé a déjà servi à une autre intention (CA-2)."""
    return AppError(
        code="idempotency_conflict",
        message="Cette clé d'idempotence a déjà été utilisée avec un autre corps.",
        status_code=409,
    )


def exiger_classe_connue(command_type: str) -> None:
    """422 si `commandType` n'est pas une classe du registre BE-127."""
    if classe_par_code(command_type) is None:
        raise AppError(
            code="command_type_unknown",
            message="Type de commande inconnu du registre des classes d'action sensible.",
            status_code=422,
        )


async def role_effectif(db: AsyncSession, actor_id: uuid.UUID, command_type: str, tenant_id: uuid.UUID | None) -> str:
    """Rôle qui autorise la commande, sur la portée de la cible ; 403 sinon.

    Une classe absente de `ROLES_PAR_CLASSE` retombe sur les rôles de gestion : la
    matrice reste fermée par défaut (un défaut ouvert accorderait une commande sans
    contrôle). Si plusieurs rôles conviennent, le premier en ordre alphabétique est
    retenu, pour que la réponse soit déterministe.
    """
    habilites = ROLES_PAR_CLASSE.get(command_type, ROLES_GESTION)
    actifs = await roles_actifs_sur_portee(db, actor_id, portee_du_cas(tenant_id))
    retenus = sorted(actifs & habilites)
    if not retenus:
        raise erreur_refus()
    return retenus[0]


def corps_identique(commande: AdminCommand, corps: dict[str, Any]) -> bool:
    """Vrai si le corps renvoyé est celui qui a créé la commande (CA-1 et CA-2).

    Les champs comparés sont ceux du corps d'intention : la clé d'idempotence ellemême
    n'est pas comparée, elle est déjà la clé de recherche.
    """
    return (
        commande.commandType == corps["commandType"]
        and commande.commandVersion == corps["commandVersion"]
        and commande.tenantId == corps["tenantId"]
        and commande.targetObjectType == corps["targetObjectType"]
        and commande.targetObjectId == corps["targetObjectId"]
        and commande.targetVersionExpected == corps["targetVersionExpected"]
        and commande.reasonTicket == corps["reasonTicket"]
    )


async def commande_existante(db: AsyncSession, actor_id: uuid.UUID, cle: str) -> AdminCommand | None:
    """La commande déjà créée par cet acteur avec cette clé, ou None."""
    stmt = select(AdminCommand).where(AdminCommand.actorId == actor_id, AdminCommand.idempotencyKey == cle)
    return (await db.execute(stmt)).scalar_one_or_none()


def nouvelle_commande(
    *,
    corps: dict[str, Any],
    actor_id: uuid.UUID,
    effective_role: str,
    correlation_id: str | None,
) -> AdminCommand:
    """Construit l'intention à partir du corps validé, sans l'ajouter à la session."""
    tenant_id = corps["tenantId"]
    return AdminCommand(
        commandType=corps["commandType"],
        commandVersion=corps["commandVersion"],
        actorId=actor_id,
        approverId=None,
        effectiveRole=effective_role,
        effectiveScope=portee_du_cas(tenant_id),
        tenantId=tenant_id,
        targetObjectType=corps["targetObjectType"],
        targetObjectId=corps["targetObjectId"],
        targetVersionExpected=corps["targetVersionExpected"],
        reasonTicket=corps["reasonTicket"],
        idempotencyKey=corps["idempotencyKey"],
        correlationId=correlation_id,
        status=ETAT_INTENTION,
        result=None,
        createdAtUtc=datetime.now(timezone.utc),
        expiresAtUtc=None,
    )
