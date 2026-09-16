"""Service du module Alertes (capacité partagée) — extrait de
`app/modules/zylo_liquid/service.py` (2026-09-15, Phase 3 de la migration
monolithe modulaire, voir ARCHITECTURE.md). Logique inchangée, seul
l'emplacement bouge (à l'exception de deux renommages documentés
ci-dessous et d'une extension mineure de signature — voir plus bas).

Point d'entrée public de ce module : tout appelant externe (aujourd'hui
`zylo_liquid` et `location`, demain un éventuel module métier
supplémentaire) passe UNIQUEMENT par les fonctions publiques de ce
fichier — `upsert_active_alert`/`auto_resolve_alert`/`list_alerts`/
`get_alert`/`acknowledge_alert`/`resolve_alert` — jamais par un accès
direct à `app.alerts.models.Alert` ni par une construction locale
d'`Alert(...)`, contrat renforcé par `import-linter` (voir `.importlinter`
à la racine). `_find_open_alert`/`_alert_to_response`/`_get_alert_and_tank`
restent privés : ils ne sont utilisés qu'à l'intérieur de ce fichier.

Renommage Phase 3 : `_upsert_active_alert` -> `upsert_active_alert` et
`_auto_resolve_alert` -> `auto_resolve_alert` (suppression du underscore
préfixe) — ces deux fonctions étaient déjà appelées par une dizaine de
fonctions productrices d'alertes ailleurs dans `zylo_liquid`/`location`
avant l'extraction (usage interne au même fichier) ; devenues des points
d'entrée réellement publics une fois appelées depuis un autre module,
elles perdent leur underscore, qui n'aurait plus été honnête. Les
fonctions productrices elles-mêmes (`run_alert_evaluation_for_tank`,
`_create_alert_if_not_already_active`, `evaluate_price_missing_alert`,
`evaluate_sensor_mapping_missing_alert`, `evaluate_calibration_missing_alert`,
`evaluate_structural_alerts_for_organization`, la réconciliation de
livraison, `location._qualify_truck_stop`...) restent dans leurs modules
d'origine (décision actée du plan de migration, §Phase 3 — pas encore
d'événements de domaine, voir Phase 5) et appellent désormais ces deux
fonctions publiques au lieu de manipuler `Alert` ou les anciennes fonctions
privées directement.

Extension mineure Phase 3 : `_find_open_alert`/`upsert_active_alert`
gagnent un paramètre `truck_id` optionnel (en plus de `station_id`, déjà
optionnel). Avant cette phase, `location._qualify_truck_stop` construisait
sa propre `Alert(truckId=..., stationId=None, ...)` directement, sans
passer par `_upsert_active_alert` (qui ne savait dédupliquer que par
station) — exactement le point documenté comme « en attente de la Phase 3 »
dans la docstring de `app/location/service.py`. Cette extension permet à
`_qualify_truck_stop` d'appeler `upsert_active_alert` comme tout autre
producteur, avec la même déduplication anti-spam que les alertes
station/cuve — aucun changement de schéma, un paramètre optionnel de plus
sur une fonction déjà interne au module.

Dépendance délibérée et documentée vers `app.modules.zylo_liquid.models`
(pas l'inverse) : `list_alerts`/`_get_alert_and_tank` ont besoin de
`Station`/`Truck`/`Tank` pour leurs jointures externes de portée (une
alerte peut être rattachée à une station OU à un camion, jamais aux deux,
voir la contrainte CHECK sur `Alert`) et pour l'affichage (nom de cuve
dans le résumé d'audit). C'est un accès en lecture seule à des types de
zylo_liquid, jamais à sa logique métier (`service.py`/`router.py`) —
même patron que `app/location/service.py` vers `Truck`/`TRUCK_READ`, voir
sa docstring. `app/alerts/models.py`, lui, n'importe aucun modèle
zylo_liquid (voir sa propre docstring) : seul `service.py` a ce besoin,
pour interroger au-delà de la seule table `Alert`."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.models import Alert
from app.alerts.permissions import ALERT_READ
from app.alerts.schemas import AlertResponse
from app.audit.service import record_audit_event
from app.core.database import AsyncSessionLocal
from app.core.errors import AppError
from app.modules.zylo_liquid.models import Station, Tank, Truck
from app.rbac.service import list_visible_resource_ids
from app.shared.pagination import PaginationParams
from app.shared.schemas import Page, PageMeta


def _to_naive_utc(value: datetime | None) -> datetime | None:
    """Normalise un datetime potentiellement "aware" (ex. suffixe Z, ISO
    8601 UTC standard envoyé par le frontend via `Date.toISOString()`) vers
    naïf en UTC — convention déjà établie dans zylo_liquid (comparaisons
    toujours en naïf UTC), dupliquée ici (fonction pure, quelques lignes)
    plutôt qu'importée depuis `zylo_liquid.service` pour ne pas créer de
    dépendance vers sa logique métier. Sans cette normalisation, comparer
    directement à une colonne naïve lève `TypeError: can't subtract
    offset-naive and offset-aware datetimes` côté asyncpg dès qu'un client
    envoie un datetime avec fuseau explicite."""
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# Refonte alertes Étape 2 (2026-09, décisions D2/D3/D4/D7) — gravité
# calculée une seule fois ici (plus jamais dérivée côté frontend depuis un
# `Set` dupliqué) ; reprend exactement l'ancien `CRITICAL_TYPES` frontend
# pour les 4 valeurs "critical", complété pour les types restants.
SEVERITY_BY_ALERT_TYPE = {
    "level_high": "critical",
    "leak": "critical",
    "delivery_discrepancy": "critical",
    "delivery_undeclared": "critical",
    "level_high_pre_alarm": "high",
    "level_low": "high",
    "water": "high",
    "sensor_offline": "medium",
    "delivery_declaration_pending": "low",
    "price_missing": "medium",
    "sensor_mapping_missing": "medium",
    "calibration_missing": "medium",
}

# D2 : types pour lesquels une source de vérité mesurable existe et peut
# être relue automatiquement — `resolve_alert` (résolution manuelle
# déclarative) leur est interdit, seule la fermeture automatique
# (`auto_resolve_alert`, appelée par l'évaluation qui a créé l'alerte) peut
# les refermer. Un utilisateur qui veut signaler une prise en charge sans
# attendre la vérification automatique utilise `acknowledge_alert` — jamais
# `resolve_alert`.
AUTO_VERIFIABLE_ALERT_TYPES = {
    "level_high", "level_high_pre_alarm", "level_low", "water", "sensor_offline",
    "leak", "delivery_discrepancy", "delivery_undeclared", "delivery_declaration_pending",
}


async def _find_open_alert(
    db: AsyncSession,
    *,
    station_id: uuid.UUID | None = None,
    truck_id: uuid.UUID | None = None,
    tank_id: uuid.UUID | None,
    product_id: uuid.UUID | None,
    alert_type: str,
) -> Alert | None:
    result = await db.execute(
        select(Alert).where(
            Alert.stationId == station_id,
            Alert.truckId == truck_id,
            Alert.tankId == tank_id,
            Alert.productId == product_id,
            Alert.type == alert_type,
            Alert.status.in_(["active", "acknowledged"]),
        )
    )
    return result.scalar_one_or_none()


async def upsert_active_alert(
    db: AsyncSession,
    *,
    station_id: uuid.UUID | None = None,
    alert_type: str,
    triggered_at,
    triggered_value: float | None = None,
    threshold_value: float | None = None,
    tank_id: uuid.UUID | None = None,
    product_id: uuid.UUID | None = None,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
    truck_id: uuid.UUID | None = None,
) -> Alert | None:
    """N'ouvre jamais une deuxième alerte active/acquittée du même type pour
    la même portée (cuve et/ou produit) — évite le spam. Si une alerte est
    déjà ouverte, sa valeur est mise à jour (avant cette refonte,
    `triggeredValue` restait figé à la première détection tant que l'alerte
    restait active — Étape 1, constat #7).

    `truck_id` (Phase 3) : portée camion, en alternative à `station_id`
    (jamais les deux, voir la contrainte CHECK sur `Alert`) — ajouté pour
    que `location._qualify_truck_stop` (alerte `truck_stop_unqualified`)
    bénéficie de la même déduplication que les autres producteurs, au lieu
    de construire `Alert` directement comme avant cette phase."""
    existing = await _find_open_alert(
        db, station_id=station_id, truck_id=truck_id, tank_id=tank_id, product_id=product_id, alert_type=alert_type
    )
    if existing is not None:
        existing.triggeredAt = triggered_at
        existing.triggeredValue = triggered_value
        existing.thresholdValue = threshold_value
        await db.flush()
        return None
    alert = Alert(
        stationId=station_id,
        truckId=truck_id,
        tankId=tank_id,
        productId=product_id,
        type=alert_type,
        severity=SEVERITY_BY_ALERT_TYPE.get(alert_type, "medium"),
        status="active",
        triggeredAt=triggered_at,
        triggeredValue=triggered_value,
        thresholdValue=threshold_value,
        sourceType=source_type,
        sourceId=source_id,
    )
    db.add(alert)
    await db.flush()
    return alert


async def auto_resolve_alert(
    db: AsyncSession,
    *,
    station_id: uuid.UUID | None = None,
    tank_id: uuid.UUID | None,
    product_id: uuid.UUID | None,
    alert_type: str,
    resolved_at,
    truck_id: uuid.UUID | None = None,
) -> None:
    """D2 : referme automatiquement une alerte dont la condition réelle a
    disparu, constatée par le service qui l'a évaluée — jamais via un clic
    humain pour les types listés dans `AUTO_VERIFIABLE_ALERT_TYPES`.
    `resolvedByUserId` reste NULL : personne n'a fermé l'alerte, le système
    a constaté la disparition de la condition."""
    alert = await _find_open_alert(
        db, station_id=station_id, truck_id=truck_id, tank_id=tank_id, product_id=product_id, alert_type=alert_type
    )
    if alert is None:
        return
    alert.status = "resolved"
    alert.resolvedAt = resolved_at
    alert.resolutionMethod = "auto_verified"
    await db.flush()


async def find_alert_in_window(
    db: AsyncSession, *, tank_id: uuid.UUID, alert_type: str, window_start, window_end
) -> Alert | None:
    """Présence/absence d'une alerte d'un type donné sur une cuve dans une
    fenêtre temporelle, indépendamment de son statut courant (active,
    acquittée ou déjà résolue) — utilisé par la réconciliation
    qualité/eau de `zylo_liquid` (`evaluate_quality_check_declaration_reconciliation`)
    pour éviter qu'elle construise elle-même une requête directe sur
    `Alert` (règle §3.1 d'ARCHITECTURE.md : jamais de requête directe sur
    les tables d'un autre module). Contrairement à `_find_open_alert`, pas
    de déduplication ici, pas de filtre de portée station/produit — une
    simple lecture."""
    result = await db.execute(
        select(Alert).where(
            Alert.tankId == tank_id,
            Alert.type == alert_type,
            Alert.triggeredAt >= window_start,
            Alert.triggeredAt <= window_end,
        )
    )
    return result.scalars().first()


def _alert_to_response(alert: Alert) -> AlertResponse:
    """`stationId` vient désormais directement de l'alerte (D4) — plus
    besoin de la cuve pour construire la réponse, ce qui fonctionne aussi
    pour les types sans cuve (ex. `price_missing`)."""
    return AlertResponse(
        id=alert.id,
        stationId=alert.stationId,
        truckId=alert.truckId,
        tankId=alert.tankId,
        productId=alert.productId,
        type=alert.type,
        severity=alert.severity,
        status=alert.status,
        sourceType=alert.sourceType,
        sourceId=alert.sourceId,
        triggeredAt=alert.triggeredAt,
        triggeredValue=float(alert.triggeredValue) if alert.triggeredValue is not None else None,
        thresholdValue=float(alert.thresholdValue) if alert.thresholdValue is not None else None,
        acknowledgedAt=alert.acknowledgedAt,
        acknowledgedByUserId=alert.acknowledgedByUserId,
        resolvedAt=alert.resolvedAt,
        resolvedByUserId=alert.resolvedByUserId,
        resolutionMethod=alert.resolutionMethod,
        resolutionNote=alert.resolutionNote,
    )


async def list_alerts(
    db: AsyncSession,
    organization_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    pagination: PaginationParams,
    station_id: uuid.UUID | None,
    tank_id: uuid.UUID | None,
    type_filter: str | None,
    status_filter: str | None,
    from_date,
    to_date,
    truck_id: uuid.UUID | None = None,
) -> Page:
    """Corrigé — filtrait auparavant uniquement par organisation, jamais par
    la portée réelle de l'utilisateur (même constat que `list_stations`,
    découvert en testant un scénario de démo réel avec des gérants/pompistes
    scopés station, mission « vente-maintenant-reglementation ») : un
    utilisateur scopé à une station ne doit voir que les alertes de celle-ci.

    Filtre directement sur `Alert.stationId`/`Alert.tankId` (D4) — plus
    besoin de passer par `Tank` pour la portée, ce qui inclut correctement
    les types d'alerte sans cuve."""
    from_date = _to_naive_utc(from_date)
    to_date = _to_naive_utc(to_date)
    if from_date is not None and to_date is not None and from_date > to_date:
        raise AppError(code="invalid_date_range", message="from_date doit être antérieure ou égale à to_date.", status_code=422)

    sees_all, visible_station_ids = await list_visible_resource_ids(db, actor_user_id, organization_id, ALERT_READ, "station")
    if not sees_all and not visible_station_ids:
        raise AppError(code="permission_denied", message=f"Permission manquante : {ALERT_READ}.", status_code=403)

    # Étape 2 tracking — une alerte peut désormais être rattachée à un
    # camion (`truckId`) plutôt qu'à une station (`stationId` nullable
    # depuis cette migration) : un INNER JOIN strict sur Station
    # exclurait silencieusement toute alerte de camion. Jointure externe
    # sur les deux, filtre d'organisation vérifié via l'une ou l'autre.
    stmt = (
        select(Alert)
        .outerjoin(Station, Station.id == Alert.stationId)
        .outerjoin(Truck, Truck.id == Alert.truckId)
        .where(or_(Station.organizationId == organization_id, Truck.organizationId == organization_id))
    )
    if not sees_all:
        # Un accès scopé par station ne couvre jamais une alerte de
        # camion (les camions ne sont pas rattachés à une station) —
        # comportement inchangé pour ces utilisateurs.
        stmt = stmt.where(Alert.stationId.in_(visible_station_ids))
    if station_id is not None:
        stmt = stmt.where(Alert.stationId == station_id)
    if truck_id is not None:
        stmt = stmt.where(Alert.truckId == truck_id)
    if tank_id is not None:
        stmt = stmt.where(Alert.tankId == tank_id)
    if type_filter is not None:
        stmt = stmt.where(Alert.type == type_filter)
    if status_filter is not None:
        stmt = stmt.where(Alert.status == status_filter)
    if from_date is not None:
        stmt = stmt.where(Alert.triggeredAt >= from_date)
    if to_date is not None:
        stmt = stmt.where(Alert.triggeredAt <= to_date)
    stmt = stmt.order_by(Alert.triggeredAt.desc())

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = await db.execute(stmt.limit(pagination.limit).offset(pagination.offset))
    rows = result.scalars().all()
    data = [_alert_to_response(alert) for alert in rows]
    return Page(data=data, meta=PageMeta(total=total or 0, limit=pagination.limit, offset=pagination.offset))


async def _get_alert_and_tank(db: AsyncSession, organization_id: uuid.UUID, alert_id: uuid.UUID) -> tuple[Alert, Tank | None]:
    """`Tank` en LEFT JOIN — uniquement pour l'affichage (nom de cuve dans
    le résumé d'audit), `None` pour les types d'alerte sans cuve."""
    result = await db.execute(
        select(Alert, Tank)
        # Étape 2 tracking — jointure externe sur Station, une alerte de
        # camion (stationId NULL) ne doit jamais être exclue par un INNER
        # JOIN strict (même correction que list_alerts ci-dessus).
        .outerjoin(Station, Station.id == Alert.stationId)
        .outerjoin(Truck, Truck.id == Alert.truckId)
        .outerjoin(Tank, Tank.id == Alert.tankId)
        .where(Alert.id == alert_id, or_(Station.organizationId == organization_id, Truck.organizationId == organization_id))
    )
    row = result.first()
    if row is None:
        raise AppError(code="alert_not_found", message="Alerte introuvable.", status_code=404)
    return row


async def get_alert(db: AsyncSession, organization_id: uuid.UUID, alert_id: uuid.UUID) -> AlertResponse:
    alert, _tank = await _get_alert_and_tank(db, organization_id, alert_id)
    return _alert_to_response(alert)


async def acknowledge_alert(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, alert_id: uuid.UUID
) -> AlertResponse:
    """D3 : déclaration d'intention humaine ("je m'en occupe") — ne referme
    jamais l'alerte, ne vérifie rien de la condition réelle. Réservé aux
    alertes encore `active` (acquitter une alerte déjà acquittée ou résolue
    n'a pas de sens)."""
    alert, tank = await _get_alert_and_tank(db, organization_id, alert_id)
    if alert.status != "active":
        raise AppError(
            code="alert_not_active",
            message="Seule une alerte active peut être acquittée.",
            status_code=409,
        )
    alert.status = "acknowledged"
    alert.acknowledgedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    alert.acknowledgedByUserId = actor_user_id
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.alert.acknowledge",
        entity_type="Alert",
        entity_id=alert.id,
        summary=f"Acquittement de l'alerte {alert.type}" + (f" (cuve {tank.displayName})" if tank else ""),
        scope_resource_type="station",
        scope_resource_id=alert.stationId,
    )
    await db.commit()
    await db.refresh(alert)
    return _alert_to_response(alert)


