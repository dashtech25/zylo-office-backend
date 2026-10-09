"""Service du module Notifications (capacité partagée, core) — pour
l'instant un seul canal, Web Push navigateur (RFC 8030, via `pywebpush`).

Découplage par événement de domaine (`app.shared.events`, même mécanisme
que `app.location` -> `app.alerts` depuis la Phase 5 de la migration
monolithe modulaire — voir la docstring de `app.location.service`) :
`app.alerts.service.upsert_active_alert` publie `"AlertCreated"` avec
toutes les données nécessaires en kwargs (jamais une référence à
re-résoudre) plutôt que d'importer ce module directement — Notifications
n'importe donc rien d'`app.alerts` (ni `.models` ni `.permissions`), et
`ALERT_READ` est redupliqué ici en chaîne littérale (voir commentaire sur
`_ALERT_READ_PERMISSION_CODE`), même tolérance que la duplication déjà
acceptée ailleurs dans le projet (ex. le CHECK SQL du type d'alerte,
dupliqué du modèle Python). Le handler abonné (`handle_alert_created`,
inscrit dans `app/main.py`) reste volontairement minimal : il ne fait que
planifier `_notify_new_alert` en tâche de fond, jamais de travail bloquant
dans le handler lui-même (voir sa docstring)."""

import asyncio
import json
import logging
import uuid

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.core.database import AsyncSessionLocal
from app.identity.models import OrganizationUser
from app.modules.zylo_liquid.models import Station, Truck
from app.notifications.models import PushSubscription
from app.notifications.schemas import CreatePushSubscriptionRequest
from app.rbac.service import user_has_permission

logger = logging.getLogger(__name__)

# Dupliqué depuis `app.alerts.permissions.ALERT_READ` (chaîne stable, déjà
# seedée en base — voir sa docstring) plutôt qu'importé, pour que
# `app.notifications` n'ait besoin d'aucun import d'`app.alerts` (contrat
# `capabilities-never-import-each-other` étendu à ce module, voir
# `.importlinter`).
_ALERT_READ_PERMISSION_CODE = "zyloLiquid.alert.read"


async def create_push_subscription(
    db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, data: CreatePushSubscriptionRequest
) -> PushSubscription:
    """Ré-abonnement (même `endpoint`, ex. après un `unsubscribe`/
    `subscribe` navigateur) : met à jour les clés plutôt que de dupliquer
    la ligne — `endpoint` est contraint unique en base."""
    existing = (await db.execute(select(PushSubscription).where(PushSubscription.endpoint == data.endpoint))).scalar_one_or_none()
    if existing is not None:
        # Correction T-004b (lot 2) : un endpoint déjà enregistré pour un
        # AUTRE utilisateur ou une AUTRE organisation n'est jamais rattaché
        # au demandeur (sinon les alertes d'une organisation partent vers le
        # navigateur d'une autre). Le ré-abonnement reste permis pour le même
        # utilisateur dans la même organisation, comme décrit ci-dessus.
        if existing.userId != user_id or existing.organizationId != organization_id:
            raise AppError(
                code="push_subscription_endpoint_taken",
                message="Cet abonnement navigateur est déjà rattaché à un autre compte.",
                status_code=409,
            )
        existing.userId = user_id
        existing.organizationId = organization_id
        existing.p256dhKey = data.keys.p256dh
        existing.authKey = data.keys.auth
        existing.userAgent = data.userAgent
        await db.commit()
        await db.refresh(existing)
        return existing

    subscription = PushSubscription(
        userId=user_id,
        organizationId=organization_id,
        endpoint=data.endpoint,
        p256dhKey=data.keys.p256dh,
        authKey=data.keys.auth,
        userAgent=data.userAgent,
    )
    db.add(subscription)
    await db.commit()
    await db.refresh(subscription)
    return subscription


async def delete_push_subscription(db: AsyncSession, organization_id: uuid.UUID, user_id: uuid.UUID, subscription_id: uuid.UUID) -> None:
    subscription = (
        await db.execute(
            select(PushSubscription).where(
                PushSubscription.id == subscription_id,
                PushSubscription.organizationId == organization_id,
                PushSubscription.userId == user_id,
            )
        )
    ).scalar_one_or_none()
    if subscription is None:
        return
    await db.delete(subscription)
    await db.commit()


async def _resolve_recipient_user_ids(db: AsyncSession, organization_id: uuid.UUID, station_id: uuid.UUID | None) -> list[uuid.UUID]:
    """Destinataires d'une alerte : tout membre de l'organisation qui a
    `ALERT_READ` sur la portée de l'alerte (la station si connue, sinon
    l'organisation entière) — réutilise l'algorithme RBAC existant
    (`user_has_permission`), jamais une deuxième logique de portée
    dupliquée ici. Nombre de membres par organisation faible en pratique
    (réseau de stations, pas un grand public) : une vérification par membre
    est largement suffisante, pas besoin d'une requête SQL dédiée."""
    member_ids = (
        (await db.execute(select(OrganizationUser.userId).where(OrganizationUser.organizationId == organization_id)))
        .scalars()
        .all()
    )
    recipients: list[uuid.UUID] = []
    for user_id in member_ids:
        allowed = await user_has_permission(
            db, user_id, organization_id, _ALERT_READ_PERMISSION_CODE,
            resource_type="station" if station_id else None,
            resource_id=station_id,
        )
        if allowed:
            recipients.append(user_id)
    return recipients


