"""Prévisualisation et confirmation des commandes opérateur (BE-125).

Table `admin_command_preview` : une preview fige, pour une intention de BE-124, l'état
de l'objet cible au moment où l'opérateur la regarde (`stateSnapshotHash`), ce que la
commande ferait (`effects`), ses bornes (`limits`) et son expiration (`expiresAtUtc`).
Elle n'exécute rien : l'effet reste chez le domaine propriétaire (QE-ADM-22) et son
exécution relève de BE-126.

Cycle :
- `creer_preview` (CA-1) : lit l'état de la cible, vérifie la version attendue, écrit
  une ligne de preview. Aucune ligne métier n'est modifiée : seule la table de preview
  reçoit une ligne.
- `confirmer_preview` : refuse une preview expirée (CA-2), invalidée, ou dont l'état a
  changé depuis (CA-3, comparaison de l'empreinte recalculée). Une preview invalidée par
  expiration ou par changement d'état est marquée (`invalidatedReason`) avant le 409,
  pour que l'invalidation soit persistée et ne se rejoue pas.

Garde de droit (CA-4) : preview et confirmation sont réservées à l'acteur qui a créé
la commande. Un autre compte reçoit 403, même habilité sur la portée.

Isolation (CA-5) : la preview porte le tenant canonique de la commande. Une commande
sans tenant cible (portée plateforme) est refusée en 422 : aucune preview plateforme
n'est définie à ce stade.

Durée (QE-ADM-07) : `expiresAtUtc` vient du réglage `ADMIN_PREVIEW_TTL_SECONDS`, sans
valeur par défaut. Sans réglage, la création de preview est refusée (503) plutôt que de
coder une durée. Les tests fixent le réglage par `monkeypatch`.

Empreinte (QE-ADM-09) : `stateSnapshotHash` est le SHA-256 du JSON canonique de l'état
observable de la cible (version, nom, statut, suppression logique). Toute différence
invalide la preview.

Types d'objets : seul `Tenant` (table `organization`, version BE-233) est lu. Un autre
type d'objet est refusé en 422 tant que son domaine propriétaire n'est pas branché
(QE-ADM-22).

Champ ajouté à la définition : `confirmedAtUtc` (NULL tant que non confirmée), nécessaire
à BE-126 pour savoir quelle preview a été confirmée. Champ `createdAtUtc` ajouté pour
tracer la création.
"""

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.database import Base
from app.core.errors import AppError
from app.core.versioning import lever_conflit_de_version
from app.identity.models import Organization
from app.operator.cases import erreur_refus
from app.operator.commands import AdminCommand, erreur_commande_introuvable

TYPE_OBJET_TENANT = "Tenant"
RAISON_EXPIREE = "expiree"
RAISON_ETAT_MODIFIE = "etat_modifie"


class AdminCommandPreview(Base):
    """Une prévisualisation d'intention de commande (BE-125).

    `stateSnapshotHash` et `effects` sont figés à la création. Seuls `invalidatedReason`
    et `confirmedAtUtc` évoluent, une fois chacun : une preview ne redevient jamais valide.
    """

    __tablename__ = "admin_command_preview"
    __table_args__ = {"comment": "Prévisualisation d'une commande opérateur, expirable et invalidable (BE-125)."}

    previewId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commandId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_command.commandId"), nullable=False, index=True,
    )
    stateSnapshotHash: Mapped[str] = mapped_column(String(64), nullable=False)
    effects: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    expiresAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidatedReason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmedAtUtc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAtUtc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def erreur_preview_introuvable() -> AppError:
    return AppError(code="preview_not_found", message="Prévisualisation introuvable.", status_code=404)


def erreur_preview_invalide(raison: str) -> AppError:
    """409 : la preview ne peut plus être confirmée (expirée, invalidée, état modifié)."""
    return AppError(
        code="preview_invalid",
        message="Cette prévisualisation n'est plus valide. Relancez une prévisualisation.",
        status_code=409,
        details=[{"raison": raison}],
    )


async def commande_de_l_initiateur(db: AsyncSession, command_id: uuid.UUID, actor_id: uuid.UUID) -> AdminCommand:
    """La commande, si `actor_id` en est l'initiateur (CA-4) ; 404 si elle n'existe pas.

    L'ordre compte : l'existence est vérifiée avant le droit, comme en BE-124 ; un autre
    compte ne voit que 403 sur une commande existante.
    """
    commande = await db.get(AdminCommand, command_id)
    if commande is None:
        raise erreur_commande_introuvable()
    if commande.actorId != actor_id:
        raise erreur_refus()
    return commande


