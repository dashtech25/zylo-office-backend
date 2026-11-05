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
from sqlalchemy.dialects.postgresql import JSONB, UUID
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
    # Résiliation (BE-090) : mode demandé et date d'effet. `cancelMode` est nul tant qu'aucune
    # résiliation n'a été demandée ; `cancelEffectiveAt` est alors la fin de période (`endDate`).
    cancelMode: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="Mode de résiliation : end_of_period ou immediate (BE-090).",
    )
    cancelEffectiveAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Date d'effet de la résiliation (BE-090).",
    )
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
    # BE-086 : cycle brouillon -> finalisée. Renseignés à la finalisation (app/billing/invoices.py),
    # NULL tant que la facture est un brouillon ou une facture émise avant BE-086.
    taxSnapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True, comment="Prix, devise et taxe figés à la finalisation (BE-078).")
    total: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="Total TTC en unités mineures, figé à la finalisation.")
    finalizedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Date de finalisation ; non NULL = facture append-only.")


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
    """Tentative de paiement (BE-028 pour une facture, BE-082 pour un checkout).

    Table unique `paymentAttempt` : une tentative porte soit une facture (`invoiceId`), soit un
    checkout (`checkoutId`), jamais les deux pour un même usage. Machine d'état BE-082 :
    `created -> submitted -> pending | requires_action | unknown | succeeded | failed | cancelled`.
    `unknown` signifie que l'issue fournisseur est inconnue (délai dépassé) : ce n'est jamais un
    échec. Aucune colonne ne porte de donnée de carte (CA-5 de BE-082).
    """

    __tablename__ = "paymentAttempt"
    __table_args__ = (
        UniqueConstraint("idempotencyKey", name="uq_paymentAttempt_idempotency"),
        UniqueConstraint("provider", "providerReference", name="uq_paymentAttempt_provider_reference"),
    )

    invoiceId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=True, index=True,
        comment="Facture payée (BE-028) ; NULL pour une tentative de checkout.",
    )
    checkoutId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("checkout.id"), nullable=True, index=True,
        comment="Checkout soumis (BE-082) ; NULL pour une tentative de facture.",
    )
    installmentRef: Mapped[str | None] = mapped_column(
        String(80), nullable=True, comment="Référence de l'échéance payée, si le paiement est fractionné (NON DÉFINI, QE-FAC-04).",
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1",
        comment="Verrou optimiste (BE-072), incrémenté à chaque transition.",
    )
    submittedAt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Instant de l'appel au fournisseur (état `submitted`).",
    )
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


class PriceRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Règle de prix, devise et taxe d'un objet tarifé pour un scénario et un tenant (BE-078).

    Une ligne par triplet (`organizationId`, `objectCode`, `scenario`). Les colonnes
    `amountMinor`, `currency` et `taxRateBps` sont NULLABLE : une règle partiellement
    saisie existe mais bloque la résolution, avec le code d'erreur de la colonne
    manquante (PRICE, CURRENCY ou TAX_NOT_CONFIGURED). Aucune valeur n'est insérée
    par défaut : le contenu vient de la finance (QE-FAC-06, QE-FAC-26).
    `objectCode` référence le code de l'offre (`plan.code`) ; `scenario` reste libre
    tant que la liste des scénarios n'est pas fixée (QE-FAC-10).
    """
    __tablename__ = "price_rule"
    __table_args__ = (
        UniqueConstraint("organizationId", "objectCode", "scenario", name="uq_price_rule_org_objet_scenario"),
        {"comment": "Règle de prix, devise et taxe par tenant, objet et scénario (BE-078). Valeurs non définies."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, comment="Tenant propriétaire de la règle.")
    objectCode: Mapped[str] = mapped_column(String(100), ForeignKey("plan.code"), nullable=False, comment="Code de l'offre tarifée.")
    scenario: Mapped[str] = mapped_column(String(50), nullable=False, comment="Scénario de tarification (valeurs NON DÉFINI, QE-FAC-10).")
    amountMinor: Mapped[int | None] = mapped_column(BigInteger, nullable=True, comment="Montant en unités mineures ; NULL = non configuré.")
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True, comment="Devise ISO ; NULL = non configurée.")
    taxRateBps: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="Taux de taxe en points de base ; NULL = non configuré.")


class PlanChange(UUIDPrimaryKeyMixin, Base):
    """Demande de changement de plan d'un abonnement (BE-088).

    Une ligne est écrite à la demande d'application d'un downgrade. Un downgrade reste
    `scheduled` jusqu'à `effectiveAt` (fin de période, `subscription.endDate`) : l'abonnement
    garde son plan tant que la demande n'est pas appliquée. Un upgrade n'est pas écrit
    (refusé en cours de période, QE-FAC-05). Au plus une ligne `scheduled` par abonnement,
    garantie par un index unique partiel (migration b088c0d1e2f3).

    `targetPlanVersionSnapshotId` pointe l'instantané figé de la version cible (BE-075) ;
    `previewJson` garde l'aperçu tel qu'il a été présenté au moment de la demande.
    Colonnes définies par BE-088 ; les noms suivent QE-FAC-04 (camelCase, FK explicites).
    """
    __tablename__ = "plan_change"
    __table_args__ = {"comment": "Demande de changement de plan d'un abonnement, appliquée à échéance (BE-088)."}

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True,
        comment="Abonnement concerné.",
    )
    targetPlanVersionSnapshotId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plan_version_snapshot.id"), nullable=False,
        comment="Instantané figé de la version d'offre cible (BE-075).",
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False, comment="upgrade ou downgrade (BE-088).")
    effectiveAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Date d'effet du changement (échéance pour un downgrade).",
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, comment="Statut de la demande : scheduled (BE-088).")
    previewJson: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Aperçu présenté au moment de la demande (BE-088).")

class EntitlementSync(UUIDPrimaryKeyMixin, Base):
    """Demande de synchronisation des droits d'un abonnement vers PH-09 (BE-085).

    PH-09 reste la seule autorité de droits : cette table ne porte que le suivi de la
    demande et de son issue. Cycle : `requested -> applied | failed | retry_pending`,
    `retry_pending -> applied | failed`. `applied` et `failed` sont terminaux : une
    synchronisation en échec ne repasse jamais à `applied`, une nouvelle demande crée une
    nouvelle ligne (BE-085, CA-1). `attempts` compte les issues enregistrées.
    """
    __tablename__ = "entitlement_sync"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'applied', 'failed', 'retry_pending')",
            name="ck_entitlement_sync_status",
        ),
        {"comment": "Suivi d'une demande de synchronisation des droits d'un abonnement (BE-085)."},
    )

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True,
        comment="Abonnement dont les droits doivent être synchronisés.",
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="Statut : requested, applied, failed ou retry_pending (BE-085).",
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="Nombre d'issues enregistrées (BE-085).",
    )
    lastErrorCode: Mapped[str | None] = mapped_column(
        String(60), nullable=True, comment="Dernier code d'erreur de synchronisation, nul si applied (BE-085).",
    )
    requestedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="Date de la demande de synchronisation (BE-085).",
    )


class Quote(Base):
    """Devis (Quote) d'un achat, du tenant bénéficiaire à un compte payeur (BE-077).

    Machine d'état : `created -> priced -> accepted | expired | revoked`. Un devis
    naît `created` ; il passe `priced` seulement quand la résolution de prix (BE-078)
    réussit, et capture alors `pricingSnapshotJson` (copie figée, jamais une
    référence vers la règle). `planVersionSnapshotId` pointe l'instantané de l'offre
    capturé au devis (BE-075) : une modification ultérieure du catalogue ne le change pas.

    `beneficiaryTenantId` est le tenant qui porte le devis ; toute lecture filtre
    dessus, un devis d'un autre tenant est donc traité comme inexistant (CA-4).
    `version` est le verrou optimiste (BE-072) incrémenté à chaque transition.
    `expiresAt` est NULLABLE : la durée de validité n'est pas définie (QE-FAC-21),
    un devis sans date n'expire pas tant que la décision n'est pas prise.
    """
    __tablename__ = "quote"
    __table_args__ = {"comment": "Devis d'achat, du tenant bénéficiaire à un payeur (BE-077). Valeurs de durée non définies (QE-FAC-21)."}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payerId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_payer.id"), nullable=False, comment="Compte payeur du devis.")
    beneficiaryTenantId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, comment="Tenant bénéficiaire, qui porte le devis (scope de lecture).")
    planVersionSnapshotId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("plan_version_snapshot.id"), nullable=False, comment="Instantané de l'offre capturé au devis (BE-075).")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created", comment="created, priced, accepted, expired ou revoked.")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="Verrou optimiste (BE-072), incrémenté à chaque transition.")
    expiresAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Fin de validité ; NULL tant que QE-FAC-21 n'est pas tranchée.")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    pricingSnapshotJson: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="Prix, devise et taxe figés à la résolution (BE-078) ; NULL avant `priced`.")


class DataExportRequest(Base):
    """Demande d'export des données de facturation d'un compte payeur (BE-098).

    Une ligne par demande. `scope` dit quel périmètre est exporté (`payeur`) et `accountId`
    désigne le compte payeur ; `organizationId` est le tenant bénéficiaire dans lequel la
    demande a été faite (isolation, CA-4). `requestedBy` est la personne qui a demandé.
    `fileRef` reste NULL tant qu'aucun stockage de fichier n'est branché (QE-FAC-25) : le
    contenu est renvoyé directement par la route. Le contenu n'est jamais stocké en base.
    """
    __tablename__ = "data_export_request"
    __table_args__ = {"comment": "Demande d'export des données de facturation d'un compte payeur (BE-098)."}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True, comment="Tenant bénéficiaire dans lequel la demande est faite.")
    accountId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("billing_payer.id"), nullable=False, index=True, comment="Compte payeur dont les données sont exportées.")
    scope: Mapped[str] = mapped_column(String(30), nullable=False, comment="Périmètre exporté (payeur).")
    requestedBy: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True, comment="Personne qui a demandé l'export.")
    status: Mapped[str] = mapped_column(String(30), nullable=False, comment="État de la demande (ready).")
    requestedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="Heure serveur de la demande.")
    fileRef: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Référence du fichier produit ; NULL tant qu'aucun stockage n'est branché (QE-FAC-25).")


class Checkout(Base):
    """Checkout d'achat ouvert depuis un devis `accepted` (BE-081).

    Machine d'état : `open -> pending -> completed | failed | cancelled | expired`. BE-081
    ne crée que l'état `open` ; `pending` vient de la soumission (BE-082) et `completed`
    de la confirmation du fournisseur (BE-083 / BE-084). Le retour de l'interface ne
    produit jamais `completed` (CA-2).

    Le tenant n'est pas porté par cette table : le périmètre de lecture passe par
    `quote.beneficiaryTenantId`. Les colonnes sont celles de la définition ; les
    colonnes exactes restent NON DÉFINIES (QE-FAC-04). `version` est le verrou optimiste
    (BE-072), initialisé à 1.
    """
    __tablename__ = "checkout"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open', 'pending', 'completed', 'failed', 'cancelled', 'expired')",
            name="ck_checkout_status",
        ),
        {"comment": "Checkout d'achat issu d'un devis accepté (BE-081). Colonnes exactes non définies (QE-FAC-04)."},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    quoteId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("quote.id"), nullable=False, index=True, comment="Devis accepté dont le checkout est issu.")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", comment="open, pending, completed, failed, cancelled ou expired.")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="Verrou optimiste (BE-072), incrémenté à chaque transition.")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class CreditNote(UUIDPrimaryKeyMixin, Base):
    """Avoir (BE-087) : correction d'une facture finalisée, sans toucher à la facture d'origine.

    Un avoir pointe toujours une facture (`invoiceId`, obligatoire). Le montant est en unités
    mineures, dans la devise de la facture (copiée à l'émission). Le motif est obligatoire et
    l'approbateur est enregistré dans l'entrée d'audit `billing.credit_note.issue`, pas sur cette
    ligne (colonnes exactes NON DÉFINI, QE-FAC-04). Pas d'`updatedAt` : un avoir est immuable.
    Voir app/billing/credit_notes/service.py pour les règles d'émission.
    """

    __tablename__ = "credit_note"
    __table_args__ = {"comment": "Avoir émis sur une facture finalisée (BE-087). Append-only ; la facture d'origine n'est pas modifiée."}

    invoiceId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=False, index=True)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Montant de l'avoir en unités mineures, strictement positif.")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, comment="Devise de la facture d'origine, copiée à l'émission.")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="Motif obligatoire (geste sensible, BE-073).")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="issued", comment="Statut de l'avoir ; `issued` à l'émission.")
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EntitlementSourceEvent(UUIDPrimaryKeyMixin, Base):
    """Journal d'idempotence des événements de liaison facturation vers entitlements (BE-058).

    Une ligne par `eventId` reçu sur la route de service. `outcome` décrit ce que l'événement
    a produit (`applied`, `reconciliation_required`, `organisation_inconnue`) ; un rejeu du même
    `eventId` ne crée jamais de seconde ligne. `organizationId` n'a pas de clé étrangère : une
    organisation inconnue doit pouvoir être journalisée (CA-5).
    """
    __tablename__ = "entitlement_source_events"
    __table_args__ = (
        UniqueConstraint("eventId", name="uq_entitlement_source_events_event_id"),
        CheckConstraint("\"eventType\" IN ('granted', 'ended')", name="ck_entitlement_source_events_type"),
        {"comment": "Journal d'idempotence des événements de liaison facturation vers entitlements (BE-058)."},
    )

    eventId: Mapped[str] = mapped_column(String(160), nullable=False)
    eventType: Mapped[str] = mapped_column(String(20), nullable=False)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    subscriptionId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    entitlementId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription_entitlement.id"), nullable=True,
    )
    outcome: Mapped[str] = mapped_column(String(40), nullable=False)
    createdAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Refund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Remboursement d'un paiement réussi (BE-093), avec approbation humaine obligatoire.

    Une ligne par demande. `request_id` porte la clé de requête (en-tête `Idempotency-Key`) : le
    couple (`paymentAttemptId`, `request_id`) est unique, donc une même demande rejouée ne crée
    jamais une seconde ligne. Statuts : `requested` (approbation enregistrée, envoi pas encore fait),
    `pending` (envoyé ou issue inconnue, à réconcilier BE-095), `succeeded`, `failed`.
    Les colonnes exactes sont NON DÉFINIES dans la définition (QE-FAC-04) : schéma retenu ici.
    L'approbateur est aussi tracé dans l'audit `billing.refund.approve`.
    """

    __tablename__ = "refund"
    __table_args__ = (
        UniqueConstraint("paymentAttemptId", "request_id", name="uq_refund_payment_request"),
        {"comment": "Remboursement d'un paiement réussi (BE-093) : approbation humaine avant tout envoi fournisseur."},
    )

    paymentAttemptId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paymentAttempt.id"), nullable=False, index=True,
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="Montant remboursé en unités mineures, strictement positif.")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, comment="Devise du paiement d'origine, copiée à la demande.")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested", comment="requested | pending | succeeded | failed.")
    approverId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True, comment="Approbateur humain distinct du demandeur (ACTF-08).")
    reason: Mapped[str] = mapped_column(Text, nullable=False, comment="Motif obligatoire (geste sensible, BE-073).")
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, comment="Clé de requête (Idempotency-Key) : avec paymentAttemptId, unique.")


