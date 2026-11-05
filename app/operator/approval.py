"""Approbation distincte (double validation) des commandes opérateur (BE-128).

Table `admin_command_approval` : la décision d'un approbateur sur une commande
(`approuvee` ou `rejetee`). La clé primaire est `commandId` : une commande reçoit au
plus une décision, et la base tranche une course entre deux approbations simultanées
(la seconde insertion échoue, la transaction est annulée, 409).

Droits (définition BE-128) :
- seul le rôle `approbateur_independant` (`ROLES_APPROBATION`) peut décider, sur la
  portée du tenant de la commande ; tout autre rôle, y compris le responsable de
  gestion qui a initié la commande, reçoit 403 (CA-2) ;
- l'initiateur ne peut pas approuver ni rejeter sa propre commande : 403 (CA-1) ;
- un approbateur sans affectation sur le tenant visé reçoit 403 (CA-5) : la portée
  est une égalité (`tenant:<uuid>` ou `platform`), comme pour BE-124 ;
- une commande déjà décidée (approuvée ou rejetée) ne change plus d'état : toute
  décision ultérieure, par n'importe quel approbateur, renvoie 409 (CA-3).

Ordre des contrôles : existence (404), droit de l'approbateur sur la portée (403),
distinction avec l'initiateur (403), état de la commande (409). Un compte qui a perdu
son droit ne peut donc pas obtenir un 409 qui révélerait l'état de la commande.

État : `approuvee` et `rejetee` sont terminaux. L'effet de l'approbation n'est pas
exécuté ici : il appartient au domaine propriétaire (QE-ADM-22, BE-126).

Le motif (`reasonTicket`) de la décision est conservé dans la ligne de décision ;
il est obligatoire (422 sinon, contrôlé par le schéma de la route).

Ce module réutilise la garde de portée de BE-123 (`app.operator.cases`) et le modèle
de commande de BE-124 (`app.operator.commands`). Il ne dépend d'aucun module métier.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.errors import AppError
from app.operator.cases import erreur_refus, portee_du_cas, roles_actifs_sur_portee
from app.operator.commands import ETAT_INTENTION, AdminCommand, erreur_commande_introuvable

ETAT_APPROUVEE = "approuvee"
ETAT_REJETEE = "rejetee"
DECISIONS = (ETAT_APPROUVEE, ETAT_REJETEE)

# Seul rôle habilité à décider (BE-121, `ROLES_CANDIDATS`). Hypothèse consignée : le
# responsable de gestion n'approuve jamais, il initie (BE-124).
ROLES_APPROBATION = frozenset({"approbateur_independant"})


class AdminCommandApproval(Base):
    """La décision unique prise sur une commande opérateur (BE-128).

    `commandId` est à la fois clé primaire et clé étrangère : une seule décision par
    commande, sans contrainte supplémentaire à maintenir dans le code.
    """

    __tablename__ = "admin_command_approval"
    __table_args__ = (
        CheckConstraint("decision IN ('approuvee', 'rejetee')", name="ck_admin_command_approval_decision"),
        {"comment": "Décision unique d'un approbateur indépendant sur une commande opérateur (BE-128)."},
    )

    commandId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_command.commandId"), primary_key=True,
    )
    approverId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True,
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    decidedAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reasonTicket: Mapped[str] = mapped_column(String(120), nullable=False)


def erreur_approbation_non_distincte() -> AppError:
    """403 : l'initiateur ne décide jamais sur sa propre commande (CA-1)."""
    return AppError(
        code="approval_not_independent",
        message="L'initiateur ne peut pas approuver ni rejeter sa propre commande.",
        status_code=403,
    )


def erreur_deja_decidee() -> AppError:
    """409 : la commande a déjà une décision, elle est terminale (CA-3)."""
    return AppError(
        code="command_already_decided",
        message="Cette commande a déjà reçu une décision : son état est terminal.",
        status_code=409,
    )


async def decider_commande(
    db: AsyncSession,
    *,
    command_id: uuid.UUID,
    approbateur_id: uuid.UUID,
    decision: str,
    motif: str,
) -> AdminCommand:
    """Enregistre la décision (`approuvee` ou `rejetee`) et renvoie la commande mise à jour.

    Lève 404 si la commande n'existe pas, 403 si l'approbateur n'a pas le rôle
    `ROLES_APPROBATION` sur la portée du tenant de la commande (CA-2, CA-5) ou s'il
    est l'initiateur (CA-1), 409 si une décision existe déjà (CA-3). La décision et le
    changement d'état de la commande sont validés dans la même transaction.
    """
    if decision not in DECISIONS:
        raise ValueError(f"Décision inconnue : {decision!r}")
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()

    roles = await roles_actifs_sur_portee(db, approbateur_id, portee_du_cas(commande.tenantId))
    if not roles & ROLES_APPROBATION:
        raise erreur_refus()
    if commande.actorId == approbateur_id:
        raise erreur_approbation_non_distincte()
    if commande.status != ETAT_INTENTION:
        raise erreur_deja_decidee()

    maintenant = datetime.now(timezone.utc)
    db.add(AdminCommandApproval(
        commandId=command_id,
        approverId=approbateur_id,
        decision=decision,
        decidedAtUtc=maintenant,
        reasonTicket=motif,
    ))
    commande.status = decision
    commande.approverId = approbateur_id
    try:
        await db.commit()
    except IntegrityError:
        # Une autre décision a été validée entre la lecture et l'écriture : la clé
        # primaire `commandId` tranche, la décision perdante reçoit 409.
        await db.rollback()
        raise erreur_deja_decidee()
    await db.refresh(commande)
    return commande
