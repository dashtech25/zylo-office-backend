"""Table `alert_routes` : routage des signaux d'exploitation vers un propriétaire (BE-241).

Une ligne par signal. Le propriétaire et le runbook sont obligatoires en base ;
un propriétaire blanc reste possible en base et est refusé par le contrôle
`valider_route` (alertes_service), qui est la règle métier. La table ne porte
aucune colonne de tenant : c'est une configuration de plateforme (CA-4).
"""

import uuid

from sqlalchemy import CheckConstraint, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class AlertRoute(UUIDPrimaryKeyMixin, Base):
    """Route d'un signal d'exploitation : propriétaire, sévérité, runbook, escalade."""

    __tablename__ = "alert_routes"
    __table_args__ = (
        CheckConstraint("severity IN ('critical','high','medium','low')", name="ck_alert_routes_severity"),
        {"comment": "Routage des signaux d'exploitation vers le propriétaire, le runbook et l'escalade."},
    )

    # Identifiant stable du signal (ex. « sauvegarde.echec »).
    signal: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Équipe ou rôle nommé qui répond au signal.
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    # Ancre de docs/exploitation/alertes.md décrivant la première action.
    runbook: Mapped[str] = mapped_column(String(300), nullable=False)
    # Escalade si le signal n'est pas pris en charge ; texte libre, délai NON DÉFINI tant que QE-EXP-11 ouverte.
    escalation: Mapped[str | None] = mapped_column(Text, nullable=True)
