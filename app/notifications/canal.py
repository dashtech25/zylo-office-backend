"""Adaptateur de canal et résultat de livraison (BE-170).

Rôle : définir l'interface que tout canal de livraison doit implémenter, le registre des
canaux disponibles, et l'écriture de chaque tentative dans la table `livraison`. Ce module
ne choisit aucun fournisseur : aucun canal n'est présumé (QE-PAR-04). Le canal est un nom
opaque fourni par l'appelant ; sans adaptateur enregistré sous ce nom, la livraison échoue.

Décisions portées ici :
- CA-1 : un canal absent ou qui lève `CHANNEL_UNAVAILABLE` (`503`, QE-PAR-01) ne fait pas
  échouer définitivement la notification. La tentative est tracée `retarde` avec une
  `prochaineTentativeAt` future, et l'erreur est relevée à l'appelant, qui planifie la
  nouvelle tentative.
- CA-2 : un rebond permanent ou une plainte passe la notification en `echec`. Toute
  notification ultérieure du même destinataire pour la même catégorie est refusée
  (`403` PERMISSION_DENIED) avant d'atteindre l'adaptateur. L'arrêt porte sur le couple
  (destinataire, catégorie) et non sur la catégorie seule.
- CA-3 : un résultat venant de l'extérieur est validé avant écriture. Un canal non
  enregistré, ou un résultat hors de `ResultatLivraison`, lève `422` SCHEMA_INVALID et
  n'écrit aucune ligne.
- CA-4 : le message remis à l'adaptateur (`MessageLivraison`) ne porte que des
  identifiants opaques. Aucune adresse, aucun nom ni contenu n'y figure, et ce module
  n'écrit aucune trace de journal. Un canal qui journalise doit le faire sans adresse.
- Refus interne : l'adaptateur ne reçoit une notification que si elle est `en_attente`
  et qu'aucun rebond ou plainte ne vise le même destinataire et la même catégorie. Sinon
  `403` PERMISSION_DENIED, sans appel au canal.

Transactions : chaque fonction publique valide sa propre transaction (`commit`) avant de
renvoyer ou de lever. La trace d'une tentative `retarde` est donc conservée même quand
l'erreur `CHANNEL_UNAVAILABLE` est relevée.

Documentation de module : `app/notifications/canal.md`.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.notifications.models import Livraison, Notification

# Code et statut HTTP d'un canal absent ou indisponible (CA-1, QE-PAR-01).
CODE_CANAL_INDISPONIBLE = "CHANNEL_UNAVAILABLE"
STATUS_CANAL_INDISPONIBLE = 503

# Délai de nouvelle tentative posé après `retarde`. La définition ne fixe pas de valeur ; le
# backoff réel relève de BE-164. Cette constante est une valeur provisoire, à remplacer
# par le calcul de backoff quand BE-164 sera livrée.
DELAI_NOUVELLE_TENTATIVE = timedelta(minutes=5)


class ResultatLivraison(StrEnum):
    """Résultat renvoyé par un canal pour une tentative de livraison.

    - `ACCEPTE` : le canal a pris le message en charge, sans confirmation de remise ;
    - `LIVRE` : remise confirmée au destinataire ;
    - `RETARDE` : remise différée, nouvelle tentative à `prochaineTentativeAt` ;
    - `REBOND` : rebond permanent ; arrête les envois au destinataire sur la catégorie ;
    - `PLAINTE` : plainte du destinataire ; arrête les envois sur la catégorie (CA-2) ;
    - `ECHEC` : échec définitif de cette tentative, sans arrêt des envois.
    """

    ACCEPTE = "accepte"
    LIVRE = "livre"
    RETARDE = "retarde"
    REBOND = "rebond"
    PLAINTE = "plainte"
    ECHEC = "echec"


# Résultats qui arrêtent les envois au destinataire sur la catégorie (CA-2).
RESULTATS_DESTRUCTIFS = (ResultatLivraison.REBOND, ResultatLivraison.PLAINTE)

# Statut de la notification après chaque résultat : `en_attente` tant qu'une nouvelle
# tentative est prévue, `envoyee` quand le canal a accepté ou livré, `echec` sinon.
_STATUT_APRES_RESULTAT: dict[ResultatLivraison, str] = {
    ResultatLivraison.ACCEPTE: "envoyee",
    ResultatLivraison.LIVRE: "envoyee",
    ResultatLivraison.RETARDE: "en_attente",
    ResultatLivraison.REBOND: "echec",
    ResultatLivraison.PLAINTE: "echec",
    ResultatLivraison.ECHEC: "echec",
}


@dataclass(frozen=True)
class MessageLivraison:
    """Données minimales remises à un canal pour une tentative (CA-4).

    Seuls des identifiants opaques sont transmis. Le canal résout lui-même le destinataire
    réel si besoin, sans que ce module ne lise ni ne transmette d'adresse.
    """

    notificationId: uuid.UUID
    categorieCode: str
    destinataireId: uuid.UUID


class AdaptateurCanal(Protocol):
    """Interface qu'un canal de livraison implémente.

    `livrer` reçoit un `MessageLivraison` et renvoie un `ResultatLivraison`. Un canal
    indisponible lève `AppError` avec le code `CHANNEL_UNAVAILABLE` (503). Toute autre
    exception (panne de la dépendance) est convertie par `livrer_notification` en
    `CHANNEL_UNAVAILABLE`, sans son détail (BE-258 CA-3).
    """

    async def livrer(self, message: MessageLivraison) -> ResultatLivraison: ...


# Registre en mémoire des canaux disponibles dans ce processus, par nom opaque.
_ADAPTATEURS: dict[str, AdaptateurCanal] = {}


def enregistrer_adaptateur(canal: str, adaptateur: AdaptateurCanal) -> None:
    """Enregistre un adaptateur sous le nom `canal`. Un nom déjà enregistré est remplacé."""
    _ADAPTATEURS[canal] = adaptateur


def retirer_adaptateur(canal: str) -> None:
    """Retire un adaptateur du registre. Sans effet si le nom est absent."""
    _ADAPTATEURS.pop(canal, None)


def obtenir_adaptateur(canal: str) -> AdaptateurCanal:
    """Renvoie l'adaptateur enregistré sous `canal`, ou lève 503 CHANNEL_UNAVAILABLE (CA-1)."""
    adaptateur = _ADAPTATEURS.get(canal)
    if adaptateur is None:
        raise AppError(
            CODE_CANAL_INDISPONIBLE,
            "Canal de notification non implémenté ou indisponible.",
            status_code=STATUS_CANAL_INDISPONIBLE,
        )
    return adaptateur


