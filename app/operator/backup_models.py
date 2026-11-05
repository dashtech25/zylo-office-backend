"""Table `backup_runs` : une ligne par tentative de sauvegarde de la base (BE-244).

Chaque tentative, réussie ou non, laisse une ligne : c'est la preuve de génération
(CA-1). Une ligne en `echec` n'a pas d'empreinte, car aucun artefact valide n'existe.
La table ne porte aucun tenant : la sauvegarde est une opération de plateforme.
La restauration par tenant n'est pas traitée ici.
"""

import datetime as dt

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class BackupRun(UUIDPrimaryKeyMixin, Base):
    """Résultat d'une sauvegarde : horodatage, périmètre, volume, empreinte, chiffrement."""

    __tablename__ = "backup_runs"
    __table_args__ = (
        CheckConstraint("resultat IN ('reussie','echec')", name="ck_backup_runs_resultat"),
        {"comment": "Tentatives de sauvegarde de la base de plateforme, avec résultat et empreinte (BE-244)."},
    )

    # Instant de la tentative (UTC).
    horodatage: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Périmètre de la sauvegarde ; « plateforme » pour la base complète.
    perimetre: Mapped[str] = mapped_column(String(40), nullable=False)
    # Taille en octets de l'artefact stocké ; NULL si aucun artefact n'a été produit.
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # reussie | echec (contrainte ck_backup_runs_resultat).
    resultat: Mapped[str] = mapped_column(String(20), nullable=False)
    # SHA-256 hexadécimal de l'artefact chiffré tel qu'il est stocké ; NULL en échec.
    empreinte: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Emplacement logique (jamais un chemin absolu de l'hôte).
    emplacement: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Vrai si l'artefact est chiffré par la clé maître (contrôlé avant conservation).
    chiffrement: Mapped[bool] = mapped_column(Boolean, nullable=False)
