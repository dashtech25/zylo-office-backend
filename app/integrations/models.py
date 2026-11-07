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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class IntegrationLink(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Lien d'un tenant vers un compte d'un fournisseur externe (BE-239).

    Table `integration_links`. Une ligne par connexion : elle porte la référence composée
    `remoteKey` (`fournisseur/compte/ressource`, CA-1), l'état `statut` (`connectée` ou
    `déconnectée`), le curseur de synchronisation `curseurSync` et le résultat de la dernière
    réconciliation (`derniereReconciliation`, `statutReconciliation`).

    - `connecteurId` : connecteur du registre (BE-160) qui porte le secret ; unique, car un
      connecteur ne sert qu'à un lien ;
    - aucun secret ici : la valeur reste dans le coffre, seule la référence est en base (BE-161) ;
    - unicité de `(organizationId, provider, externalAccount)` tant que le lien existe : deux
      connexions actives au même compte d'un même tenant sont impossibles.
    """

    __tablename__ = "integration_links"
    __table_args__ = (
        CheckConstraint("statut IN ('connectée', 'déconnectée')", name="ck_integration_links_statut"),
        CheckConstraint(
            "\"statutReconciliation\" IS NULL OR \"statutReconciliation\" IN ('succes', 'echec')",
            name="ck_integration_links_statut_reconciliation",
        ),
        CheckConstraint("length(btrim(\"remoteKey\")) > 0", name="ck_integration_links_remote_key_non_vide"),
        UniqueConstraint(
            "organizationId", "provider", "externalAccount", name="uq_integration_links_tenant_compte"
        ),
        {"comment": "Liens tenant vers des comptes de fournisseurs externes, sans secret (BE-239)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    connecteurId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connecteur.id"), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    externalAccount: Mapped[str] = mapped_column(String(128), nullable=False)
    remoteKey: Mapped[str] = mapped_column(String(512), nullable=False)
    statut: Mapped[str] = mapped_column(String(16), nullable=False, server_default="connectée")
    curseurSync: Mapped[str | None] = mapped_column(String(255), nullable=True)
    derniereReconciliation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    statutReconciliation: Mapped[str | None] = mapped_column(String(16), nullable=True)


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


class LettreMorte(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une tentative d'intégration définitivement échouée, en attente de reprise (BE-165).

    - `tentativeId` : la tentative `echec` d'où provient la lettre ; une seule lettre par
      tentative (unicité), donc un échec ne peut pas être déplacé deux fois ;
    - `originalId` : identifiant de l'événement d'origine (`eventId` de la tentative), celui
      que la reprise rejoue ;
    - `motif`, `operateur`, `reprisAt` : renseignés seulement par la reprise manuelle.
      Tant que `reprisAt` est nul, la lettre peut être reprise ; une fois posé, la reprise
      est définitivement close (CA-4).

    Écarts assumés avec la définition, tranchés sans attendre : le rattachement au tenant
    s'appelle `organizationId` (convention BE-160/BE-164), la table `lettreMorte` suit le
    camelCase. La durée de rétention est NON DÉFINIE (QE-PAR-17) : aucune purge n'existe.
    """

    __tablename__ = "lettreMorte"
    __table_args__ = (
        UniqueConstraint("tentativeId", name="uq_lettreMorte_tentativeId"),
        CheckConstraint("motif IS NULL OR length(btrim(motif)) > 0", name="ck_lettreMorte_motif_non_vide"),
        Index("ix_lettreMorte_organizationId_createdAt", "organizationId", "createdAt"),
        {"comment": "Lettres mortes d'intégration et reprises manuelles tracées (BE-165)."},
    )

    tentativeId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tentativeIntegration.id"), nullable=False
    )
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False)
    originalId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    motif: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operateur: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    reprisAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


STATUT_WEBHOOK_RECU = "recu"


