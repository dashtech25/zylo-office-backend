"""Feature flags côté serveur et déploiement canari (BE-251).

Intention
---------
Un flag ouvre une fonction à UN tenant explicitement ciblé, pour un temps borné.
Il ne remplace jamais les droits : `fonction_ouverte` exige d'abord la décision
du moteur d'autorisation unique (`app.core.authz.decide`, BE-226), puis l'état du
flag. Un flag actif n'accorde donc rien à un utilisateur non autorisé (CA-1).

Règles
------
- Portée : une ligne `feature_flags` par couple (clé, tenant). Un tenant non ciblé
  n'a pas de ligne et reçoit la valeur par défaut sûre, fermée (CA-4).
- Défaut sûr : `defaut_actif` vaut faux. Absence de ligne, ligne sans propriétaire,
  ligne sans expiration, ligne expirée : la fonction reste fermée (CA-2).
- Expiration obligatoire : `expire_le` est NOT NULL en base et requis par la route.
  Un canari ne dure que `FLAGS_DUREE_CANARI_HEURES` (CA-5) ; sans cette valeur,
  aucun canari ne démarre (échec fermé, code `canari_non_configure`).
- Arrêt : `canari_doit_s_arreter` compare un taux d'erreur observé au seuil
  `FLAGS_SEUIL_ARRET_CANARI`. Sans seuil configuré, le canari doit s'arrêter.
- Désactivation immédiate (CA-3) : aucune mise en cache. Chaque décision relit la
  ligne du flag ; une désactivation validée est effective à la décision suivante.
- Audit : chaque écriture de `modifier_flag` ajoute une ligne `flag_changes`
  dans la même transaction que la mise à jour ; l'appelant valide la transaction.
- Changement réservé à l'exploitation : la route (`app.release.flags_router`)
  passe par `app.operator.permissions.require_operator`. Ce module ne contrôle
  pas l'appelant : il suppose que la garde a déjà été franchie.

Valeurs NON DÉFINIES (définition BE-251, CA-5) : durée de canari et seuil d'arrêt
sont lus de `app.core.config.settings` ; aucune valeur par défaut.

Piège évité : un flag n'est jamais lu depuis un en-tête ou un corps d'interface.
La décision porte sur l'état serveur et les droits vérifiés.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.authz import decide
from app.core.config import settings
from app.core.database import Base
from app.core.errors import AppError
from app.identity.models import User
from app.shared.models import UUIDPrimaryKeyMixin


class FeatureFlag(UUIDPrimaryKeyMixin, Base):
    """État d'un flag pour un tenant (table `feature_flags`).

    `proprietaire_id` et `expire_le` sont NOT NULL : une ligne incomplète ne peut
    pas exister en base (CA-2). Pas de clé étrangère vers `user`, comme
    `release_records` : l'identifiant reste lisible si le compte disparaît.
    """

    __tablename__ = "feature_flags"
    __table_args__ = (
        UniqueConstraint("cle", "organization_id", name="uq_feature_flags_cle_organisation"),
        {"comment": "Feature flags par tenant : état, défaut sûr, propriétaire et expiration (BE-251)."},
    )

    cle: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization.id", ondelete="CASCADE"), nullable=False
    )
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Valeur retenue hors ligne valide (absence, expiration, contrôle échoué). Toujours faux.
    defaut_actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    proprietaire_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    modifie_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FlagChange(UUIDPrimaryKeyMixin, Base):
    """Trace d'un changement de flag (table `flag_changes`, audit).

    Une ligne par écriture de `modifier_flag`. `ancien_actif` est nul à la création.
    Les lignes ne sont jamais modifiées ni supprimées par ce module.
    """

    __tablename__ = "flag_changes"
    __table_args__ = ({"comment": "Journal des changements de feature flags (BE-251, audit)."},)

    cle: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    acteur_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    ancien_actif: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nouvel_actif: Mapped[bool] = mapped_column(Boolean, nullable=False)
    proprietaire_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    expire_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def controle_flag(flag: FeatureFlag, maintenant: datetime) -> list[str]:
    """Liste les anomalies qui empêchent un flag de s'ouvrir (CA-2).

    Retourne une liste vide si le flag est utilisable. Codes :
    - `proprietaire_absent` : aucun propriétaire désigné ;
    - `expiration_absente` : aucune date d'expiration ;
    - `expire` : la date d'expiration est atteinte ou dépassée.
    Une anomalie ne lève pas d'erreur : la décision reste fermée (échec fermé).
    """
    anomalies: list[str] = []
    if flag.proprietaire_id is None:
        anomalies.append("proprietaire_absent")
    if flag.expire_le is None:
        anomalies.append("expiration_absente")
    elif flag.expire_le <= maintenant:
        anomalies.append("expire")
    return anomalies


def valider_canari(expire_le: datetime, maintenant: datetime) -> None:
    """Refuse l'activation d'un canari dont la durée n'est pas bornée par la configuration (CA-5).

    - `FLAGS_DUREE_CANARI_HEURES` absente (NON DÉFINI) : `canari_non_configure`, 422 ;
    - expiration au-delà de `maintenant + durée` : `canari_hors_duree`, 422.
    La désactivation n'appelle pas cette fonction : couper une fonction ne demande
    aucune durée.
    """
    duree_heures = settings.FLAGS_DUREE_CANARI_HEURES
    if duree_heures is None:
        raise AppError(
            code="canari_non_configure",
            message="La durée de canari n'est pas configurée.",
            status_code=422,
        )
    if expire_le > maintenant + timedelta(hours=duree_heures):
        raise AppError(
            code="canari_hors_duree",
            message="L'expiration dépasse la durée de canari configurée.",
            status_code=422,
        )


def canari_doit_s_arreter(taux_erreur: float) -> bool:
    """Vrai si le taux d'erreur observé impose l'arrêt du canari (CA-5).

    Le seuil vient de `FLAGS_SEUIL_ARRET_CANARI`. Sans seuil configuré, la réponse
    est vraie : l'échec est fermé, un canari sans seuil ne continue pas.
    """
    seuil = settings.FLAGS_SEUIL_ARRET_CANARI
    if seuil is None:
        return True
    return taux_erreur > seuil


async def fonction_ouverte(
    db: AsyncSession,
    *,
    cle: str,
    organization_id: uuid.UUID,
    user: User | None,
    permission_code: str,
) -> bool:
    """Décide si la fonction protégée par `cle` est ouverte pour `user` dans ce tenant.

    Ouverte seulement si les deux conditions sont vraies :
    1. le moteur d'autorisation (`decide`, BE-226) accorde `permission_code` ;
    2. la ligne du flag existe pour CE tenant, est active, et son contrôle est vide.
    Un refus de droits ou un flag fermé donne `False`, sans exception : la route
    appelante traduit ce booléen en 403.
    """
    decision = await decide(db, user=user, organization_id=organization_id, permission_code=permission_code)
    if not decision.allowed:
        return False
    flag = (
        await db.execute(
            select(FeatureFlag).where(FeatureFlag.cle == cle, FeatureFlag.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if flag is None:
        return False
    if controle_flag(flag, datetime.now(timezone.utc)):
        return False
    return bool(flag.actif)


async def modifier_flag(
    db: AsyncSession,
    *,
    cle: str,
    organization_id: uuid.UUID,
    actif: bool,
    proprietaire_id: uuid.UUID,
    expire_le: datetime,
    acteur_id: uuid.UUID,
) -> FeatureFlag:
    """Crée ou met à jour l'état d'un flag pour un tenant, et trace le changement.

    - Activation (`actif=True`) : la durée est contrôlée par `valider_canari` (CA-5).
    - Désactivation : aucune contrainte de durée, la coupure est immédiate (CA-3).
    - Dans les deux cas, propriétaire et expiration sont fournis par l'appelant
      (CA-2) ; une expiration naïve est lue en UTC.
    Écrit une ligne `flag_changes` dans la transaction. Ne valide pas la transaction :
    l'appelant fait le `commit`, pour qu'écriture et audit réussissent ou échouent ensemble.
    """
    if expire_le.tzinfo is None:
        expire_le = expire_le.replace(tzinfo=timezone.utc)
    maintenant = datetime.now(timezone.utc)
    if actif:
        valider_canari(expire_le, maintenant)

    flag = (
        await db.execute(
            select(FeatureFlag).where(FeatureFlag.cle == cle, FeatureFlag.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    ancien_actif = flag.actif if flag is not None else None
    if flag is None:
        flag = FeatureFlag(cle=cle, organization_id=organization_id)
        db.add(flag)
    flag.actif = actif
    flag.defaut_actif = False
    flag.proprietaire_id = proprietaire_id
    flag.expire_le = expire_le
    flag.modifie_le = maintenant

    db.add(
        FlagChange(
            cle=cle,
            organization_id=organization_id,
            acteur_id=acteur_id,
            ancien_actif=ancien_actif,
            nouvel_actif=actif,
            proprietaire_id=proprietaire_id,
            expire_le=expire_le,
            cree_le=maintenant,
        )
    )
    await db.flush()
    return flag
