"""Livraison d'une notification sur un canal, avec enregistrement du résultat (BE-238).

Doc de module de `app/notifications/` pour la livraison. Ce module ne choisit ni
la catégorie ni l'audience (BE-167, BE-169) : il reçoit une notification déjà produite
par le moteur, puis appelle le canal demandé.

Règles tenues ici :
- CA-5 : avant tout appel au canal, le consentement de l'utilisateur pour la catégorie
  est vérifié (`verifier_envoi_autorise`, BE-168). Sans consentement, le canal n'est
  pas appelé, aucune ligne de livraison n'est écrite, et `CONSENT_SUPPRESSED` est levé.
- CA-3 : le résultat de chaque tentative est écrit dans `notification_delivery`. Un
  appel au canal qui lève une exception produit une ligne `echec` et fait passer la
  notification à `echec`. L'envoi n'est déclaré (`envoyee`) que si le canal a renvoyé
  normalement.
- Une notification `supprimee` par le moteur n'est jamais livrée : elle ne peut pas
  passer à `envoyee` ni à `echec` (erreur 409).

Contrat du canal (`envoi`) : une fonction synchrone qui reçoit la notification et
lève une exception en cas d'échec. Les canaux bloquants (ex. `pywebpush`) doivent être
enveloppés par l'appelant (`asyncio.to_thread`) avant d'être passés ici.

Limite connue : le compte des tentatives puis l'insertion ne sont pas verrouillés. Deux
livraisons concurrentes du même couple (notification, canal) peuvent se disputer le même
numéro de tentative ; la contrainte d'unicité fait alors échouer l'une des deux.
"""

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.notifications.models import Notification, NotificationDelivery
from app.notifications.preferences import verifier_envoi_autorise

RESULTAT_ENVOYEE = "envoyee"
RESULTAT_ECHEC = "echec"
STATUT_SUPPRIMEE = "supprimee"


async def livrer_notification(
    db: AsyncSession,
    *,
    notification: Notification,
    canal: str,
    envoi: Callable[[Notification], None],
) -> NotificationDelivery:
    """Tente l'envoi de `notification` sur `canal` et enregistre le résultat.

    Paramètres :
    - `notification` : ligne produite par le moteur (BE-169), statut `en_attente` ou `echec`
      pour une nouvelle tentative ;
    - `canal` : identifiant du canal, enregistré tel quel ;
    - `envoi` : fonction synchrone appelée une fois, qui lève en cas d'échec du canal.

    Retour : la ligne `NotificationDelivery` créée, avec `resultat` `envoyee` ou `echec`.
    Le canal en échec ne fait pas remonter d'exception : l'échec est un résultat enregistré.

    Erreurs :
    - `403` CONSENT_SUPPRESSED si le destinataire s'est désinscrit de la catégorie (CA-5) ;
      rien n'est écrit et le canal n'est pas appelé ;
    - `409` notification_supprimee si le moteur a déjà supprimé la notification.

    La transaction est validée en fin d'appel, comme dans `app.notifications.moteur`.
    """
    if notification.statut == STATUT_SUPPRIMEE:
        raise AppError(
            code="notification_supprimee",
            message="La notification a été supprimée par le moteur : elle ne peut pas être livrée.",
            status_code=409,
        )

    await verifier_envoi_autorise(
        db, utilisateur_id=notification.destinataireId, categorie_code=notification.categorieCode
    )

    tentatives_precedentes = await db.scalar(
        select(func.count())
        .select_from(NotificationDelivery)
        .where(NotificationDelivery.notificationId == notification.id, NotificationDelivery.canal == canal)
    )

    try:
        envoi(notification)
    except Exception:  # noqa: BLE001 - voulu : un canal en panne est un résultat enregistré, pas une erreur de requête
        resultat = RESULTAT_ECHEC
    else:
        resultat = RESULTAT_ENVOYEE

    ligne = NotificationDelivery(
        notificationId=notification.id,
        canal=canal,
        resultat=resultat,
        tentative=(tentatives_precedentes or 0) + 1,
        horodatage=datetime.now(timezone.utc),
    )
    db.add(ligne)
    notification.statut = resultat
    await db.commit()
    return ligne
