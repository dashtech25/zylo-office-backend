"""Moteur de notification (BE-169) : audience, déduplication, suppression.

Rôle : à partir d'un événement d'origine déjà produit par un producteur métier, créer
une notification par destinataire éligible de l'audience de chaque règle qui lit ce type
d'événement. Le moteur ne livre rien : la livraison par canal relève de BE-170, qui fait
passer `statut` de `en_attente` à `envoyee` ou `echec`.

Décisions portées ici :
- CA-3 : le producteur doit pouvoir consulter le sujet. Le contrôle passe par le moteur
  d'autorisation unique (`app.core.authz.decide`, BE-226) ; le moteur ne réimplémente
  aucune règle d'accès (QE-PAR-27). Tout refus, y compris hors tenant ou sans identité,
  lève `403` PERMISSION_DENIED avant toute lecture de règle ou écriture de notification.
- CA-1 : l'audience est résolue à l'envoi (pas figée dans la règle), et chaque membre
  résolu reçoit une ligne `en_attente` s'il est éligible et consentant.
- CA-2 : un destinataire non éligible (compte suspendu ou supprimé) ou désinscrit de la
  catégorie (`CONSENT_SUPPRESSED`, BE-168) reçoit une ligne `supprimee` avec le motif
  `CONSENT_SUPPRESSED`. Ce motif est repris tel quel de la définition pour les deux cas ;
  l'écart entre « non éligible » et « désinscrit » reste à trancher (voir la doc de module).
- CA-4 : la ligne est insérée avec `ON CONFLICT DO NOTHING` sur la contrainte
  `(eventId, categorieCode, destinataireId)`. Un rejeu du même événement ne crée donc
  aucun doublon et ne renvoie que les lignes réellement nouvelles.
- CA-5 : les membres sont lus uniquement dans l'organisation de l'événement (jointure
  sur `organization_user`). Un membre d'un autre tenant n'apparaît jamais.

Audiences connues : `membres_organisation` (tous les membres de l'organisation). Toute
autre référence lève `422` SCHEMA_INVALID : une audience inconnue ne doit jamais être
résolue en silence vers une liste vide, qui masquerait une erreur de configuration.

Le moteur valide l'appartenance du type d'événement au catalogue au moment de la
configuration de la règle (BE-167) ; il ne le revérifie pas ici.

Documentation de module : `app/notifications/moteur.md`.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import decide
from app.core.errors import AppError
from app.identity.models import OrganizationUser, User
from app.notifications.models import Notification, RegleNotification
from app.notifications.preferences import verifier_envoi_autorise

# Référence d'audience supportée. Une seule valeur à ce stade ; l'ajout d'une audience
# passe par cette constante et par `_resoudre_audience`.
AUDIENCE_MEMBRES_ORGANISATION = "membres_organisation"

# Motif écrit dans `motifSuppression` pour une ligne `supprimee` (CA-2).
MOTIF_CONSENTEMENT = "CONSENT_SUPPRESSED"

STATUT_EN_ATTENTE = "en_attente"
STATUT_SUPPRIMEE = "supprimee"

# Nom de la contrainte d'unicité de `notification` (CA-4), cible du ON CONFLICT.
_CONTRAINTE_UNICITE = "uq_notification_event_categorie_destinataire"


@dataclass(frozen=True)
class _Destinataire:
    """Membre résolu pour une audience : identifiant et éligibilité à l'envoi."""

    utilisateur_id: uuid.UUID
    eligible: bool


async def _resoudre_audience(db: AsyncSession, tenant_id: uuid.UUID, audience: str) -> list[_Destinataire]:
    """Résout une référence d'audience en membres du tenant, à l'instant de l'envoi (CA-1, CA-5).

    Un compte est éligible s'il est `active` et non supprimé. Les résultats sont triés par
    identifiant pour que l'ordre d'insertion, donc les tests et les journaux, soit stable.
    Une référence inconnue lève `422` SCHEMA_INVALID.
    """
    if audience != AUDIENCE_MEMBRES_ORGANISATION:
        raise AppError(
            "SCHEMA_INVALID",
            "Référence d'audience de notification inconnue.",
            status_code=422,
            field_errors={"audience": ["référence inconnue"]},
        )
    lignes = await db.execute(
        select(User.id, User.status, User.deletedAt, OrganizationUser.status)
        .join(OrganizationUser, OrganizationUser.userId == User.id)
        .where(OrganizationUser.organizationId == tenant_id)
        .order_by(User.id)
    )
    # BE-212 (CA-4) : un membre suspendu dans le tenant n'est pas éligible, même si son
    # compte global est actif. L'envoi est limité aux membres actifs de ce tenant.
    return [
        _Destinataire(
            utilisateur_id=identifiant,
            eligible=statut == "active" and supprime_le is None and statut_membre == "active",
        )
        for identifiant, statut, supprime_le, statut_membre in lignes.all()
    ]


