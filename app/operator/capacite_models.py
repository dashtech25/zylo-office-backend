"""Table `capacity_samples` : échantillons de capacité par service et par tenant (BE-255).

Une ligne par requête (ou tâche) mesurée. Les colonnes sont celles de la définition :
latence, concurrence, taille et coût attribué, rattachés à un service et à un tenant.

Choix de nommage (à confirmer, voir docs/exploitation/capacite.md) :
- `latencyMs` : durée en millisecondes, flottant pour garder les fractions ;
- `sizeBytes` : taille de la charge utile en octets (la définition dit « taille ») ;
- `attributedCostCents` : coût attribué au tenant, en centimes entiers, sans devise
  portée ici (la devise relève du module de facturation, pas de la mesure).

Pas de clé étrangère vers `organization` : la mesure doit rester écrivable même
si le tenant est supprimé ensuite, et ne doit pas bloquer l'écriture d'un tenant
bruyant (CA-2). `tenantId` est donc une simple référence.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class CapacitySample(UUIDPrimaryKeyMixin, Base):
    """Un échantillon de mesure de capacité pour un service et un tenant."""

    __tablename__ = "capacity_samples"
    __table_args__ = {
        "comment": "Échantillons de latence, concurrence, taille et coût attribué par service et tenant (BE-255).",
    }

    # Identifiant stable du service mesuré (ex. « api.stations »).
    service: Mapped[str] = mapped_column(String(120), nullable=False)
    # Organisation (tenant) à laquelle la mesure est attribuée.
    tenantId: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False)
    latencyMs: Mapped[float] = mapped_column(Float, nullable=False)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False)
    sizeBytes: Mapped[int] = mapped_column(Integer, nullable=False)
    attributedCostCents: Mapped[int] = mapped_column(Integer, nullable=False)
    measuredAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