async def resolve_alert(
    db: AsyncSession, organization_id: uuid.UUID, actor_user_id: uuid.UUID, alert_id: uuid.UUID, resolution_note: str | None
) -> AlertResponse:
    """D2 : réservé aux types sans vérification automatique possible — pour
    tout type listé dans `AUTO_VERIFIABLE_ALERT_TYPES`, la fermeture ne peut
    venir que du service qui a constaté la disparition de la condition
    réelle (`auto_resolve_alert`), jamais d'un clic humain non vérifié.
    `resolutionNote` devient obligatoire : une fermeture manuelle sans
    vérification automatique exige une justification tracée."""
    alert, tank = await _get_alert_and_tank(db, organization_id, alert_id)
    if alert.status == "resolved":
        raise AppError(code="alert_already_resolved", message="Cette alerte est déjà résolue.", status_code=409)
    if alert.type in AUTO_VERIFIABLE_ALERT_TYPES:
        raise AppError(
            code="alert_requires_automatic_verification",
            message="Ce type d'alerte se referme automatiquement dès que la condition réelle disparaît — utilisez l'acquittement pour signaler une prise en charge.",
            status_code=422,
        )
    if not resolution_note:
        raise AppError(
            code="resolution_note_required",
            message="Une justification est obligatoire pour résoudre manuellement ce type d'alerte.",
            status_code=422,
        )
    alert.status = "resolved"
    alert.resolvedAt = datetime.now(timezone.utc).replace(tzinfo=None)
    alert.resolvedByUserId = actor_user_id
    alert.resolutionMethod = "manual_justified"
    alert.resolutionNote = resolution_note
    await record_audit_event(
        db,
        organization_id,
        actor_user_id,
        action="zyloLiquid.alert.resolve",
        entity_type="Alert",
        entity_id=alert.id,
        summary=f"Résolution de l'alerte {alert.type}" + (f" (cuve {tank.displayName})" if tank else ""),
        scope_resource_type="station",
        scope_resource_id=alert.stationId,
    )
    await db.commit()
    await db.refresh(alert)
    return _alert_to_response(alert)


async def handle_truck_stop_unqualified(
    *,
    truck_id: uuid.UUID,
    alert_type: str,
    triggered_at,
    source_type: str | None = None,
    source_id: uuid.UUID | None = None,
) -> None:
    """Handler de l'événement de domaine `TruckStopUnqualified` (Phase 5,
    voir `app.shared.events` et la docstring de
    `app.location.service.run_truck_stop_detection`, premier cas d'usage
    réel du registre d'événements en mémoire). Ouvre sa propre session —
    jamais celle de l'appelant, qui a déjà committé (ou va committer,
    selon l'ordre choisi par le producteur) au moment où cet événement est
    publié ; ce handler ne doit dépendre d'aucun état de la transaction qui
    a déclenché l'événement, seulement du `payload` reçu."""
    async with AsyncSessionLocal() as db:
        await upsert_active_alert(
            db, truck_id=truck_id, alert_type=alert_type, triggered_at=triggered_at,
            source_type=source_type, source_id=source_id,
        )
        await db.commit()
