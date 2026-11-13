"""Enregistrement de release (BE-250, table `release_records`).

Une ligne = un artefact versionné présent dans un environnement. La promotion ne
reconstruit rien : elle crée une nouvelle ligne pour l'environnement cible en
recopiant version, hash d'artefact, référence source, SBOM et résultats de gates de
la ligne source. Une ligne n'est jamais modifiée après écriture (preuve de provenance).

Pas de clé étrangère vers `user` : les identifiants de demandeur et d'approbateur
sont conservés tels quels pour rester lisibles même si le compte est supprimé plus tard.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class ReleaseRecord(UUIDPrimaryKeyMixin, Base):
    """Une release présente dans un environnement, avec sa provenance et son approbation."""

    __tablename__ = "release_records"
    __table_args__ = (
        # Une version n'est présente qu'une fois par environnement.
        UniqueConstraint("version", "environnement", name="uq_release_records_version_environnement"),
        {"comment": "Releases versionnées : hash d'artefact, provenance, gates et approbation par environnement."},
    )

    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # SHA-256 hexadécimal de l'artefact : c'est lui qui est promu, jamais une reconstruction.
    hash_artefact: Mapped[str] = mapped_column(String(64), nullable=False)
    reference_source: Mapped[str] = mapped_column(String(255), nullable=False)
    sbom_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    # Version du schéma de configuration attendue par cette release (sert au rollback).
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Résultat par gate, par exemple {"G1": "reussi"}. Une promotion exige les gates requis « reussi ».
    resultats_gates: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    environnement: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    demandeur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approbateur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    promue_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class Compensation(UUIDPrimaryKeyMixin, Base):
    """Action de compensation d'une opération passée, idempotente (BE-252, table `compensations`).

    Une compensation ne réécrit pas l'historique : elle annule l'effet d'une mutation asynchrone
    déjà produite. La clé d'idempotence est unique : redemander la même compensation renvoie la
    ligne existante, jamais une seconde ligne.
    """

    __tablename__ = "compensations"
    __table_args__ = (
        UniqueConstraint("cle_idempotence", name="uq_compensations_cle_idempotence"),
        {"comment": "Compensations de mutations passées : opération d'origine, action, état et idempotence."},
    )

    # Référence de l'opération annulée (identifiant de la mutation asynchrone d'origine).
    operation_origine: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    # Nom de l'action de compensation, résolu par l'appelant dans un registre fermé.
    action_compensation: Mapped[str] = mapped_column(String(64), nullable=False)
    # `en_attente` ou `realisee` ; une compensation réalisée n'est plus rejouée.
    etat: Mapped[str] = mapped_column(String(16), nullable=False)
    cle_idempotence: Mapped[str] = mapped_column(String(128), nullable=False)
    demandeur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    approbateur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    demandee_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    realisee_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