async def _notification_eligible(db: AsyncSession, notification_id: uuid.UUID) -> Notification:
    """Renvoie la notification si elle peut être remise à un canal, sinon lève 403 (refus interne).

    Non éligible : notification absente, statut autre que `en_attente`, ou rebond/plainte déjà
    enregistré pour le même destinataire et la même catégorie (CA-2).
    """
    notification = (
        await db.execute(select(Notification).where(Notification.id == notification_id))
    ).scalar_one_or_none()
    refus = AppError(
        "PERMISSION_DENIED",
        "Notification non éligible à la livraison.",
        status_code=403,
    )
    if notification is None or notification.statut != "en_attente":
        raise refus
    arret = (
        await db.execute(
            select(Livraison.id)
            .join(Notification, Livraison.notificationId == Notification.id)
            .where(
                Notification.destinataireId == notification.destinataireId,
                Notification.categorieCode == notification.categorieCode,
                Livraison.resultat.in_([str(resultat) for resultat in RESULTATS_DESTRUCTIFS]),
            )
            .limit(1)
        )
    ).first()
    if arret is not None:
        raise refus
    return notification


async def _ecrire_tentative(
    db: AsyncSession,
    notification: Notification,
    *,
    canal: str,
    resultat: ResultatLivraison,
    code_erreur: str | None = None,
    prochaine_tentative_at: datetime | None = None,
) -> Livraison:
    """Ajoute une ligne `livraison` pour une tentative, met à jour le statut, valide la transaction.

    Le numéro de tentative suit le nombre de lignes déjà présentes pour la notification ;
    la contrainte d'unicité `(notificationId, tentativeNo)` protège contre une écriture
    concurrente.
    """
    deja = (
        await db.execute(select(func.count()).select_from(Livraison).where(Livraison.notificationId == notification.id))
    ).scalar_one()
    livraison = Livraison(
        notificationId=notification.id,
        canal=canal,
        tentativeNo=deja + 1,
        resultat=resultat.value,
        codeErreur=code_erreur,
        prochaineTentativeAt=prochaine_tentative_at,
    )
    db.add(livraison)
    notification.statut = _STATUT_APRES_RESULTAT[resultat]
    await db.commit()
    await db.refresh(livraison)
    return livraison