class Dispute(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Litige (dispute) ouvert par le fournisseur sur un paiement (BE-094).

    Une ligne par litige fournisseur. Ouverture et clôture ne viennent que d'un évènement
    fournisseur (BE-083, traité par BE-029) : aucune route d'écriture publique. `providerRef`
    (identifiant du litige chez le fournisseur) est unique : un même litige reçu deux fois ne
    crée jamais une seconde ligne. Statuts : `opened`, `evidence_due`, `under_review` (ouverts),
    `won`, `lost`, `withdrawn` (clos). Les colonnes exactes sont NON DÉFINIES dans la définition
    (QE-FAC-04) : schéma retenu ici.
    """

    __tablename__ = "dispute"
    __table_args__ = (
        {"comment": "Litige fournisseur sur un paiement (BE-094) : ouverture et clôture par évènement fournisseur."},
    )

    paymentAttemptId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paymentAttempt.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="opened | evidence_due | under_review | won | lost | withdrawn.")
    providerRef: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, comment="Identifiant du litige chez le fournisseur.")
    openedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Date de réception de l'ouverture.")
    resolvedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, comment="Date de clôture (won, lost, withdrawn).")


class ReconciliationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une exécution de réconciliation des paiements (BE-095), bornée à un tenant.

    Une ligne par lancement. `scope` vaut `tenant` (seul périmètre livré) ; `organizationId` borne
    la sélection des tentatives : une réconciliation ne lit jamais un autre tenant (CA-4).
    `differenceCount` compte les écarts créés par ce lancement. Le statut reste `completed` :
    un fournisseur injoignable ne fait pas échouer le run, il laisse simplement les tentatives
    `unknown` sans constat (aucune correction, aucune capture).
    """

    __tablename__ = "reconciliation_run"
    __table_args__ = ({"comment": "Exécution de réconciliation des paiements et résultats incertains (BE-095)."},)

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True,
        comment="Tenant dont les tentatives ont été réconciliées (CA-4).",
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="tenant", comment="Périmètre demandé : tenant.")
    periodKey: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="Période indicative fournie par l'appelant (non filtrante, écart documenté).")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed", comment="completed.")
    differenceCount: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0", comment="Nombre d'écarts créés par ce run.")
    startedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Instant de lancement du run.")