def _send_push(subscription: PushSubscription, payload: str) -> bool:
    """Retourne False si l'abonnement est mort (410/404 — navigateur
    désinstallé, permission révoquée) : l'appelant le supprime alors en
    base plutôt que de re-tenter indéfiniment un endpoint mort."""
    try:
        webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dhKey, "auth": subscription.authKey},
            },
            data=payload,
            vapid_private_key=settings.VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"},
        )
        return True
    except WebPushException as exc:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in (404, 410):
            return False
        logger.exception("Échec d'envoi push (endpoint=%s, status=%s)", subscription.endpoint, status_code)
        return True  # erreur transitoire : ne pas supprimer l'abonnement


async def _resolve_organization_id(db: AsyncSession, station_id: uuid.UUID | None, truck_id: uuid.UUID | None) -> uuid.UUID | None:
    """`Alert` ne stocke pas `organizationId` directement (voir
    `app/alerts/models.py`) — dérivé ici depuis la station/le camion reçus
    dans le payload de l'événement. Le navire (`vesselId`) n'est pas géré :
    Zylo Tanker ne produit pas encore d'alertes déclenchant une
    notification push."""
    if station_id is not None:
        station = await db.get(Station, station_id)
        return station.organizationId if station else None
    if truck_id is not None:
        truck = await db.get(Truck, truck_id)
        return truck.organizationId if truck else None
    return None


def handle_alert_created(
    alert_id: uuid.UUID,
    alert_type: str,
    severity: str,
    station_id: uuid.UUID | None = None,
    truck_id: uuid.UUID | None = None,
) -> None:
    """Handler abonné à l'événement de domaine `"AlertCreated"` (inscrit
    dans `app/main.py`, voir `app.shared.events.subscribe`) — publié par
    `app.alerts.service.upsert_active_alert` UNIQUEMENT quand il vient de
    CRÉER une alerte (jamais sur une simple mise à jour, pour ne pas
    spammer à chaque cycle de télémétrie tant que la condition persiste).

    Reste volontairement synchrone et quasi instantané : ne fait que
    planifier `_notify_new_alert` en tâche de fond (`asyncio.create_task`),
    jamais de travail bloquant ici — `app.shared.events.publish` attend
    chaque handler abonné, un handler lent ralentirait donc directement
    `upsert_active_alert`, et donc la création de l'alerte elle-même."""
    task = asyncio.create_task(
        _notify_new_alert(alert_id=alert_id, alert_type=alert_type, severity=severity, station_id=station_id, truck_id=truck_id)
    )
    task.add_done_callback(lambda t: t.exception() and logger.exception("Échec de notification push (alerte=%s)", alert_id, exc_info=t.exception()))


async def _notify_new_alert(
    alert_id: uuid.UUID, alert_type: str, severity: str, station_id: uuid.UUID | None, truck_id: uuid.UUID | None
) -> None:
    """Session dédiée, jamais celle de l'appelant : l'événement est publié
    par `upsert_active_alert` avant le commit de son propre appelant (pas
    de mécanisme dans `app.shared.events` pour garantir "après commit" ici
    sans toucher la dizaine de producteurs d'alertes existants) — mais
    toutes les données de l'alerte elle-même arrivent en paramètres, sans
    relecture de la table `Alert` : la seule dépendance à une donnée
    externe potentiellement pas encore visible est `Station`/`Truck`, qui
    existent forcément déjà avant qu'une alerte les concernant ne soit
    créée (pas de course possible sur cette partie-là)."""
    if not settings.VAPID_PRIVATE_KEY:
        return  # Web Push non configuré (dev sans clés VAPID) — silencieux, jamais une erreur.

    async with AsyncSessionLocal() as db:
        organization_id = await _resolve_organization_id(db, station_id, truck_id)
        if organization_id is None:
            return

        recipient_ids = await _resolve_recipient_user_ids(db, organization_id, station_id)
        if not recipient_ids:
            return

        subscriptions = (
            (await db.execute(select(PushSubscription).where(PushSubscription.userId.in_(recipient_ids))))
            .scalars()
            .all()
        )
        if not subscriptions:
            return

        payload = json.dumps(
            {
                "title": f"Alerte {severity}",
                "body": f"{alert_type} — {station_id or truck_id}",
                "alertId": str(alert_id),
                "severity": severity,
                "type": alert_type,
            }
        )
        stale_ids: list[uuid.UUID] = []
        for subscription in subscriptions:
            # `pywebpush` est synchrone/bloquant (requête HTTP) — délégué à
            # un thread pour ne jamais geler la boucle d'événements asyncio
            # (partagée avec tout le reste du process, y compris les
            # requêtes HTTP en cours).
            if not await asyncio.to_thread(_send_push, subscription, payload):
                stale_ids.append(subscription.id)

        if stale_ids:
            for subscription in subscriptions:
                if subscription.id in stale_ids:
                    await db.delete(subscription)
            await db.commit()
