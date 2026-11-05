"""Table `tenant` (BE-185).

Un tenant porte son état de cycle de vie (`state`) et un verrou de version
(`version`, +1 à chaque transition). `tenantId` est la clé primaire : elle sert
aussi d'identifiant opaque côté API (BE-182).

Le graphe des états est dans `machine.py` ; la contrainte `ck_tenant_state`
refuse en base une valeur hors des six états connus, même si le service était
contourné. Le slug est unique : deux tenants ne partagent jamais le même
identifiant lisible.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.tenants.machine import ETATS_TENANT


class Tenant(Base):
    """Tenant de la plateforme : une ligne par client, du demande de création à la fermeture.

    `closedAt` n'est renseigné qu'à la transition vers `closed`. Une ligne fermée n'est
    jamais supprimée : elle reste lisible par la plateforme et invisible aux membres.
    """

    __tablename__ = "tenant"
    __table_args__ = (
        CheckConstraint(
            "state IN (" + ", ".join(f"'{etat}'" for etat in ETATS_TENANT) + ")",
            name="ck_tenant_state",
        ),
        {"comment": "Tenant de la plateforme : cycle de vie (BE-185), état et verrou de version."},
    )

    tenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    closedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
