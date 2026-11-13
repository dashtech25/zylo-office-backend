"""Table `operations` (BE-236).

Une ligne par opération asynchrone. Les colonnes suivent la définition :
type, statut, transitions horodatées, acteur initiateur, résultat, motif d'échec et
date de la dernière vérification (utilisée pour sortir de `inconnu`).

Invariants garantis en base :
- `statut` appartient à l'ensemble fermé des cinq états ;
- `tenantId` est obligatoire : une opération n'existe jamais hors tenant.

Les règles de transition ne sont pas en base : elles sont dans `service.py`, seul
endroit qui écrit `statut`.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

STATUTS_OPERATION = ("recue", "en_cours", "succes", "echec", "inconnu")


class Operation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une opération asynchrone rattachée à un tenant et à son initiateur.

    `transitions` est la liste ordonnée des changements d'état, chacun horodaté
    (`{"statut": ..., "horodatage": ...}`). `resultat` n'est renseigné qu'au succès,
    `motifEchec` qu'à l'échec ; ils restent nuls pour `inconnu`.
    """

    __tablename__ = "operations"
    __table_args__ = (
        CheckConstraint(
            "statut IN ('recue', 'en_cours', 'succes', 'echec', 'inconnu')",
            name="ck_operations_statut",
        ),
        {"comment": "Opérations asynchrones consultables : état, transitions horodatées, résultat ou motif d'échec (BE-236)."},
    )

    tenantId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, comment="Tenant propriétaire."
    )
    type: Mapped[str] = mapped_column(String(100), nullable=False, comment="Type d'opération, sous forme domaine.action.")
    statut: Mapped[str] = mapped_column(String(20), nullable=False, index=True, comment="État courant parmi STATUTS_OPERATION.")
    transitions: Mapped[list] = mapped_column(JSON, nullable=False, comment="Historique ordonné des transitions, horodatées.")
    acteurId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True, comment="Initiateur de l'opération."
    )
    resultat: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Résultat, renseigné au succès seulement.")
    motifEchec: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="Motif, renseigné à l'échec seulement.")
    derniereVerificationAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Dernière vérification de l'issue ; requise pour sortir de inconnu."
    )