class WebhookRecu(UUIDPrimaryKeyMixin, Base):
    """Un événement externe reçu par un webhook entrant, sans sa charge utile complète (BE-163).

    - `connecteurId` et `idExterne` forment la clé d'idempotence : une seule ligne par couple
      (CA-2), garantie par la contrainte d'unicité `uq_webhook_recu_connecteur_id_externe` ;
    - `organizationId` reprend l'organisation du connecteur (jamais celle de l'en-tête de
      requête) ; nul pour un connecteur de portée `global` ;
    - `payloadMinimal` ne garde que les champs de routage du schéma, pas le corps reçu.
    """

    __tablename__ = "webhook_recu"
    __table_args__ = (
        UniqueConstraint("connecteurId", "idExterne", name="uq_webhook_recu_connecteur_id_externe"),
        CheckConstraint(f"statut IN ('{STATUT_WEBHOOK_RECU}')", name="ck_webhook_recu_statut"),
        CheckConstraint("length(btrim(\"idExterne\")) > 0", name="ck_webhook_recu_id_externe_non_vide"),
        {"comment": "Événements externes reçus par webhook entrant, sans charge utile complète (BE-163)."},
    )

    connecteurId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connecteur.id"), nullable=False, index=True
    )
    idExterne: Mapped[str] = mapped_column(String(255), nullable=False)
    organizationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    payloadMinimal: Mapped[dict] = mapped_column(JSONB, nullable=False)
    recuAt: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    statut: Mapped[str] = mapped_column(String(16), nullable=False, server_default=STATUT_WEBHOOK_RECU)


ETAT_INTEGRATION_CONFIGUREE = "configured"
ETAT_INTEGRATION_ACTIVE = "active"
ETAT_INTEGRATION_DEGRADEE = "degraded"
ETAT_INTEGRATION_REVOQUEE = "revoked"


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Configuration d'une intégration externe d'un tenant, sans valeur de secret (BE-210).

    Table `integration`. Une ligne par couple (`provider`, `purpose`) et par organisation
    (unicité `uq_integration_organisation_fournisseur_usage`).

    - `state` : `configured`, `active`, `degraded` ou `revoked` (CHECK en base) ; une
      intégration révoquée ne résout plus aucune référence ;
    - `credentialRef` : référence de la version courante du secret, dans le coffre ; la
      valeur n'est jamais une colonne de cette table ;
    - `scopes` : liste JSON des portées demandées, sans secret.

    Écart assumé avec la définition, tranché sans attendre : le rattachement au tenant
    s'appelle `organizationId` (convention BE-007 / BE-160), et la clé primaire est `id`.
    """

    __tablename__ = "integration"
    __table_args__ = (
        CheckConstraint(
            f"state IN ('{ETAT_INTEGRATION_CONFIGUREE}', '{ETAT_INTEGRATION_ACTIVE}', "
            f"'{ETAT_INTEGRATION_DEGRADEE}', '{ETAT_INTEGRATION_REVOQUEE}')",
            name="ck_integration_state",
        ),
        CheckConstraint("configSchemaVersion >= 1", name="ck_integration_config_schema_version_positive"),
        CheckConstraint("length(btrim(provider)) > 0", name="ck_integration_provider_non_vide"),
        CheckConstraint("length(btrim(purpose)) > 0", name="ck_integration_purpose_non_vide"),
        UniqueConstraint(
            "organizationId", "provider", "purpose", name="uq_integration_organisation_fournisseur_usage"
        ),
        {"comment": "Configuration d'intégration par tenant, référence de credential sans valeur (BE-210)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    purpose: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    configSchemaVersion: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, server_default=ETAT_INTEGRATION_CONFIGUREE)
    credentialRef: Mapped[str] = mapped_column(String(255), nullable=False)


class IntegrationCredential(UUIDPrimaryKeyMixin, Base):
    """Une version du secret d'une intégration, par sa seule référence (BE-210).

    Table `integration_credential`. Chaque rotation ajoute une version ; toutes restent
    résolubles jusqu'à la révocation de l'intégration (CA-4). `referenceSecret` désigne
    l'entrée du coffre, sans la valeur.
    """

    __tablename__ = "integration_credential"
    __table_args__ = (
        CheckConstraint('"version" >= 1', name="ck_integration_credential_version_positive"),
        CheckConstraint("length(btrim(\"referenceSecret\")) > 0", name="ck_integration_credential_reference_non_vide"),
        UniqueConstraint("integrationId", "version", name="uq_integration_credential_version"),
        {"comment": "Versions de credential d'intégration : références au coffre, jamais de valeur (BE-210)."},
    )

    integrationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("integration.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    referenceSecret: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    createdAt: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
