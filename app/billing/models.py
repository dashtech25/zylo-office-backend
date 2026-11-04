"""Modèles de facturation du socle : catalogue, versions de prix et abonnements.

Contrat (BE-023) :
- `Plan` : offre commerciale d'un module (code unique, prix de référence).
- `PlanVersion` : instantané de prix et d'entitlements, immuable une fois publié.
  Un abonnement reste rattaché à la version sous laquelle il a été souscrit.
- `Subscription` : abonnement d'une seule organisation (`organizationId` NOT NULL,
  refus à l'écriture sinon). Les montants sont en `amountMinor` (entier, unité
  mineure de la devise) ; `amountCents` n'existe plus que comme colonne legacy
  de `invoice`, recopiée par la migration c0b7d9a2e511.

Les lectures d'abonnement passent toujours par une organisation (voir
app/billing/service.py::current_subscription) : aucune requête globale.
"""
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class Plan(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Offre du catalogue pour un module. Le prix de référence sert de contrôle de cohérence à get_or_create_plan."""
    __tablename__ = "plan"
    __table_args__ = {"comment": "Offre commerciale pour un module donné (prix, période, fonctionnalités incluses)."}

    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    priceCents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XAF")
    periodDays: Mapped[int] = mapped_column(nullable=False, default=30)


class BillingPayer(Base):
    """Payeur d'un abonnement (BE-071) : la personne ou l'entité qui règle la facture.

    Le payeur est distinct du tenant bénéficiaire (`Subscription.beneficiaryTenantId`)
    et de l'administrateur (`Subscription.adminUserId`). Payer ne confère aucun droit
    d'accès : un paiement réussi n'alimente jamais `subscription_entitlement`.
    `payerKind` dit de quelle sorte d'entité il s'agit ; `accountRef` est la référence
    du compte côté facturation (la nature de cette référence reste à fixer, QE-FAC-22).
    """
    __tablename__ = "billing_payer"
    __table_args__ = {"comment": "Payeur d'un abonnement, distinct du tenant bénéficiaire et de l'administrateur (BE-071)."}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payerKind: Mapped[str] = mapped_column(String(30), nullable=False, comment="Sorte de payeur (organisation, personne).")
    accountRef: Mapped[str] = mapped_column(String(255), nullable=False, comment="Référence du compte payeur côté facturation.")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Abonnement d'une organisation à un plan. Démarre en `trial` ; `planVersionId` pointe la version souscrite (nullable pour les lignes antérieures à c0b7d9a2e511).

    BE-071 sépare trois rôles qui étaient confondus dans `organizationId` :
    - `payerId` : le payeur (`billing_payer`), nullable pour les lignes antérieures ;
    - `beneficiaryTenantId` : le tenant qui bénéficie de l'abonnement. Il reprend
      `organizationId` (recopié par la migration) ; c'est le périmètre de lecture
      et d'écriture (isolation tenant, CA-3 de BE-071) ;
    - `adminUserId` : l'utilisateur administrateur du tenant, seul habilité à changer
      l'administrateur (voir app/billing/payers.py::changer_administrateur).
    `organizationId` reste NOT NULL (contrat BE-023) : il n'est plus le seul propriétaire.
    """
    __tablename__ = "subscription"
    __table_args__ = {"comment": "Abonnement d'une organisation à un plan — statut trial/active/expired/cancelled."}

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    planId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan.id"), nullable=False, index=True)
    planVersionId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("planVersion.id"), nullable=True, index=True)
    payerId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_payer.id"), nullable=True, index=True, comment="Payeur de l'abonnement (BE-071).")
    beneficiaryTenantId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True, comment="Tenant bénéficiaire, périmètre d'accès (BE-071).")
    adminUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True, index=True, comment="Administrateur du tenant bénéficiaire (BE-071).")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="trial")
    # Trois axes indépendants (BE-079) : cycle de vie, finances, incident. Aucun ne dérive
    # des deux autres ; leurs valeurs et transitions sont dans app/billing/subscriptions/etats.py.
    lifecycleStatus: Mapped[str] = mapped_column(
        String(30), nullable=False, default="trialing", server_default="trialing",
        comment="Axe cycle de vie de l'abonnement (BE-079).",
    )
    financialStatus: Mapped[str] = mapped_column(
        String(30), nullable=False, default="none", server_default="none",
        comment="Axe financier de l'abonnement (BE-079).",
    )
    incidentStatus: Mapped[str] = mapped_column(
        String(30), nullable=False, default="none", server_default="none",
        comment="Axe incident de l'abonnement (BE-079).",
    )
    startDate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endDate: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    renewedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Verrou optimiste (BE-072) : incrémenté à chaque écriture versionnée, voir app/billing/idempotency.py.
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "invoice"
    __table_args__ = {"comment": "Facture émise pour un abonnement — le règlement réel (prestataire de paiement) n'est pas implémenté dans ce socle."}

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True
    )
    amountCents: Mapped[int] = mapped_column(Numeric(12, 0), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="XAF")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")  # pending | paid | failed
    issuedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paidAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    amountMinor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    idempotencyKey: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    # Verrou optimiste (BE-072), voir app/billing/idempotency.py.
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")


class IdempotencyRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registre d'idempotence des commandes mutantes (BE-072).

    Une ligne par (principal, route, clé). `scopeKey` porte cette portée ; une
    seconde demande de même portée est rejouée ou refusée selon `commandHash`.
    Voir app/billing/idempotency.py pour le contrat complet.
    """
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("scopeKey", name="uq_idempotency_record_scope"),
        {"comment": "Registre d'idempotence : portée principal + route + clé, empreinte de commande, résultat rejouable."},
    )

    scopeKey: Mapped[str] = mapped_column(Text, nullable=False)
    idempotencyKey: Mapped[str] = mapped_column(Text, nullable=False)
    commandHash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending | completed
    resultRef: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PlanVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Instantané immuable de prix et d'entitlements d'un plan (numéro `version` croissant par plan)."""
    __tablename__ = "planVersion"
    __table_args__ = (UniqueConstraint("planId", "version", name="uq_planVersion_plan_version"),)

    planId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan.id"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(nullable=False)
    amountMinor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    periodDays: Mapped[int] = mapped_column(nullable=False)
    entitlementCodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    effectiveAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Capability(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Registre de capacités rattaché au registre de modules (BE-021).

    Une capacité est la cible d'un entitlement (`subscription_entitlement.capaciteId`).
    `quotaUnit` porte l'unité dans laquelle `quotaLimite` est exprimé (QE-SOC-23) :
    l'entitlement ne la répète pas.
    """
    __tablename__ = "capability"
    __table_args__ = {"comment": "Registre des capacités d'un module, cible des entitlements d'abonnement."}

    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(150), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    quotaUnit: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="Unité du quota de la capacité.")


class SubscriptionEntitlement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Droit accordé par un abonnement ou une attribution (BE-024, absorbe BE-261).

    Table unique des entitlements (décision D3). Chaque ligne est une attribution :
    - `sourceAttribution` dit d'où vient le droit (`offre`, `achat_additionnel`,
      `essai`, `allocation_admin`, `usage_reel`) ;
    - `niveauApplication` dit à quel niveau il s'applique (`organisation` ou `utilisateur`) ;
    - `offreId` pointe la version de plan source (`planVersion`) quand le droit vient d'une offre ;
    - `capaciteId` pointe le registre de capacités ; `quotaLimite` est un entier strictement
      positif dont l'unité est portée par la capacité ;
    - `status` porte l'effet d'accès (`active`, `inactive`, `expired`, `blocked`) : il n'y a pas
      de colonne séparée. L'état calculé `expired` est dérivé de `endsAt` (voir
      app/billing/entitlements.py::calculer_entitlements).

    `organizationId` est nul uniquement pour une offre globale (`sourceAttribution` = `offre`).
    Une ligne sans organisation pour une autre source est refusée par la base.
    Le nom de table est en snake_case : décision du propriétaire pour BE-024.
    """
    __tablename__ = "subscription_entitlement"
    __table_args__ = (
        UniqueConstraint("subscriptionId", "entitlementCode", name="uq_subscription_entitlement_subscription_code"),
        # BE-045 : lecture des entitlements d'une organisation par module.
        Index("ix_subscription_entitlement_organizationId_moduleCode", "organizationId", "moduleCode"),
        CheckConstraint(
            "\"niveauApplication\" IN ('organisation', 'utilisateur')",
            name="ck_subscription_entitlement_niveau",
        ),
        CheckConstraint(
            "\"sourceAttribution\" IN ('offre', 'achat_additionnel', 'essai', 'allocation_admin', 'usage_reel')",
            name="ck_subscription_entitlement_source",
        ),
        CheckConstraint(
            "status IN ('active', 'inactive', 'expired', 'blocked')",
            name="ck_subscription_entitlement_status",
        ),
        CheckConstraint('"quotaLimite" IS NULL OR "quotaLimite" > 0', name="ck_subscription_entitlement_quota_positif"),
        CheckConstraint(
            "\"organizationId\" IS NOT NULL OR \"sourceAttribution\" = 'offre'",
            name="ck_subscription_entitlement_org_offre_globale",
        ),
        {"comment": "Entitlements d'abonnement : droits par capacité, source, niveau, quota et état d'accès."},
    )

    organizationId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True)
    subscriptionId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True)
    moduleCode: Mapped[str] = mapped_column(String(100), nullable=False)
    entitlementCode: Mapped[str] = mapped_column(String(150), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    startsAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    endsAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offreId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("planVersion.id"), nullable=True, index=True)
    capaciteId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("capability.id"), nullable=True, index=True)
    quotaLimite: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Pas de valeur par défaut (BE-045, CA-4) : le niveau et la source sont toujours explicites.
    niveauApplication: Mapped[str] = mapped_column(String(20), nullable=False)
    sourceAttribution: Mapped[str] = mapped_column(String(30), nullable=False)
    # Compteur de version de l'état (BE-045) : 1 à la création, incrémenté par les écritures d'état.
    stateVersion: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")


