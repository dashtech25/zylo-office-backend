"""Modèles du module Zylo Tanker (supervision de navires pétroliers) —
premier modèle métier réel du module (2026-09-16), après le squelette
`router.py`/`ping`. `Vessel` est l'équivalent, côté navire, de
`zyloLiquidTruck` : juste assez de champs pour servir de cible de FK à
`GpsDevice.vesselId`/`GpsDeviceAssignment.vesselId`/`TruckStopEvent.vesselId`
(généralisation de `app/location/`, voir sa docstring) et de portée
d'organisation pour les alertes de tracking (`app/alerts/models.py`).

Volontairement minimal — pas de capacité, type de navire, équipage :
viendra avec « Gestion des cuves », l'étape suivante annoncée par le
commanditaire, hors périmètre de ce chantier (tracking de position
uniquement)."""

import uuid

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Vessel(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bateau-citerne du réseau — référentiel minimal (nom, code
    d'immatriculation), même esprit que `Truck` côté zylo_liquid. Le code
    reste unique par organisation, même règle que `plateNumber` sur
    `Truck`."""

    __tablename__ = "zyloTankerVessel"
    __table_args__ = (
        UniqueConstraint("organizationId", "code", name="uq_ztVessel_org_code"),
        {"comment": "Bateau-citerne du réseau — référentiel minimal, cible de FK pour le tracking GPS généralisé."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, comment="Immatriculation/code d'identification du navire — unique par organisation.")
