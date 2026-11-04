"""Table `encryption_keys` : versions des clés de données (BE-231).

Une ligne par version N. `wrappedKey` contient la clé de données ENVELOPPÉE par
la clé maître (core/crypto.py) ; il ne contient jamais la clé en clair. Une
version révoquée garde sa ligne (traçabilité des dates) mais perd son matériel :
`wrappedKey` vaut NULL.

Statuts : `active`, `retiree`, `revoquee` (voir core/crypto.py pour le cycle de vie).
"""

import datetime as dt

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class EncryptionKey(UUIDPrimaryKeyMixin, Base):
    """Une version de clé de données. Aucune colonne ne porte une clé en clair."""

    __tablename__ = "encryption_keys"

    # Numéro de version N, unique : la valeur chiffrée référence cette version.
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    # active | retiree | revoquee (contrainte en migration).
    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    # Clé de données enveloppée par la clé maître ; NULL une fois révoquée.
    wrappedKey: Mapped[str | None] = mapped_column(Text, nullable=True)
    createdAt: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    retiredAt: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
