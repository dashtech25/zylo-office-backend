"""Table de classification des champs de payload d'événement (BE-174).

Rôle : déclarer, pour chaque type d'événement et chaque champ de son payload, le niveau de
classification de la donnée et la liste des permissions qui permettent de la recevoir. Sans
ligne déclarée, un champ est refusé à la validation (CA-1) : la minimisation est donc
déclarative, pas une liste noire.

Invariants :
- `(typeEvenement, champ)` est unique : un champ n'a qu'une classification ;
- `classification` appartient à `CLASSIFICATIONS` (contrainte CHECK) ;
- `consommablePar` NULL signifie « aucun consommateur » : le champ n'est jamais exposé
  (recommandation QE-PAR-16 : pas d'accès sans permission explicite).
"""

from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin
from app.securite.classification import CLASSIFICATIONS


class ClassificationChamp(UUIDPrimaryKeyMixin, Base):
    """Une déclaration de classification : un champ d'un type d'événement.

    `consommablePar` est une liste de permissions au format `domaine.entite.action`. Un
    consommateur qui détient au moins une de ces permissions reçoit le champ ; les autres ne le
    reçoivent pas (expurgation, voir `filtrer_payload_pour_consommateur`).
    """

    __tablename__ = "classification_champ"
    __table_args__ = (
        UniqueConstraint("typeEvenement", "champ", name="uq_classification_champ_type_champ"),
        CheckConstraint(
            "classification IN (" + ", ".join(f"'{c}'" for c in CLASSIFICATIONS) + ")",
            name="ck_classification_champ_classification",
        ),
        {"comment": "Classification des champs de payload d'événement et permissions de consommation (BE-174)."},
    )

    typeEvenement: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    champ: Mapped[str] = mapped_column(String(100), nullable=False)
    classification: Mapped[str] = mapped_column(String(32), nullable=False)
    consommablePar: Mapped[list | None] = mapped_column(JSON, nullable=True)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
