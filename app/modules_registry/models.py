import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin

# Valeurs des enums du catalogue (BE-040, matrice-etats-modules-et-droits.md section 1).
# Publication et visibilité sont des axes orthogonaux : aucun des deux n'ouvre l'accès à lui seul.
# L'accès reste décidé par `etats.py` (registre) et par l'activation de l'organisation.
ETATS_PUBLICATION_MODULE: tuple[str, ...] = (
    "draft",
    "review",
    "published",
    "deprecated",
    "withdrawn",
    "quarantined",
)
VISIBILITES_MODULE: tuple[str, ...] = ("hidden", "visible", "restricted")
# États d'une version (BE-042) : draft -> review -> published ; review -> draft (rejet).
ETATS_PUBLICATION_VERSION: tuple[str, ...] = ("draft", "review", "published")


class Module(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Module du catalogue Zylo Office (table `module`, réutilisée par BE-040).

    La table existait depuis BE-021 comme registre statique. BE-040 y ajoute le cycle de
    publication (`publicationState`) et la visibilité (`visibility`). `code` joue le rôle de
    `slug` du catalogue : unique, il sert de clé stable. `version` est l'ancien champ texte de
    BE-021, conservé ; la liste des versions est dans `module_version`.
    """

    __tablename__ = "module"
    __table_args__ = {"comment": "Catalogue des modules (registre, cycle de publication, visibilité)."}

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, default="0.1.0")
    # Version du contrat de manifeste (format non défini, QE-SOC-19). Hors de
    # VERSIONS_MANIFESTE_SUPPORTEES, le module passe à l'état `incompatible` (etats.py).
    manifestVersion: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1", comment="Version du contrat de manifeste du module."
    )
    publicationState: Mapped[str] = mapped_column(
        Enum(*ETATS_PUBLICATION_MODULE, name="module_publication_state", native_enum=True),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="Cycle de publication du module au catalogue (draft, review, published, ...).",
    )
    visibility: Mapped[str] = mapped_column(
        Enum(*VISIBILITES_MODULE, name="module_visibility", native_enum=True),
        nullable=False,
        default="hidden",
        server_default="hidden",
        comment="Visibilité du module dans le catalogue (hidden, visible, restricted).",
    )


class ModuleVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Une version d'un module du catalogue (table `module_version`, BE-040).

    Une version est immuable dès qu'elle est publiée (`publishedAt` renseigné) : son contenu
    (`digest`, `provenance`, `licence`, `compatibility`, `prerequisites`) ne se modifie plus.
    La règle est appliquée par `catalogue.modifier_version`. Une version sans `digest` ni
    `provenance` ne peut pas être publiée (`catalogue.verifier_publiable`).
    `stateVersion` est le compteur de révision : il avance à chaque transition de `publicationState`
    (BE-042), et la commande de publication doit le reprendre (contrôle de concurrence).
    """

    __tablename__ = "module_version"
    __table_args__ = (
        UniqueConstraint("moduleId", "version", name="uq_module_version_module_version"),
        {"comment": "Versions d'un module du catalogue ; une version publiée est immuable."},
    )

    moduleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("module.id"), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False, comment="Version semver (ex. 1.2.0).")
    digest: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="Empreinte du paquet.")
    provenance: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="Origine du paquet.")
    licence: Mapped[str | None] = mapped_column(String(100), nullable=True)
    compatibility: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prerequisites: Mapped[list | None] = mapped_column(JSON, nullable=True)
    stateVersion: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    publicationState: Mapped[str] = mapped_column(
        Enum(*ETATS_PUBLICATION_VERSION, name="module_version_publication_state", native_enum=True),
        nullable=False,
        default="draft",
        server_default="draft",
        comment="État de publication de la version (draft, review, published).",
    )
    publishedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationModule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizationModule"
    __table_args__ = (
        UniqueConstraint("organizationId", "moduleCode", name="uq_organizationModule_org_module"),
        {"comment": "État d'activation d'un module pour une organisation donnée (active/inactive/trial)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True
    )
    moduleCode: Mapped[str] = mapped_column(String(100), ForeignKey("module.code"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="inactive")  # active | inactive | trial
    activatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivatedAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# Origines d'une transition (BE-041, matrice-etats-modules-et-droits.md section 2) : qui a
# déclenché la transition. Une origine ne vaut pas permission : elle sert à l'audit et aux règles
# d'autorité (ex. une suspension `security` n'est pas levée par un `client`).
ORIGINES_TRANSITION: tuple[str, ...] = ("client", "commercial", "security", "support", "automation", "platform")


class ModuleStateTransition(UUIDPrimaryKeyMixin, Base):
    """Journal append-only des transitions d'état (table `module_state_transitions`, BE-041).

    Une ligne par transition réussie. L'état courant d'un sujet (`subjectType`, `subjectId`) est
    le `toState` de sa dernière ligne, et sa version d'état est `stateVersionAfter`. Aucune ligne
    n'est modifiée ni supprimée : une correction est une nouvelle transition.

    Contraintes :
    - `(subjectType, subjectId, idempotencyKey)` unique : un rejeu de commande ne crée pas de ligne ;
    - `(subjectType, subjectId, stateVersionAfter)` unique (ajout de BE-041) : deux transitions
      concurrentes ne peuvent pas prendre la même version, la seconde échoue en conflit.

    `actorId` est obligatoire (pas de transition anonyme). `organizationId` est nul pour un sujet
    de plateforme. La fonction qui écrit ces lignes est `transitions.transitionner`.
    """

    __tablename__ = "module_state_transitions"
    __table_args__ = (
        UniqueConstraint(
            "subjectType", "subjectId", "idempotencyKey", name="uq_module_state_transitions_idempotence"
        ),
        UniqueConstraint(
            "subjectType", "subjectId", "stateVersionAfter", name="uq_module_state_transitions_version"
        ),
        {"comment": "Journal append-only des transitions d'état des modules (BE-041)."},
    )

    subjectType: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    subjectId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    fromState: Mapped[str] = mapped_column(String(50), nullable=False)
    toState: Mapped[str] = mapped_column(String(50), nullable=False)
    actorId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organizationId: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=True, index=True
    )
    origin: Mapped[str] = mapped_column(
        Enum(*ORIGINES_TRANSITION, name="module_transition_origin", native_enum=True),
        nullable=False,
        comment="Origine de la transition (client, commercial, security, support, automation, platform).",
    )
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    operationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    idempotencyKey: Mapped[str] = mapped_column(String(200), nullable=False)
    stateVersionBefore: Mapped[int] = mapped_column(Integer, nullable=False)
    stateVersionAfter: Mapped[int] = mapped_column(Integer, nullable=False)
    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ModuleCompatibilityEvaluation(UUIDPrimaryKeyMixin, Base):
    """Évaluation de compatibilité d'une version de module (table `module_compatibility_evaluations`, BE-044).

    Une ligne par évaluation demandée par la console plateforme. `result` vaut `compatible`,
    `incompatible` ou `unknown` (jamais `compatible` sans information, voir `compatibilite.py`).
    `reasons` est la liste des motifs (`DEPENDENCY_CYCLE`, `PREREQUISITE_MISSING`, ...). Les lignes
    sont append-only : une nouvelle évaluation est une nouvelle ligne.
    """

    __tablename__ = "module_compatibility_evaluations"
    __table_args__ = (
        {"comment": "Évaluations de compatibilité des versions de module (BE-044), append-only."},
    )

    moduleVersionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_version.id"), nullable=False, index=True
    )
    result: Mapped[str] = mapped_column(
        Enum("compatible", "incompatible", "unknown", name="module_compatibility_result", native_enum=True),
        nullable=False,
        comment="Résultat de l'évaluation (compatible, incompatible, unknown).",
    )
    reasons: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="Motifs de l'évaluation.")
    evaluatedAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), comment="Date de l'évaluation."
    )


