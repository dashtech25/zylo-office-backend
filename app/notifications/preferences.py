"""Préférences et consentement des utilisateurs par catégorie de notification (BE-168).

Ce module porte la décision de consentement : lecture et modification des préférences
de l'utilisateur courant, et contrôle d'envoi `verifier_envoi_autorise` utilisé par le
moteur de notification (BE-169). Il ne calcule ni les destinataires ni les envois.

Décisions portées ici :
- Ordre de décision (lecture comme écriture) : d'abord l'appartenance de la cible à
  l'organisation active (CA-5, `404` TENANT_MISMATCH, sans révéler l'existence de
  la cible), puis l'identité de l'acteur (CA-3, `403` PERMISSION_DENIED). Un refus ne
  lit ni n'écrit rien.
- Une seule ligne par (utilisateur, catégorie) ; `modifier_preference` la met à jour.
- Chaque modification écrit `horodatageConsentement` = instant courant UTC (CA-1), y
  compris une réinscription.
- Désinscription (`consentement = false`) : l'envoi de la catégorie est refusé par
  `CONSENT_SUPPRESSED` (403, action « ne pas envoyer ») (CA-2).
- Absence de ligne : aucune préférence n'est enregistrée, donc aucune suppression. Ce
  n'est pas une valeur par défaut de consentement présumée ; la question reste ouverte
  (QE-PAR-02, à trancher avant BE-169).
- Aucune plage de silence ni heure calme (CA-4, QE-PAR-14). La colonne `canal` n'est pas
  créée (QE-PAR-04).

Les routes sont dans `app/notifications/router.py` ; le modèle dans `models.py`
(`PreferenceNotification`). Documentation de route : `app/notifications/preferences.md`.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.identity.models import OrganizationUser
from app.notifications.models import CategorieNotification, PreferenceNotification

# Origine écrite dans `sourceConsentement` pour une décision prise par l'utilisateur
# lui-même via l'API. Les autres origines (ex. import) seront ajoutées à leur tâche.
SOURCE_UTILISATEUR = "utilisateur"


async def _exiger_membre_organisation(db: AsyncSession, organization_id: uuid.UUID, utilisateur_id: uuid.UUID) -> None:
    """Refuse `404` TENANT_MISMATCH si la cible n'appartient pas à l'organisation active.

    Le `404` (et non `403`) évite de révéler à un autre tenant que la cible existe (CA-5).
    """
    appartenance = await db.scalar(
        select(OrganizationUser.id).where(
            OrganizationUser.organizationId == organization_id,
            OrganizationUser.userId == utilisateur_id,
        )
    )
    if appartenance is None:
        raise AppError("TENANT_MISMATCH", "Ressource introuvable.", status_code=404)


def _exiger_soi_meme(acteur_id: uuid.UUID, utilisateur_id: uuid.UUID) -> None:
    """Refuse `403` PERMISSION_DENIED si l'acteur n'est pas la personne concernée (CA-3)."""
    if acteur_id != utilisateur_id:
        raise AppError(
            "PERMISSION_DENIED",
            "Seules vos propres préférences de notification sont accessibles.",
            status_code=403,
        )


async def lire_preferences(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
) -> list[PreferenceNotification]:
    """Renvoie les préférences enregistrées de `utilisateur_id` (CA-3, CA-5).

    Seules les catégories ayant une ligne sont renvoyées : aucune préférence n'est
    inventée pour une catégorie non renseignée (CA-4).
    """
    await _exiger_membre_organisation(db, organization_id, utilisateur_id)
    _exiger_soi_meme(acteur_id, utilisateur_id)
    resultat = await db.execute(
        select(PreferenceNotification)
        .where(PreferenceNotification.utilisateurId == utilisateur_id)
        .order_by(PreferenceNotification.categorieCode)
    )
    return list(resultat.scalars().all())


async def modifier_preference(
    db: AsyncSession,
    *,
    organization_id: uuid.UUID,
    acteur_id: uuid.UUID,
    utilisateur_id: uuid.UUID,
    categorie_code: str,
    consentement: bool,
) -> PreferenceNotification:
    """Crée ou met à jour le consentement de `utilisateur_id` pour une catégorie (CA-1).

    La catégorie doit exister (`404` NOTIFICATION_CATEGORY_NOT_FOUND). L'horodatage est
    celui de cette décision. Un refus (CA-3, CA-5) ne modifie rien.
    """
    await _exiger_membre_organisation(db, organization_id, utilisateur_id)
    _exiger_soi_meme(acteur_id, utilisateur_id)
    if await db.get(CategorieNotification, categorie_code) is None:
        raise AppError("NOTIFICATION_CATEGORY_NOT_FOUND", "Catégorie de notification introuvable.", status_code=404)

    maintenant = datetime.now(timezone.utc)
    preference = await db.scalar(
        select(PreferenceNotification).where(
            PreferenceNotification.utilisateurId == utilisateur_id,
            PreferenceNotification.categorieCode == categorie_code,
        )
    )
    if preference is None:
        preference = PreferenceNotification(
            utilisateurId=utilisateur_id,
            categorieCode=categorie_code,
        )
        db.add(preference)
    preference.consentement = consentement
    preference.horodatageConsentement = maintenant
    preference.sourceConsentement = SOURCE_UTILISATEUR
    await db.commit()
    await db.refresh(preference)
    return preference


async def verifier_envoi_autorise(db: AsyncSession, *, utilisateur_id: uuid.UUID, categorie_code: str) -> None:
    """Lève `403` CONSENT_SUPPRESSED si l'utilisateur s'est désinscrit de la catégorie (CA-2).

    Sans ligne ou avec consentement vrai, ne fait rien. Appelé par le moteur d'envoi
    (BE-169) avant chaque envoi.
    """
    consentement = await db.scalar(
        select(PreferenceNotification.consentement).where(
            PreferenceNotification.utilisateurId == utilisateur_id,
            PreferenceNotification.categorieCode == categorie_code,
        )
    )
    if consentement is False:
        raise AppError(
            "CONSENT_SUPPRESSED",
            "Envoi supprimé par le consentement.",
            status_code=403,
        )
