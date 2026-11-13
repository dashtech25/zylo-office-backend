"""Table `restore_drills` : un exercice de restauration par ligne (BE-245).

Chaque exercice, réussi ou non, laisse une ligne : c'est la preuve qu'une sauvegarde
(`backup_runs`, BE-244) a été restaurée dans un environnement isolé, avec les invariants
vérifiés et la durée de chaque étape. Un exercice en `echec` ne prouve pas la restauration.

La table ne porte aucun tenant : l'exercice est une opération de plateforme. Le champ
`environnement` contient le nom logique de la base cible, jamais un chemin ou un mot de passe.
"""

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class RestoreDrill(UUIDPrimaryKeyMixin, Base):
    """Résultat d'un exercice de restauration : sauvegarde source, invariants, durées par étape."""

    __tablename__ = "restore_drills"
    __table_args__ = (
        CheckConstraint("resultat IN ('reussie','echec')", name="ck_restore_drills_resultat"),
        {"comment": "Exercices de restauration vérifiée sur base jetable, avec invariants et durées (BE-245)."},
    )

    # Instant de l'exercice (UTC).
    horodatage: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Sauvegarde restaurée ; l'exercice n'existe pas sans elle.
    sauvegarde_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("backup_runs.id"), nullable=False)
    # Compte opérateur qui a lancé l'exercice (le droit est contrôlé avant toute écriture).
    acteur_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Nom logique de la base cible, toujours distinct de la base source.
    environnement: Mapped[str] = mapped_column(String(120), nullable=False)
    # Invariants vérifiés : {nom: booléen}. Tous vrais pour un exercice réussi.
    invariants: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Liste ordonnée de {"etape": str, "duree_ms": int}, dans l'ordre d'exécution.
    durees: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # reussie | echec (contrainte ck_restore_drills_resultat).
    resultat: Mapped[str] = mapped_column(String(20), nullable=False)