class ModuleUpgradePlan(UUIDPrimaryKeyMixin, Base):
    """Plan de mise à jour d'un module entre deux versions (table `module_upgrade_plans`, BE-044).

    Le plan est seulement calculé et journalisé ; rien n'est exécuté. `forwardOnly` vaut vrai dès
    que `rollbackPossible` est faux. Aucune étape de retour arrière n'est proposée automatiquement
    (voir `compatibilite.construire_plan_mise_a_jour`).
    """

    __tablename__ = "module_upgrade_plans"
    __table_args__ = ({"comment": "Plans de mise à jour de module, calculés sans exécution (BE-044)."},)

    moduleId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("module.id"), nullable=False, index=True)
    fromVersion: Mapped[str] = mapped_column(String(50), nullable=False)
    toVersion: Mapped[str] = mapped_column(String(50), nullable=False)
    steps: Mapped[list] = mapped_column(JSON, nullable=False, default=list, comment="Étapes ordonnées du plan.")
    rollbackPossible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    forwardOnly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    createdAt: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Portées d'une permission déclarée par un module (BE-055) : organisation `{orgId}`, tenant, plateforme.
PORTEES_PERMISSION_MODULE: tuple[str, ...] = ("organization", "tenant", "platform")


class ModulePermission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Permission déclarée par une version d'un module (table `module_permissions`, BE-055).

    La déclaration appartient à la version, pas au module : deux versions peuvent déclarer le
    même code (l'unicité porte sur `(moduleVersionId, code)`), et seule la version installée
    fait foi pour savoir si un code est accordable (`declarations.exiger_permissions_declarees`).
    `scope` indique la portée de la permission (organisation, tenant ou plateforme).
    """

    __tablename__ = "module_permissions"
    __table_args__ = (
        UniqueConstraint("moduleVersionId", "code", name="uq_module_permissions_version_code"),
        {"comment": "Permissions déclarées par chaque version d'un module (BE-055)."},
    )

    moduleVersionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_version.id"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(150), nullable=False, comment="Code de permission (domaine.entite.action).")
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    scope: Mapped[str] = mapped_column(
        Enum(*PORTEES_PERMISSION_MODULE, name="module_permission_scope", native_enum=True),
        nullable=False,
        comment="Portée de la permission (organization, tenant, platform).",
    )


class ModuleInstallation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Installation technique d'un module pour une organisation (table `module_installations`, BE-047).

    Une ligne par tentative d'installation. `state` et `stateVersion` reflètent le dernier `toState`
    et `stateVersionAfter` du journal `module_state_transitions` (sujet `tenant_module`, BE-041) : le
    journal reste la trace faisant foi, cette ligne sert aux lectures courantes. `operationId` est
    l'identifiant de l'opération, renvoyé à l'appelant pour relire un résultat incertain.

    Contrainte : au plus une installation non `removed` par `(organizationId, moduleId)`, garantie par
    un index unique partiel (une ancienne installation retirée n'empêche pas une nouvelle).
    `lastErrorCode` porte le code d'erreur de la dernière étape en échec (ex. provisionnement).
    """

    __tablename__ = "module_installations"
    __table_args__ = (
        Index(
            "uq_module_installations_organisation_module_actif",
            "organizationId",
            "moduleId",
            unique=True,
            postgresql_where=text("state <> 'removed'"),
        ),
        {"comment": "Installations techniques des modules par organisation (BE-047)."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id"), nullable=False, index=True,
        comment="Organisation (tenant) qui installe le module.",
    )
    moduleId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module.id"), nullable=False, index=True
    )
    moduleVersionId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("module_version.id"), nullable=False, index=True,
        comment="Version installée ; doit être publiée et compatible au moment de l'installation.",
    )
    state: Mapped[str] = mapped_column(
        String(50), nullable=False, default="not_installed", server_default="not_installed",
        comment="État courant de l'installation (matrice d'états, BE-041).",
    )
    stateVersion: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
        comment="Version d'état : nombre de transitions journalisées.",
    )
    operationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, unique=True, default=uuid.uuid4,
        comment="Identifiant de l'opération d'installation (relecture par GET).",
    )
    lastErrorCode: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Code d'erreur de la dernière étape en échec."
    )
