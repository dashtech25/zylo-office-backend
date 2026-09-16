"""Modèle du module Alertes (capacité partagée) — extrait de
`app/modules/zylo_liquid/models.py` (2026-09-15, Phase 3 de la migration
monolithe modulaire, voir ARCHITECTURE.md). Nom de table Postgres
inchangé, seul l'emplacement du code Python bouge. Pas de redesign de
schéma dans cette phase : les FK vers station/camion/cuve/produit restent
strictes, exactement comme avant l'extraction (décision actée dans le plan
de migration — le découplage polymorphe complet d'`Alert`, comme
`Document`/`DocumentLink` en Phase 1, reste une option future si un vrai
besoin apparaît).

`Alert.stationId`/`truckId`/`tankId`/`productId` référencent des tables du
module `zylo_liquid` (`zyloLiquidStation`/`zyloLiquidTruck`/
`zyloLiquidTank`/`zyloLiquidFuelProduct`) mais ce fichier n'importe AUCUN
modèle Python de `zylo_liquid` : SQLAlchemy résout ces FK par nom de table
au moment du mapper configure, tant que les deux modules partagent la même
`Base` (`app.core.database.Base`) — même mécanisme déjà en place pour
`app/location/models.py` vers `zyloLiquidTruck.id` (voir sa docstring),
repris ici à l'identique. `app/alerts/service.py`, en revanche, a besoin
d'importer `Station`/`Truck` de `zylo_liquid.models` pour les jointures de
portée (`list_alerts`/`_get_alert_and_tank`) — dépendance sanctionnée et
documentée dans la docstring de `service.py`, jamais ici dans `models.py`."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Alert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Alerte (Point 2 chapitre 4, Point 13 §13.4) — modèle confirmé absent
    en Phase 1 (Point 2 §7), créé à la construction de l'endpoint 12
    (issue #45). Partage une table unique entre tous les déclencheurs —
    jamais un second modèle d'alerte par famille.

    Refonte alertes Étape 2 (2026-09) — décisions D2/D3/D4 :
    - `stationId` toujours renseigné (portée minimale garantie même sans
      cuve) ; `tankId`/`productId` selon le type (une cuve précise, ou un
      produit à l'échelle de la station — ex. `price_missing`).
    - `sourceType`/`sourceId` : référence logique vers l'entité qui a
      réellement déclenché l'alerte (`DeliveryDetected`, `DeliveryDeclaration`,
      `LeakageRecord`...) — jamais une FK stricte (polymorphe), pour permettre
      un vrai diagnostic sans dupliquer un second schéma par famille.
    - `severity` calculée par le service au moment de la création — plus
      jamais dérivée côté frontend depuis un `Set` de types dupliqué.
    - Cycle de vie à 3 états (`active`/`acknowledged`/`resolved`, D3) :
      l'acquittement (qui/quand) est une déclaration d'intention humaine,
      distincte de la résolution. La résolution elle-même distingue
      `resolutionMethod` : `auto_verified` (le service a relu la condition
      réelle et constaté sa disparition — `resolvedByUserId` reste NULL) vs
      `manual_justified` (aucune vérification automatique possible pour ce
      type, fermeture manuelle avec `resolutionNote` obligatoire et
      `resolvedByUserId` renseigné). Un clic humain ne referme donc plus
      jamais silencieusement une alerte pour laquelle une vérité mesurable
      existe (Point 2 §11 de la mission alertes)."""

    __tablename__ = "zyloLiquidAlert"
    __table_args__ = (
        CheckConstraint(
            "type IN ('level_high','level_high_pre_alarm','level_low','water','leak','sensor_offline',"
            "'delivery_discrepancy','delivery_undeclared','delivery_declaration_pending',"
            "'price_missing','sensor_mapping_missing','calibration_missing','truck_stop_unqualified')",
            name="ck_zlAlert_type",
        ),
        CheckConstraint("status IN ('active','acknowledged','resolved')", name="ck_zlAlert_status"),
        CheckConstraint(
            "severity IN ('critical','high','medium','low')",
            name="ck_zlAlert_severity",
        ),
        CheckConstraint(
            "\"resolutionMethod\" IS NULL OR \"resolutionMethod\" IN ('auto_verified','manual_justified')",
            name="ck_zlAlert_resolutionMethod",
        ),
        # Étape 2 tracking — un camion n'est pas toujours rattaché à une
        # station (arrêt hors lieu connu) : au moins l'un des deux doit
        # être renseigné, jamais une alerte totalement orpheline.
        CheckConstraint("\"stationId\" IS NOT NULL OR \"truckId\" IS NOT NULL", name="ck_zlAlert_station_or_truck"),
        {"comment": "Alerte déclenchée automatiquement — cycle de vie active/acknowledged/resolved (refonte 2026-09, voir docstring)."},
    )

    stationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidStation.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Étape 2 (flux métier) — alerte d'arrêt de camion hors de tout lieu
    # connu, jamais rattachée à une station (le camion peut être n'importe
    # où). Mutuellement complémentaire de stationId, voir CHECK ci-dessus.
    truckId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTruck.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tankId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidTank.id", ondelete="CASCADE"), nullable=True, index=True
    )
    productId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("zyloLiquidFuelProduct.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="active", index=True)

    # Référence logique (jamais une FK stricte — polymorphe par nature) vers
    # l'entité qui a réellement produit l'alerte, pour permettre un
    # diagnostic contextualisé (D4). NULL pour les types sans entité source
    # dédiée (ex. seuils de niveau, dérivés directement de la mesure).
    sourceType: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sourceId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    triggeredAt: Mapped[datetime] = mapped_column(nullable=False)
    triggeredValue: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    thresholdValue: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    acknowledgedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    acknowledgedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )

    resolvedAt: Mapped[datetime | None] = mapped_column(nullable=True)
    resolvedByUserId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="SET NULL"), nullable=True
    )
    resolutionMethod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolutionNote: Mapped[str | None] = mapped_column(Text, nullable=True)
