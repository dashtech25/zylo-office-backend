import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, synonym

from app.core.database import Base
from app.shared.models import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Organisation cliente : tenant racine (BE-002).

    Colonnes clés : `name` (nom affiché), `slug` (identifiant stable, unique en
    base : un second enregistrement au même slug est refusé par la contrainte
    d'unicité), `status` (défaut `active`). La suppression est logique
    (`deletedAt`, SoftDeleteMixin). Le schéma vient de la migration
    `4b1cccdb5fd5` ; aucune migration supplémentaire n'est requise par BE-002.
    Aucune lecture publique ne renvoie plusieurs organisations sans paramètre de
    portée (voir app/identity/service.py::list_user_organizations).
    """

    __tablename__ = "organization"
    __table_args__ = (
        # BE-186 CA-1 : un tenant ne porte qu'une organisation en v1 (NULL reste permis
        # pour les organisations créées avant la migration, sans tenant rattaché).
        UniqueConstraint("tenantId", name="uq_organization_tenantId"),
        {"comment": "Organisation cliente de Zylo Office — tenant racine du système multi-organisation."},
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    # Verrou de version (BE-233, app/core/versioning.py) : +1 à chaque mutation.
    version: Mapped[int] = mapped_column(
        nullable=False, server_default="1", comment="Version de l'agrégat (BE-233) ; incrémentée à chaque mutation, verrou de conflit."
    )
    # BE-186 : tenant racine de l'organisation (FK vers `tenant`, unique). Renseigné à la création.
    tenantId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("tenant.id"), nullable=True)
    # BE-102 : créateur de l'organisation (FK vers `user`), sert à la déduplication par créateur.
    # Nul pour les organisations créées avant BE-102.
    createdByUserId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=True)
    # BE-186 : identifiants légaux confidentiels, stockés chiffrés (app.core.field_crypto) ;
    # visibles seulement avec `organization.legal.read`. Jamais en clair au repos.
    legalRegistrationNumberChiffre: Mapped[str | None] = mapped_column(Text, nullable=True)
    legalTaxNumberChiffre: Mapped[str | None] = mapped_column(Text, nullable=True)


class User(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Utilisateur global (BE-003) : une seule ligne par personne, quel que soit
    le nombre d'organisations auxquelles elle appartient (rattachement dans
    `organization_user`, BE-004).

    `email` est unique, et un index unique sur `lower(email)` (uq_user_email_lower)
    refuse deux comptes qui ne diffèrent que par la casse. `hashedPassword` ne
    contient jamais de mot de passe en clair : seul le condensat bcrypt produit
    par app/core/security.py::hash_password y est stocké. `status` vaut `active`,
    `suspended` ou `pending`. Un utilisateur inexistant n'obtient aucune session.
    """

    __tablename__ = "user"
    # Intention (T-013) : unicité de l'e-mail sans tenir compte de la casse.
    # L'e-mail est normalisé en minuscules à l'écriture ; cet index bloque aussi
    # les comptes anciens qui ne différeraient que par la casse.
    __table_args__ = (
        Index("uq_user_email_lower", text("lower(email)"), unique=True),
        {"comment": "Utilisateur du système — identité unique, valable pour toutes les organisations et tous les modules."},
    )

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashedPassword: Mapped[str] = mapped_column(String(255), nullable=False)
    fullName: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")  # active | suspended | pending

    # Module Personnel (Centre administratif de la station) — colonnes
    # additives, toutes nullable : les comptes déjà auto-inscrits via
    # `POST /auth/register` n'ont que `fullName`, jamais rétro-déduites.
    firstName: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lastName: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Référence opaque vers le service de stockage générique
    # (app/shared/storage.py) — jamais un fichier stocké par ce module.
    photoStorageReference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Vrai après une création de compte par un tiers (mot de passe temporaire
    # généré côté serveur, jamais choisi par la personne) — force un
    # changement via POST /auth/change-password avant utilisation normale.
    mustChangePassword: Mapped[bool] = mapped_column(nullable=False, server_default="false")
    # Verrou de version (BE-187) : +1 à chaque transition de statut réussie
    # (app/identity/cycle_de_vie_utilisateur.py), comme organization.version (BE-233).
    version: Mapped[int] = mapped_column(
        nullable=False, server_default="1", comment="Version de l'utilisateur (BE-187) ; incrémentée à chaque transition de statut."
    )


class OrganizationUser(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Appartenance d'un utilisateur global à une organisation (BE-004).

    Association plusieurs-à-plusieurs : un utilisateur peut appartenir à
    plusieurs organisations, et chaque ligne désigne un couple
    (`organizationId`, `userId`). La contrainte `uq_organizationUser_org_user`
    refuse un second rattachement identique, ce qui garantit un seul contexte
    par couple. Le schéma vient de la migration `4b1cccdb5fd5`.

    Cette table est la seule preuve d'appartenance : `assert_active_membership`
    (app/rbac/service.py) la consulte à chaque requête, donc supprimer la ligne
    retire l'accès à la requête suivante. Table renommée `organization_user`
    par BE-100 (décision QE-POR-30, snake_case pour les tables).

    `status` (BE-100) porte le statut d'appartenance, `active` par défaut. Il
    n'est pas encore lu par `assert_active_membership` : la présence de la ligne
    reste la seule preuve d'accès, comme avant (QE-SOC-04).
    """

    __tablename__ = "organization_user"
    __table_args__ = (
        UniqueConstraint("organizationId", "userId", name="uq_organizationUser_org_user"),
        {"comment": "Association utilisateur <-> organisation (appartenance, many-to-many)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", server_default="active")
    # BE-189 : verrou de version du membership, +1 à chaque changement d'état (app/identity/membership.py).
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="Version du membership (BE-189) ; incrémentée à chaque changement d'état."
    )


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Tenant de la plateforme : unique définition de la table `tenant` (BE-100, cycle de vie BE-185).

    Une seule classe porte la table : BE-100 (organisation, invitation) et BE-185
    (cycle de vie, `app/tenants/`) la réutilisent. Colonnes BE-100 : `organizationId`
    (unique, un seul tenant par organisation) et `status` (défaut `active`). Colonnes
    ajoutées par BE-185 : `slug` (identifiant lisible, unique), `version` (verrou de
    version, +1 à chaque transition) et `closedAt` (renseigné à la fermeture).

    `tenantId` et `state` sont des synonymes de `id` et `status` : le vocabulaire de
    l'API BE-185 reste celui de la définition, sans seconde colonne. `organizationId`
    est facultatif, car un tenant précède son organisation racine (QE-API-05). La
    contrainte `ck_tenant_state` borne `status` aux six états du cycle de vie.
    Aucune colonne parente : le modèle est plat (QE-POR-05).
    """

    __tablename__ = "tenant"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenant_slug"),
        CheckConstraint(
            "status IN ('requested', 'provisioning', 'active', 'suspended', 'closing', 'closed')",
            name="ck_tenant_state",
        ),
        {"comment": "Tenant de la plateforme : organisation (BE-100), cycle de vie (BE-185), état et verrou de version."},
    )

    organizationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", server_default="active")
    slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    closedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenantId = synonym("id")
    state = synonym("status")


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Invitation du portail d'organisation (BE-100) : destinataire, rôle, statut.

    Le destinataire est l'identité invitée (`recipientUserId`, QE-POR-24) ; seule
    cette identité peut accepter. `roleId` est le rôle proposé, facultatif.
    `status` ne prend que `pending`, `accepted`, `expired` ou `revoked` : la
    contrainte de table refuse toute autre valeur. Le créateur est
    `createdByUserId`. Cette table est distincte de `organizationInvitation`
    (BE-012, adresse e-mail sans compte) : voir la doc du module portail.
    """

    __tablename__ = "invitation"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'expired', 'revoked')",
            name="ck_invitation_status",
        ),
        {"comment": "Invitation du portail d'organisation : destinataire identifié, rôle proposé, statut borné."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    recipientUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    roleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    createdByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)


class UserInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jeton d'activation d'un compte créé par une organisation (T-021, T-049).

    Intention : seule l'empreinte SHA-256 du jeton est stockée (le jeton n'existe
    qu'en clair dans le message envoyé au titulaire). Usage unique (`usedAt`),
    durée limitée (`expiresAt`), révocable (`revokedAt`, réémission). Un seul
    jeton ouvert par compte : garanti par l'index partiel ci-dessous.
    """

    __tablename__ = "userInvitation"
    __table_args__ = (
        Index(
            "uq_userInvitation_open_per_user",
            "userId",
            unique=True,
            postgresql_where="\"usedAt\" IS NULL AND \"revokedAt\" IS NULL",
        ),
        {"comment": "Jeton d'activation à usage unique d'un compte créé par une organisation (haché, à durée limitée)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False, index=True)
    createdByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
    tokenHash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    usedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revokedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationInvitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Invitation d'une personne à rejoindre une organisation (BE-012).

    Contrairement à `userInvitation` (activation d'un compte déjà créé, T-021),
    le destinataire n'a pas forcément de compte : la table porte donc son
    adresse (`email`, normalisée en minuscules) et non un `userId`.

    Colonnes : `roleId` est le rôle proposé (nullable, doit appartenir à
    l'organisation) ; `status` vaut `pending` à la création, `revoked` ou
    `accepted` plus tard (acceptation hors périmètre de BE-012). Seule
    l'empreinte SHA-256 du jeton est stockée (`tokenHash`) ; le jeton n'existe
    en clair que dans le message envoyé au destinataire.

    Invariant : une seule invitation `pending` par couple (organisation,
    adresse), garanti par l'index partiel ci-dessous, pour qu'une course entre
    deux créations ne produise pas deux invitations ouvertes.
    """

    __tablename__ = "organizationInvitation"
    __table_args__ = (
        Index(
            "uq_organizationInvitation_pending_per_email",
            "organizationId",
            "email",
            unique=True,
            postgresql_where=text("\"status\" = 'pending'"),
        ),
        {"comment": "Invitation à rejoindre une organisation : destinataire, rôle proposé, état, expiration (jeton haché)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    roleId: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("role.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending", server_default="pending")
    tokenHash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expiresAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    createdByUserId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id"), nullable=False)
