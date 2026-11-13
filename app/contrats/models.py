"""Registre des versions de contrat (BE-215).

Une ligne par couple (`contractName`, `version`). `version` est le numéro de major : un
changement additif reste dans la même version, un changement cassant exige une nouvelle
version (voir `app.contrats.compatibilite`).

`status` vaut `current` (sélectionnable pour une nouvelle souscription) ou `deprecated`
(toujours accepté pour les consommateurs existants, plus sélectionnable). `removedAt`, quand
il est renseigné, retire la version : elle n'est plus acceptée.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class ContractVersion(UUIDPrimaryKeyMixin, Base):
    """Une version d'un contrat d'API ou d'événement, avec son schéma de payload (BE-215)."""

    __tablename__ = "contract_version"
    __table_args__ = (
        UniqueConstraint("contractName", "version", name="uq_contract_version_contract_version"),
        CheckConstraint("version >= 1", name="ck_contract_version_version"),
        CheckConstraint("status IN ('current', 'deprecated')", name="ck_contract_version_status"),
        {"comment": "Registre des versions de contrat : compatibilité, coexistence N/N-1 et dépréciation (BE-215)."},
    )

    contractName: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="current")
    removedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    schemaJson: Mapped[dict] = mapped_column(JSON, nullable=False)
