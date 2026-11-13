"""Registre des secrets de l'exploitation (BE-230).

Table `secret_registry` : une ligne par secret nommé de l'environnement. Elle décrit
le secret (propriétaire, portée, expiration, dernière rotation, consommateur,
caractère obligatoire) mais ne contient JAMAIS sa valeur. Les valeurs vivent dans
`app.core.secrets.SecretStore`, injectées depuis l'environnement.

Portée : l'environnement (pas la plateforme ni l'organisation) ; d'où la valeur
par défaut `environment`.
"""

import datetime as dt

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import UUIDPrimaryKeyMixin


class SecretRegistry(UUIDPrimaryKeyMixin, Base):
    """Métadonnées d'un secret. Aucune colonne ne porte une valeur de secret."""

    __tablename__ = "secret_registry"

    # Nom de la variable d'environnement (ex. JWT_SECRET) : identifiant unique du secret.
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    # Équipe ou rôle responsable de la rotation.
    owner: Mapped[str] = mapped_column(String(120), nullable=False)
    # Portée du secret. Seule valeur admise aujourd'hui : `environment`.
    scope: Mapped[str] = mapped_column(String(40), nullable=False, default="environment", server_default="environment")
    # Échéance. NULL : pas d'échéance connue (un secret obligatoire sans échéance reste admis).
    expiresAt: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Dernière rotation confirmée. NULL : jamais tourné depuis l'inventaire.
    lastRotatedAt: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Composant qui consomme le secret (ex. « authentification des sessions »).
    consumer: Mapped[str] = mapped_column(String(200), nullable=False)
    # Obligatoire : son absence ou son expiration fait échouer le démarrage hors développement.
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("true"))
