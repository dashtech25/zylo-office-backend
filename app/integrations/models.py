"""Modèle du registre des connecteurs (BE-160).

Table `connecteur` : un connecteur est une intégration externe déclarée par un tenant
(portée `tenant`) ou par la plateforme (portée `global`). Le registre ne stocke aucun
secret : la configuration est référencée par `versionConfiguration`, et sa validation
relève de BE-155. Les valeurs d'état sont les libellés de la définition ; leurs
transitions autorisées sont dans `app/integrations/registre.py`.

Écarts assumés avec la définition, tranchés sans attendre :
- la colonne de rattachement s'appelle `organizationId` (convention BE-007 retenue par
  BE-153), et non `tenantId` ; elle est nulle exactement pour la portée `global`
  (QE-PAR-19 : recommandation appliquée, portée explicite) ;
- les colonnes `createdAt` et `updatedAt` viennent de `TimestampMixin`.
"""

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

PORTEE_TENANT = "tenant"
PORTEE_GLOBAL = "global"


class Connecteur(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une intégration externe enregistrée, avec son état et sa version de configuration.

    - `portee` : `tenant` (rattaché à `organizationId`) ou `global` (sans organisation,
      géré par l'administration plateforme seule) ;
    - `etat` : `création`, `activé`, `suspendu` ou `révoqué` (CHECK en base) ;
    - `versionConfiguration` : version de configuration appliquée, incrémentée seulement
      par une reprise validée (`reprendre_configuration`).
    """

    __tablename__ = "connecteur"
    __table_args__ = (
        CheckConstraint(f"portee IN ('{PORTEE_TENANT}', '{PORTEE_GLOBAL}')", name="ck_connecteur_portee"),
        CheckConstraint(
            "etat IN ('création', 'activé', 'suspendu', 'révoqué')",
            name="ck_connecteur_etat",
        ),
        CheckConstraint(
            f"(portee = '{PORTEE_GLOBAL}' AND \"organizationId\" IS NULL) "
            f"OR (portee = '{PORTEE_TENANT}' AND \"organizationId\" IS NOT NULL)",
            name="ck_connecteur_portee_organisation",
        ),
        CheckConstraint("length(btrim(nom)) > 0", name="ck_connecteur_nom_non_vide"),
        CheckConstraint('"versionConfiguration" >= 1', name="ck_connecteur_version_positive"),
        Index("ix_connecteur_organizationId_etat", "organizationId", "etat"),
        {"comment": "Registre des connecteurs : portée, état et version de configuration (BE-160)."},
    )

    portee: Mapped[str] = mapped_column(String(16), nullable=False)
    organizationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    etat: Mapped[str] = mapped_column(String(16), nullable=False)
    versionConfiguration: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