class EntitlementAllocation(UUIDPrimaryKeyMixin, Base):
    """Siège d'un entitlement attribué à un membre d'une organisation (BE-046).

    Une ligne = une attribution. La révocation ne supprime jamais la ligne : elle renseigne
    `revokedAt`, et le siège redevient disponible. Un couple (entitlement, utilisateur) n'a
    qu'une attribution active à la fois : l'index unique partiel ne porte que sur les lignes
    dont `revokedAt` est nul, ce qui permet une nouvelle attribution après révocation.

    `organizationId` est copié de `subscription_entitlement.organizationId` à l'écriture et
    jamais saisi par le client : le service (app/billing/allocations.py) le vérifie contre
    l'entitlement verrouillé. Les écritures passent par ce service, qui pose le verrou sur
    l'entitlement avant de compter les sièges.
    """

    __tablename__ = "entitlement_allocations"
    __table_args__ = (
        # Un seul siège actif par couple (entitlement, utilisateur) ; une révocation libère le couple.
        Index(
            "uq_entitlement_allocations_active",
            "entitlementId",
            "userId",
            unique=True,
            postgresql_where=text('"revokedAt" IS NULL'),
        ),
        {"comment": "Sièges d'entitlement attribués aux membres (BE-046). Révocation par revokedAt, sans suppression."},
    )

    entitlementId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_entitlement.id"), nullable=False, index=True
    )
    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    grantedBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    grantedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "paymentAttempt"
    __table_args__ = (
        UniqueConstraint("idempotencyKey", name="uq_paymentAttempt_idempotency"),
        UniqueConstraint("provider", "providerReference", name="uq_paymentAttempt_provider_reference"),
    )

    invoiceId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="test")
    idempotencyKey: Mapped[str] = mapped_column(String(120), nullable=False)
    providerReference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    amountMinor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    checkoutUrl: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    requestedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PaymentWebhookEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Table d'idempotence des évènements webhook de paiement (BE-029).

    Une ligne par (fournisseur, identifiant d'évènement). Le contenu n'est jamais stocké :
    seule son empreinte SHA-256 (`payloadDigest`) l'est. Traitée par app/billing/webhooks.py.
    """
    __tablename__ = "paymentWebhookEvent"
    __table_args__ = (UniqueConstraint("provider", "eventId", name="uq_paymentWebhookEvent_provider_event"),)

    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    eventId: Mapped[str] = mapped_column(String(160), nullable=False)
    eventType: Mapped[str] = mapped_column(String(100), nullable=False)
    payloadDigest: Mapped[str] = mapped_column(String(64), nullable=False)
    signatureVerified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requestId: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # `outcome` : received | recorded_unverified | applied | ignored | quarantined (BE-029).
    outcome: Mapped[str] = mapped_column(String(40), nullable=False, default="received")
    # Quarantaine (BE-029, CA-5) : renseignées seulement si un contenu contradictoire arrive
    # avec le même identifiant ; ce contenu n'est jamais appliqué.
    quarantinedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantineDigest: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PlanVersionSnapshot(Base):
    """Instantané figé d'une version d'offre, capturé au devis ou au contrat (BE-075).

    Chaque ligne fige `snapshotJson` au moment de la capture : une modification
    ultérieure du catalogue (nouvelle version, prix réécrit) ne la change pas.
    `planRef` est le code du plan, `planVersion` le numéro de version capturé,
    `sourceCatalogueRef` l'identifiant de la ligne `planVersion` d'origine.
    `organizationId` ancre l'instantané à un tenant : un snapshot n'est lu que
    depuis son organisation (CA-4 de BE-075). Cette colonne ne figure pas dans la
    liste de champs de la définition ; elle est ajoutée pour l'isolation tenant.
    Pas de mise à jour exposée : le module app/billing/catalog_snapshot.py n'écrit
    que la capture.
    """
    __tablename__ = "plan_version_snapshot"
    __table_args__ = {"comment": "Instantané immuable d'une version d'offre, capturé au devis ou au contrat (BE-075)."}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, comment="Tenant propriétaire de l'instantané (BE-075).")
    planRef: Mapped[str] = mapped_column(String(100), nullable=False, comment="Code du plan capturé.")
    planVersion: Mapped[int] = mapped_column(Integer, nullable=False, comment="Numéro de la version capturée.")
    capturedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sourceCatalogueRef: Mapped[str] = mapped_column(String(64), nullable=False, comment="Identifiant de la ligne planVersion source.")
    snapshotJson: Mapped[dict] = mapped_column(JSON, nullable=False, comment="Contenu figé de l'offre et de sa version.")


class ConsentRecord(Base):
    """Preuve d'un consentement versionné (BE-076), append-only.

    Une ligne est écrite à chaque consentement ou correction et n'est jamais modifiée :
    une migration pose un trigger PostgreSQL qui refuse UPDATE et DELETE (CA-2). Une
    correction est une nouvelle ligne dont `correctionOfId` pointe l'entrée d'origine.
    `consentTextVersion` identifie le texte accepté ; `scope` est le périmètre
    (payeur, tenant, beneficiaire). `accountId` référence le compte payeur `billing_payer`.
    """
    __tablename__ = "consent_record"
    __table_args__ = {"comment": "Consentement versionné d'une personne pour un compte payeur, append-only (BE-076)."}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    personId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True, comment="Personne qui consent.")
    accountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_payer.id"), nullable=False, index=True, comment="Compte payeur concerné.")
    consentTextVersion: Mapped[str] = mapped_column(String(64), nullable=False, comment="Identifiant de version du texte accepté.")
    scope: Mapped[str] = mapped_column(String(30), nullable=False, comment="Périmètre du consentement (payeur, tenant, beneficiaire).")
    recordedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="Heure d'enregistrement serveur.")
    correctionOfId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("consent_record.id"), nullable=True, index=True, comment="Entrée d'origine corrigée, nulle hors correction.")