class ReconciliationDifference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Écart détecté par une réconciliation (BE-095, CA-2).

    Un écart signifie : le fournisseur confirme un débit sous la référence d'une tentative que Zylo
    tient `unknown`. Il est seulement constaté (`status` = `detected`) : aucune correction de la
    tentative n'est faite automatiquement. L'évènement `ReconciliationDifferenceDetected` est écrit
    dans l'outbox avec la même transaction.
    """

    __tablename__ = "reconciliation_difference"
    __table_args__ = (
        UniqueConstraint("runId", "paymentAttemptId", name="uq_reconciliation_difference_run_attempt"),
        {"comment": "Écart constaté par une réconciliation des paiements (BE-095), sans correction automatique."},
    )

    runId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("reconciliation_run.id"), nullable=False, index=True)
    paymentAttemptId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("paymentAttempt.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="detected", comment="detected (aucune correction automatique).")


class RenewalRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Passage du job de renouvellement (BE-089) pour un abonnement et une période.

    Clé de déduplication : (subscriptionId, periodKey, type). `type` est une colonne ajoutée
    à la liste de la fiche : celle-ci demande la clé sans la nommer (QE-FAC-04 non tranché) ;
    recommandation appliquée, une colonne texte, valeur `renewal` pour ce job.
    `status` : `completed` (facture émise) ou `refused` (abonnement terminé, journalisé).
    """

    __tablename__ = "renewal_run"
    __table_args__ = (
        UniqueConstraint("subscriptionId", "periodKey", "type", name="uq_renewal_run_key"),
        {"comment": "Passage du job de renouvellement d'abonnement (BE-089), une ligne par abonnement, période et type."},
    )

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True,
    )
    periodKey: Mapped[str] = mapped_column(String(20), nullable=False, comment="Clé de période de facturation, opaque pour le job.")
    type: Mapped[str] = mapped_column(String(40), nullable=False, default="renewal", comment="Type de passage ; `renewal` pour BE-089.")
    status: Mapped[str] = mapped_column(String(20), nullable=False, comment="completed | refused.")
    attemptedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, comment="Instant du premier passage pour cette clé.")
    invoiceId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoice.id"), nullable=True, comment="Facture émise par ce passage ; NULL si refusé.",
    )


class CloseOperation(UUIDPrimaryKeyMixin, Base):
    """Clôture d'un abonnement (BE-097) : orchestration des prérequis avant `subscription_closed`.

    Cycle : `requested -> close_pending_finance | close_pending_entitlement | close_pending_data
    -> completed`. Une clôture bloquée reste ouverte et peut être reprise (même ligne) ; `completed`
    est terminal et un rejeu renvoie la ligne existante. `prerequisitesJson` garde le résultat
    vérifié de chaque prérequis (finance, droits, données) à la dernière évaluation.
    """

    __tablename__ = "close_operation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'close_pending_finance', 'close_pending_entitlement', "
            "'close_pending_data', 'completed', 'blocked', 'escalated')",
            name="ck_close_operation_status",
        ),
        {"comment": "Clôture d'un abonnement, prérequis vérifiés un à un (BE-097)."},
    )

    subscriptionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("subscription.id"), nullable=False, index=True,
        comment="Abonnement clôturé.",
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, comment="Statut de la clôture (BE-097).")
    prerequisitesJson: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, comment="Résultat vérifié de chaque prérequis (BE-097).")
    requestedAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), comment="Heure de la demande de clôture.")
