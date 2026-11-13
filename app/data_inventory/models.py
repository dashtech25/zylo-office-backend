"""Modèle de l'inventaire des données (BE-242).

Une ligne par couple (objet, champ) : elle décrit la finalité, la classe, le
propriétaire, les lecteurs, le transfert, la rétention, la présence en sauvegarde,
l'export et les modalités de suppression. La durée de rétention est un entier
en jours ; NULL signifie « non décidée » (NON DÉFINI) et bloque la suppression
automatique (voir service.py).
"""

from sqlalchemy import Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class DataInventory(UUIDPrimaryKeyMixin, Base):
    """Entrée du registre des données : un champ d'un objet, avec sa gouvernance."""

    __tablename__ = "data_inventory"
    __table_args__ = (
        UniqueConstraint("objet", "champ", name="uq_data_inventory_objet_champ"),
        {"comment": "Inventaire des données : classe, propriétaire, rétention et modalités par champ."},
    )

    objet: Mapped[str] = mapped_column(String(150), nullable=False)  # nom réel de la table
    champ: Mapped[str] = mapped_column(String(150), nullable=False)  # colonne, ou « * » pour l'objet entier
    finalite: Mapped[str | None] = mapped_column(String(300), nullable=True)
    classe: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tenantScope: Mapped[str | None] = mapped_column(String(20), nullable=True)  # « tenant » ou « plateforme »
    proprietaire: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lecteurs: Mapped[str | None] = mapped_column(String(300), nullable=True)
    transfert: Mapped[str | None] = mapped_column(String(300), nullable=True)
    retentionJours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # NULL = NON DÉFINI
    sauvegarde: Mapped[str | None] = mapped_column(String(100), nullable=True)
    export: Mapped[str | None] = mapped_column(String(100), nullable=True)
    suppression: Mapped[str | None] = mapped_column(String(300), nullable=True)