def _valider_resultat(resultat: str) -> ResultatLivraison:
    """Convertit une valeur reçue en `ResultatLivraison`, ou lève 422 SCHEMA_INVALID (CA-3)."""
    try:
        return ResultatLivraison(resultat)
    except ValueError:
        raise AppError(
            "SCHEMA_INVALID",
            "Résultat de livraison hors énumération.",
            status_code=422,
            field_errors={"resultat": ["valeur inconnue"]},
        ) from None


async def livrer_notification(db: AsyncSession, *, notificationId: uuid.UUID, canal: str) -> Livraison:
    """Tente la remise d'une notification éligible via le canal `canal` et trace la tentative.

    Renvoie la ligne `livraison` écrite. Erreurs :
    - `403` PERMISSION_DENIED si la notification n'est pas éligible (refus interne, aucun appel
      au canal) ;
    - `503` CHANNEL_UNAVAILABLE si le canal est absent ou indisponible : la tentative est
      tracée `retarde` avec `prochaineTentativeAt`, puis l'erreur est relevée (CA-1) ;
    - `422` SCHEMA_INVALID si le canal renvoie un résultat hors énumération.
    """
    notification = await _notification_eligible(db, notificationId)
    message = MessageLivraison(
        notificationId=notification.id,
        categorieCode=notification.categorieCode,
        destinataireId=notification.destinataireId,
    )
    try:
        adaptateur = obtenir_adaptateur(canal)
        try:
            brut = await adaptateur.livrer(message)
        except AppError:
            raise
        except Exception as exc:  # noqa: BLE001 : panne de dépendance, jamais relayée telle quelle (BE-258 CA-3)
            raise AppError(
                CODE_CANAL_INDISPONIBLE,
                "Canal de notification indisponible.",
                status_code=STATUS_CANAL_INDISPONIBLE,
            ) from None
        resultat = _valider_resultat(brut)
    except AppError as erreur:
        if erreur.code != CODE_CANAL_INDISPONIBLE:
            raise
        await _ecrire_tentative(
            db,
            notification,
            canal=canal,
            resultat=ResultatLivraison.RETARDE,
            code_erreur=CODE_CANAL_INDISPONIBLE,
            prochaine_tentative_at=datetime.now(UTC) + DELAI_NOUVELLE_TENTATIVE,
        )
        raise
    return await _ecrire_tentative(db, notification, canal=canal, resultat=resultat)


async def enregistrer_resultat(
    db: AsyncSession,
    *,
    notificationId: uuid.UUID,
    canal: str,
    resultat: str,
) -> Livraison:
    """Enregistre un résultat de livraison reçu d'un canal, par exemple un rebond tardif (CA-3).

    Contrôles avant toute écriture :
    - `422` SCHEMA_INVALID si `canal` n'est pas enregistré dans le registre ;
    - `422` SCHEMA_INVALID si `resultat` n'appartient pas à `ResultatLivraison` ;
    - `403` PERMISSION_DENIED si la notification n'existe pas.
    """
    if canal not in _ADAPTATEURS:
        raise AppError(
            "SCHEMA_INVALID",
            "Résultat de livraison reçu d'un canal inconnu.",
            status_code=422,
            field_errors={"canal": ["canal inconnu"]},
        )
    valeur = _valider_resultat(resultat)
    notification = (
        await db.execute(select(Notification).where(Notification.id == notificationId))
    ).scalar_one_or_none()
    if notification is None:
        raise AppError("PERMISSION_DENIED", "Notification introuvable pour ce résultat.", status_code=403)
    return await _ecrire_tentative(db, notification, canal=canal, resultat=valeur)
