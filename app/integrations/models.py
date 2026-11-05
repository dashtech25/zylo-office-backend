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

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
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


class SecretIntegration(UUIDPrimaryKeyMixin, Base):
    """Référence d'un secret d'intégration, sans la valeur (BE-161).

    Table `secret_integration` : chaque ligne désigne, par `referenceSecret`, une entrée du
    coffre (`app.core.secrets.SecretStore` pour l'instant). La valeur n'est JAMAIS une
    colonne de cette table ni d'une autre table : seule la référence est persistée.

    - `version` : numéro de version par connecteur, à partir de 1 ; la version la plus
      haute est la valeur courante ;
    - `expireAt` : échéance, nullable (QE-PAR-09, recommandation appliquée : un secret sans
      échéance connue reste admis, un secret expiré est refusé à l'envoi) ;
    - unicité de `(connecteurId, version)`.
    """

    __tablename__ = "secret_integration"
    __table_args__ = (
        CheckConstraint('"version" >= 1', name="ck_secret_integration_version_positive"),
        CheckConstraint("length(btrim(\"referenceSecret\")) > 0", name="ck_secret_integration_reference_non_vide"),
        UniqueConstraint("connecteurId", "version", name="uq_secret_integration_connecteur_version"),
        {"comment": "Références des secrets d'intégration, jamais de valeur (BE-161)."},
    )

    connecteurId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connecteur.id"), nullable=False, index=True
    )
    referenceSecret: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    expireAt: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    createdAt: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


ISSUE_SUCCES = "succes"
ISSUE_ECHEC = "echec"


class TentativeIntegration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une tentative d'effet d'intégration sur un connecteur, sans contenu (BE-164).

    - `connecteurId` et `eventId` forment la clé d'effet : une seule ligne `succes` par
      couple (CA-3, garanti par l'index unique partiel) ;
    - `correlationId` relie la tentative à la chaîne de traitement de l'événement ;
    - `dureeMs` est la durée mesurée de l'appel, `tentativeNo` son rang (à partir de 1) ;
    - `prochaineTentativeAt` est renseigné seulement pour un échec transitoire ;
    - aucune colonne de contenu (payload, corps de réponse) : le journal ne garde que des
      métadonnées (CA-1).

    Écart assumé avec la définition : le rattachement au tenant s'appelle `organizationId`
    (convention retenue par BE-160), et le nom de table est `tentativeIntegration`
    (CLAUDE.md : tables en camelCase).
    """

    __tablename__ = "tentativeIntegration"
    __table_args__ = (
        CheckConstraint(f"issue IN ('{ISSUE_SUCCES}', '{ISSUE_ECHEC}')", name="ck_tentativeIntegration_issue"),
        CheckConstraint('"dureeMs" >= 0', name="ck_tentativeIntegration_duree_positive"),
        CheckConstraint('"tentativeNo" >= 1', name="ck_tentativeIntegration_tentative_positive"),
        Index(
            "uq_tentativeIntegration_effet_succes",
            "connecteurId",
            "eventId",
            unique=True,
            postgresql_where=text(f"issue = '{ISSUE_SUCCES}'"),
        ),
        Index("ix_tentativeIntegration_organizationId_createdAt", "organizationId", "createdAt"),
        {"comment": "Journal des tentatives d'intégration : métadonnées sans payload (BE-164)."},
    )

    connecteurId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("connecteur.id"), nullable=False)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False)
    correlationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    eventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    issue: Mapped[str] = mapped_column(String(16), nullable=False)
    codeErreur: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dureeMs: Mapped[int] = mapped_column(Integer, nullable=False)
    tentativeNo: Mapped[int] = mapped_column(Integer, nullable=False)
    prochaineTentativeAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