async def _motif_de_suppression(db: AsyncSession, destinataire: _Destinataire, categorie_code: str) -> str | None:
    """Renvoie `CONSENT_SUPPRESSED` si le destinataire ne doit pas recevoir la notification, sinon None.

    Non éligible : motif retenu d'après CA-2, sans appeler le contrôle de consentement.
    Éligible : `verifier_envoi_autorise` (BE-168) lève `CONSENT_SUPPRESSED` si l'utilisateur
    s'est désinscrit ; toute autre erreur est remontée sans être avalée.
    """
    if not destinataire.eligible:
        return MOTIF_CONSENTEMENT
    try:
        await verifier_envoi_autorise(db, utilisateur_id=destinataire.utilisateur_id, categorie_code=categorie_code)
    except AppError as erreur:
        if erreur.code == MOTIF_CONSENTEMENT:
            return MOTIF_CONSENTEMENT
        raise
    return None


async def produire_notifications(
    db: AsyncSession,
    *,
    eventId: uuid.UUID,
    evenementType: str,
    tenantId: uuid.UUID,
    producteur: User | None,
    permissionConsultation: str,
    sujetType: str,
    sujetId: uuid.UUID,
    sujetTenantId: uuid.UUID,
) -> list[Notification]:
    """Produit les notifications d'un événement d'origine et renvoie les lignes nouvellement créées.

    Paramètres :
    - `eventId` : identifiant de l'événement d'origine, clé de déduplication (CA-4) ;
    - `evenementType` : type d'événement, cherché dans `regle_notification` ;
    - `tenantId` : organisation de l'événement ; seule l'audience de ce tenant est résolue (CA-5) ;
    - `producteur` : utilisateur qui produit l'événement, jugé sur le droit de consulter le
      sujet ; `None` est refusé ;
    - `permissionConsultation`, `sujetType`, `sujetId`, `sujetTenantId` : droit et sujet
      passés à `decide` (BE-226) ; `sujetTenantId` est le tenant réel du sujet.

    Erreurs :
    - `403` PERMISSION_DENIED si le producteur n'a pas le droit de consulter le sujet (CA-3),
      sans aucune écriture ;
    - `422` SCHEMA_INVALID si une règle porte une audience inconnue.

    Effets : une ligne `notification` par (règle, destinataire résolu), statut `en_attente` ou
    `supprimee`. Les lignes déjà présentes pour le même événement ne sont pas recréées (CA-4).
    La transaction est validée en fin d'appel (même convention que `app.notifications.categories`).
    """
    decision = await decide(
        db,
        user=producteur,
        organization_id=tenantId,
        permission_code=permissionConsultation,
        resource_type=sujetType,
        resource_id=sujetId,
        resource_organization_id=sujetTenantId,
    )
    if not decision.allowed:
        raise AppError(
            "PERMISSION_DENIED",
            "Le producteur ne peut pas consulter le sujet de l'événement : notification refusée.",
            status_code=403,
        )

    regles = (
        await db.execute(select(RegleNotification).where(RegleNotification.evenementType == evenementType))
    ).scalars().all()

    identifiants_crees: list[uuid.UUID] = []
    for regle in regles:
        destinataires = await _resoudre_audience(db, tenantId, regle.audience)
        for destinataire in destinataires:
            motif = await _motif_de_suppression(db, destinataire, regle.categorieCode)
            insertion = (
                pg_insert(Notification)
                .values(
                    eventId=eventId,
                    categorieCode=regle.categorieCode,
                    destinataireId=destinataire.utilisateur_id,
                    statut=STATUT_SUPPRIMEE if motif else STATUT_EN_ATTENTE,
                    motifSuppression=motif,
                )
                .on_conflict_do_nothing(constraint=_CONTRAINTE_UNICITE)
                .returning(Notification.id)
            )
            identifiant = (await db.execute(insertion)).scalar_one_or_none()
            if identifiant is not None:
                identifiants_crees.append(identifiant)

    await db.commit()
    if not identifiants_crees:
        return []
    resultat = await db.execute(select(Notification).where(Notification.id.in_(identifiants_crees)).order_by(Notification.id))
    return list(resultat.scalars().all())
