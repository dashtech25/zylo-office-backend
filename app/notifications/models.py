"""Modèles de la capacité Notifications partagée : abonnements Web Push, éléments
d'inbox explicitement adressés, catégories et règles de notification (BE-167).
Aucun producteur métier n'est branché dans ce module.

Tables : `notificationPushSubscription` (PushSubscription) et
`notification_inbox_item` (NotificationInboxItem). Les tables sont listées
dans l'inventaire des données (`app/data_inventory/registre.py`) : tout
renommage de table doit l'y reporter, sinon `tests/test_inventaire_donnees_be242.py`
échoue. Les noms de table suivent la règle de la tâche BE-037 : snake_case
pour les tables décidées depuis, camelCase pour les plus anciennes."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.shared.models import TimestampMixin, UUIDPrimaryKeyMixin


class PushSubscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Un abonnement Web Push par (utilisateur, endpoint navigateur) —
    `endpoint` est l'URL unique fournie par le navigateur au moment de
    `PushManager.subscribe()`, jamais réutilisée entre deux
    navigateurs/appareils différents (contrainte d'unicité dessus, pas sur
    `userId`)."""

    __tablename__ = "notificationPushSubscription"
    __table_args__ = (
        UniqueConstraint("endpoint", name="uq_notificationPushSubscription_endpoint"),
        {"comment": "Abonnement Web Push navigateur (RFC 8030) — module Notifications, 2026-09-20."},
    )

    userId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True)
    organizationId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    # Clés fournies par le navigateur à l'abonnement (chiffrement du payload
    # push côté serveur, standard Web Push) — jamais générées ici.
    p256dhKey: Mapped[str] = mapped_column(String(255), nullable=False)
    authKey: Mapped[str] = mapped_column(String(255), nullable=False)
    userAgent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class NotificationInboxItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Message interne explicitement adressé à un membre d'organisation.

    Table `notification_inbox_item` (snake_case, décision BE-037 ; renommée par
    la révision f5a6b7c8d9e0). Les index et la contrainte d'unicité gardent
    leurs noms camelCase d'origine, référencés par le service d'insertion.

    Idempotence : un même événement source ne produit qu'un item par
    destinataire (contrainte `uq_notificationInboxItem_event_recipient` sur
    organisation, destinataire, type et identifiant d'événement).

    Le stockage ne choisit ni catégorie produit ni canal de livraison. Aucun
    producteur métier n'est branché tant que le catalogue d'événements PH-13
    et la frontière Notifications/Alertes (ARC-007) ne sont pas validés.
    """

    __tablename__ = "notification_inbox_item"
    __table_args__ = (
        UniqueConstraint(
            "organizationId", "recipientUserId", "sourceEventType", "sourceEventId",
            name="uq_notificationInboxItem_event_recipient",
        ),
        Index("ix_notificationInboxItem_recipient_created", "organizationId", "recipientUserId", "createdAt"),
        Index("ix_notificationInboxItem_recipient_read", "organizationId", "recipientUserId", "readAt"),
        {"comment": "Notification in-app explicitement adressée; aucun canal ni rétention automatisée implicite."},
    )

    organizationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    recipientUserId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False
    )
    # Clé d'idempotence de l'événement source, fournie par un producteur
    # interne de confiance; aucun endpoint HTTP client ne peut créer d'item.
    sourceEventType: Mapped[str] = mapped_column(String(80), nullable=False)
    sourceEventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    readAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CategorieNotification(Base):
    """Catégorie de notification déclarée par la plateforme (BE-167).

    Clé naturelle `code` (identifiant stable, référencé par `regle_notification`).
    - `audienceRegle` : règle d'audience de la catégorie, obligatoire et non vide
      (CHECK en base, CA-1) ; sa résolution en destinataires relève de BE-169 ;
    - `canalDefaut` : canal présumé, NULL par défaut. Aucun canal n'est présumé
      (CA-4) ; la sémantique du canal par défaut reste QE-PAR-04 ;
    - `actif` : statut obligatoire, vrai à la création.
    """

    __tablename__ = "categorie_notification"
    __table_args__ = (
        CheckConstraint("length(btrim(\"audienceRegle\")) > 0", name="ck_categorie_notification_audience_non_vide"),
        CheckConstraint("length(btrim(code)) > 0", name="ck_categorie_notification_code_non_vide"),
        {"comment": "Catégories de notification et leur audience (BE-167), sans canal présumé."},
    )

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    libelle: Mapped[str] = mapped_column(String(200), nullable=False)
    audienceRegle: Mapped[str] = mapped_column(String(120), nullable=False)
    canalDefaut: Mapped[str | None] = mapped_column(String(40), nullable=True)
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class RegleNotification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Règle reliant un type d'événement du catalogue à une catégorie (BE-167).

    - `evenementType` : type d'événement, validé à l'écriture contre le catalogue
      (CA-2) ; une seule règle par couple (type, catégorie) ;
    - `categorieCode` : clé étrangère vers `categorie_notification.code` ;
    - `audience` : référence d'audience figée ici, résolue en destinataires à
      l'envoi uniquement (BE-169). Ne contient jamais une liste de personnes.
    La modification de la règle est réservée à l'autorité plateforme (CA-3).
    """

    __tablename__ = "regle_notification"
    __table_args__ = (
        UniqueConstraint("evenementType", "categorieCode", name="uq_regle_notification_evenement_categorie"),
        {"comment": "Règles événement vers catégorie et audience (BE-167), configurées par la plateforme."},
    )

    evenementType: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    categorieCode: Mapped[str] = mapped_column(
        String(80), ForeignKey("categorie_notification.code", ondelete="RESTRICT"), nullable=False
    )
    audience: Mapped[str] = mapped_column(String(120), nullable=False)


class PreferenceNotification(UUIDPrimaryKeyMixin, Base):
    """Consentement d'un utilisateur à une catégorie de notification (BE-168).

    - `utilisateurId` : utilisateur global concerné ; suppression en cascade avec le compte ;
    - `categorieCode` : catégorie visée, clé étrangère vers `categorie_notification.code` ;
    - `consentement` : vrai = envoi autorisé, faux = désinscription (CA-2) ;
    - `horodatageConsentement` : moment de la dernière décision de l'utilisateur (CA-1) ;
    - `sourceConsentement` : origine de la décision, écrite par le service.

    Une seule ligne par couple (utilisateur, catégorie) : la modification met à jour la
    ligne existante. Aucune plage de silence ni heure calme ne figure ici (CA-4). La
    colonne `canal` n'existe pas : sa sémantique est QE-PAR-04, et aucun canal n'est présumé.
    """

    __tablename__ = "preference_notification"
    __table_args__ = (
        UniqueConstraint("utilisateurId", "categorieCode", name="uq_preference_notification_utilisateur_categorie"),
        {"comment": "Consentement par utilisateur et catégorie de notification (BE-168)."},
    )

    utilisateurId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    categorieCode: Mapped[str] = mapped_column(
        String(80), ForeignKey("categorie_notification.code", ondelete="RESTRICT"), nullable=False
    )
    consentement: Mapped[bool] = mapped_column(Boolean, nullable=False)
    horodatageConsentement: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sourceConsentement: Mapped[str] = mapped_column(String(40), nullable=False)


class Notification(UUIDPrimaryKeyMixin, Base):
    """Notification produite par le moteur (BE-169) pour un destinataire.

    Une ligne par (événement d'origine, catégorie, destinataire). Le moteur crée
    les lignes ; le canal (BE-170) met à jour `statut` vers `envoyee` ou `echec`.

    - `statut` : `en_attente` (éligible et consentant), `supprimee` (motif dans
      `motifSuppression`, ex. `CONSENT_SUPPRESSED`), `envoyee`, `echec` ;
    - `eventId` : identifiant de l'événement d'origine, clé d'idempotence avec la
      catégorie et le destinataire (CA-4). Pas de clé étrangère : l'événement peut
      venir de l'outbox ou d'un producteur interne.

    Aucune colonne de tenant : le destinataire appartient à un seul tenant au moment
    de la résolution d'audience (CA-5), la trace par tenant reste dans l'événement.
    """

    __tablename__ = "notification"
    __table_args__ = (
        UniqueConstraint("eventId", "categorieCode", "destinataireId", name="uq_notification_event_categorie_destinataire"),
        CheckConstraint(
            "statut IN ('en_attente', 'supprimee', 'envoyee', 'echec')", name="ck_notification_statut"
        ),
        CheckConstraint(
            "(statut = 'supprimee') = (\"motifSuppression\" IS NOT NULL)",
            name="ck_notification_motif_suppression",
        ),
        {"comment": "Notification produite par le moteur (BE-169) : audience résolue à l'envoi, déduplication par événement."},
    )

    eventId: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    categorieCode: Mapped[str] = mapped_column(
        String(80), ForeignKey("categorie_notification.code", ondelete="RESTRICT"), nullable=False
    )
    destinataireId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statut: Mapped[str] = mapped_column(String(20), nullable=False)
    motifSuppression: Mapped[str | None] = mapped_column(String(80), nullable=True)
    creeAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class Livraison(UUIDPrimaryKeyMixin, Base):
    """Tentative de remise d'une notification à un canal (BE-170).

    Une ligne par tentative, numérotée par `tentativeNo` à partir de 1 ; l'unicité de
    `(notificationId, tentativeNo)` garde la numérotation sans trou ni doublon.

    - `canal` : nom opaque du canal ayant reçu la tentative. Aucun fournisseur n'est
      présumé (QE-PAR-04) : la colonne n'a pas de liste de valeurs en base ;
    - `resultat` : `accepte`, `livre`, `retarde`, `rebond`, `plainte` ou `echec`
      (CHECK en base, énumération `ResultatLivraison`) ;
    - `codeErreur` : code d'erreur de la tentative, renseigné pour `CHANNEL_UNAVAILABLE` ;
    - `prochaineTentativeAt` : échéance de la nouvelle tentative, renseignée pour `retarde`.

    Aucune adresse ni donnée personnelle du destinataire n'est stockée ici (CA-4) : le
    destinataire se lit via la notification.
    """

    __tablename__ = "livraison"
    __table_args__ = (
        UniqueConstraint("notificationId", "tentativeNo", name="uq_livraison_notification_tentative"),
        CheckConstraint(
            "resultat IN ('accepte', 'livre', 'retarde', 'rebond', 'plainte', 'echec')",
            name="ck_livraison_resultat",
        ),
        CheckConstraint('"tentativeNo" >= 1', name="ck_livraison_tentative_positive"),
        {"comment": "Tentatives de livraison d'une notification par canal (BE-170), sans donnée destinataire."},
    )

    notificationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canal: Mapped[str] = mapped_column(String(40), nullable=False)
    tentativeNo: Mapped[int] = mapped_column(Integer, nullable=False)
    resultat: Mapped[str] = mapped_column(String(20), nullable=False)
    codeErreur: Mapped[str | None] = mapped_column(String(80), nullable=True)
    prochaineTentativeAt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    creeAt: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class NotificationDelivery(UUIDPrimaryKeyMixin, Base):
    """Tentative d'envoi d'une notification sur un canal, avec son résultat (BE-238).

    Une ligne par tentative : `(notificationId, canal, tentative)` est unique, donc
    une nouvelle tentative sur le même canal ajoute une ligne au lieu d'écraser la
    précédente. Le résultat est `envoyee` ou `echec` ; un échec n'est jamais présenté
    comme un envoi (CA-3). La ligne est écrite par `app.notifications.livraison`.

    - `canal` : canal utilisé (ex. `web_push`), texte libre tant que QE-PAR-04 n'est
      pas tranché ;
    - `horodatage` : moment où le résultat a été constaté.
    """

    __tablename__ = "notification_delivery"
    __table_args__ = (
        UniqueConstraint("notificationId", "canal", "tentative", name="uq_notification_delivery_tentative"),
        CheckConstraint("resultat IN ('envoyee', 'echec')", name="ck_notification_delivery_resultat"),
        CheckConstraint("tentative >= 1", name="ck_notification_delivery_tentative_positive"),
        {"comment": "Tentatives d'envoi par canal et résultat (BE-238)."},
    )

    notificationId: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("notification.id", ondelete="CASCADE"), nullable=False, index=True
    )
    canal: Mapped[str] = mapped_column(String(40), nullable=False)
    resultat: Mapped[str] = mapped_column(String(20), nullable=False)
    tentative: Mapped[int] = mapped_column(Integer, nullable=False)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