async def lire_tenant_cible(db: AsyncSession, commande: AdminCommand) -> Organization:
    """Organisation visée par la commande ; 422 si le type ou l'identifiant ne se lit pas."""
    if commande.targetObjectType != TYPE_OBJET_TENANT:
        raise AppError(
            code="target_type_unsupported",
            message="Type d'objet cible non pris en charge par la prévisualisation.",
            status_code=422,
        )
    try:
        cible_id = uuid.UUID(commande.targetObjectId)
    except ValueError as erreur:
        raise AppError(
            code="target_id_invalid",
            message="Identifiant de cible invalide.",
            status_code=422,
        ) from erreur
    organisation = await db.get(Organization, cible_id)
    if organisation is None:
        raise AppError(code="target_not_found", message="Cible introuvable.", status_code=404)
    return organisation


def etat_observable(commande: AdminCommand, organisation: Organization) -> dict[str, Any]:
    """Champs de la cible qui entrent dans l'empreinte (QE-ADM-09)."""
    return {
        "tenantId": str(commande.tenantId),
        "targetObjectType": commande.targetObjectType,
        "targetObjectId": str(organisation.id),
        "version": organisation.version,
        "name": organisation.name,
        "status": organisation.status,
        "deletedAt": organisation.deletedAt.isoformat() if organisation.deletedAt else None,
    }


def empreinte_etat(etat: dict[str, Any]) -> str:
    """SHA-256 du JSON canonique : deux états égaux donnent le même condensat."""
    canonique = json.dumps(etat, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


async def creer_preview(db: AsyncSession, commande: AdminCommand) -> AdminCommandPreview:
    """Crée la preview de la commande, ou lève 422, 503, 404 ou 409.

    Ordre : tenant cible (422), durée configurée (503), cible lue (404), version attendue
    vérifiée (409 `version_conflict`, BE-233), puis écriture de la seule ligne de preview.
    """
    if commande.tenantId is None:
        raise AppError(
            code="preview_tenant_absent",
            message="La prévisualisation exige un tenant cible.",
            status_code=422,
        )
    duree = settings.ADMIN_PREVIEW_TTL_SECONDS
    if duree is None:
        raise AppError(
            code="preview_duree_non_configuree",
            message="La durée de prévisualisation n'est pas configurée.",
            status_code=503,
        )
    organisation = await lire_tenant_cible(db, commande)
    if commande.targetVersionExpected is not None and organisation.version != commande.targetVersionExpected:
        lever_conflit_de_version(organisation.version, organisation.updatedAt)

    maintenant = datetime.now(timezone.utc)
    etat = etat_observable(commande, organisation)
    preview = AdminCommandPreview(
        commandId=commande.commandId,
        stateSnapshotHash=empreinte_etat(etat),
        effects={
            "commandType": commande.commandType,
            "tenantId": str(commande.tenantId),
            "targetObjectType": commande.targetObjectType,
            "targetObjectId": str(organisation.id),
            "targetVersion": organisation.version,
            "effetsDomaine": "NON DÉFINI : effets détaillés chez le domaine propriétaire (QE-ADM-22)",
        },
        limits={"dureeSecondes": duree, "executionIncluse": False},
        expiresAtUtc=maintenant + timedelta(seconds=duree),
        invalidatedReason=None,
        confirmedAtUtc=None,
        createdAtUtc=maintenant,
    )
    db.add(preview)
    await db.commit()
    await db.refresh(preview)
    return preview


async def confirmer_preview(db: AsyncSession, commande: AdminCommand, preview_id: uuid.UUID) -> AdminCommandPreview:
    """Confirme la preview si elle est encore valide ; sinon 409 après l'avoir invalidée.

    L'expiration est testée avant l'empreinte : une preview expirée reste refusée même si
    l'état n'a pas changé (CA-2). Une invalidation est écrite puis le 409 est levé, pour
    qu'un second essai ne rejoue pas la même vérification.
    """
    preview = await db.get(AdminCommandPreview, preview_id)
    if preview is None or preview.commandId != commande.commandId:
        raise erreur_preview_introuvable()
    if preview.invalidatedReason is not None:
        raise erreur_preview_invalide(preview.invalidatedReason)
    if preview.confirmedAtUtc is not None:
        return preview

    maintenant = datetime.now(timezone.utc)
    if preview.expiresAtUtc <= maintenant:
        preview.invalidatedReason = RAISON_EXPIREE
        await db.commit()
        raise erreur_preview_invalide(RAISON_EXPIREE)

    organisation = await lire_tenant_cible(db, commande)
    if empreinte_etat(etat_observable(commande, organisation)) != preview.stateSnapshotHash:
        preview.invalidatedReason = RAISON_ETAT_MODIFIE
        await db.commit()
        raise erreur_preview_invalide(RAISON_ETAT_MODIFIE)

    preview.confirmedAtUtc = maintenant
    await db.commit()
    await db.refresh(preview)
    return preview
